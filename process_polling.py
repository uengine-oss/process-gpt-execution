from fastapi import HTTPException
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import Document
from langserve import add_routes
from langchain.output_parsers.json import SimpleJsonOutputParser  # JsonOutputParser 임포트
from pydantic import BaseModel
from typing import List, Optional, Any
from code_executor import execute_python_code
from langchain_core.runnables import RunnableLambda
from datetime import datetime
import time

from database import fetch_process_definition, fetch_process_instance, fetch_organization_chart, fetch_ui_definition_by_activity_id, fetch_user_info, get_vector_store, fetch_workitem_with_submitted_status, fetch_workitem_by_proc_inst_and_activity
from database import upsert_process_instance, upsert_completed_workitem, upsert_next_workitems, upsert_chat_message, upsert_todo_workitems, upsert_workitem, delete_workitem
from database import ProcessInstance
import uuid
import json

# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-4o", streaming=True)
vision_model = ChatOpenAI(model="gpt-4-vision-preview", max_tokens = 4096, streaming=True)


# parser 생성
import re
class CustomJsonOutputParser(SimpleJsonOutputParser):
    def parse(self, text: str) -> dict:
        # Extract JSON from markdown if present
        match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            raise ValueError("No JSON content found within backticks.")
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")
# Replace the existing parser with our custom parser
parser = CustomJsonOutputParser()


prompt = PromptTemplate.from_template(
    """
    Now, you're going to create an interactive system similar to a BPM system that helps our company's employees understand various processes and take the next steps when they start a process or are curious about the next steps.

    - Process Definition: {processDefinitionJson}

    - Process Instance Id: {instance_id}
    - Process Instance Data: {instance_variables_data}
        
    - Organization Chart: {organizationChart}
    
    - User Information: {user_info}
    
    - Role Bindings: {role_bindings}

    - Currently Running Activities: {current_activity_ids}

    - Users Currently Running Activities: {current_user_ids}
    
    - Currently Running Activity's Form Fields: {form_fields}
    
    - Received Message From Current Step:
    
      activityId: "{activity_id}",  // the activityId is not included in the Currently Running Activities or is the next activityId than Current Running Activities, it must never be added to completedActivities to return the activityId as complete and must be reported in cannotProceedErrors.
      user: "{user_email}",
      submitted form values: {form_values},
      submitted answer: "{answer}"    // If no form values have been submitted, assign the values in the form field using the submitted answers. Based on the current running activity form fields. If the readonly="true" fields are not entered, never return an error and ignore it. But if fields with readonly="false" are not entered, return the error "DATA_FIELD_NOT_EXIST"
    
    - Today is:  {today}
    
    - Process Instance Name Pattern: "{instance_name_pattern}"  // If there is no process instance name pattern, the key_value format of parameterValue, along with the process definition name, is the default for the instance name pattern. e.g. 휴가신청_이름_홍길동_사유_개인일정_시작일_20240701
    
    Given the current state, tell me which next step activity should be executed. Return the result in a valid json format:
    The data changes and role binding changes should be derived from the user submitted data or attached image OCR. 
    At this point, the data change values must be written in Python format, adhering to the process data types declared in the process definition. For example, if a process variable is declared as boolean, it should be true/false.
    Information about completed activities must be returned.
    If the person responsible for the next activity is an external customer, the nextUserEmail included in nextActivities must be returned customer email. Customer emails must be found in submitted form values or process instance data. Never write customer emails at will or return non-external ones. Instances will be broken.
    If the condition of the sequence is not met for progression to the next step, it cannot be included in nextActivities and must be reported in cannotProceedErrors.
    startEvent/endEvent is not an activity id. Never be included in completedActivities/nextActivities.
    If the user-submitted data is insufficient, refer to the process data to extract the value.
    When an image is input, the process activity is completed based on the analyzed contents by analyzing the image.
    
    result should be in this JSON format:
    {{
        "instanceId": "{instance_id}",
        "instanceName": "process instance name",
        "processDefinitionId": "{process_definition_id}",
        "fieldMappings":
        [{{
            "key": "process data key", // Replace with _ if there is a space, Process Definition 에서 없는 데이터는 추가하지 않음. 프로세스 정의 데이터에 이메일이나 이름 같은 변수가 존재하지만 값이 누락된 경우 역할 바인딩에서 적절한 값을 알아서 지정하여 필드 매핑해줄 것.
            "name": "process data name",
            "value": <value for changed data>  // Refer to the data type of this process variable. For example, if the type of the process variable is Date, calculate and assign today's date. If the type of variable is a form, assign the JSON format.
        }}],

        "roleBindings": {role_bindings},
        "roleBindingChanges":
        [{{
            "roleName": "name of role",
            "userId": "email address for the role"
        }}],
        
        "completedActivities":
        [{{
            "completedActivityId": "the id of completed activity id", // Not Return if completedActivityId is "startEvent".
            "completedUserEmail": "the email address of completed activity's role",
            "result": "DONE" // The result of the completed activity
        }}],
        
        "nextActivities":
        [{{
            "nextActivityId": "the id of next activity id", // Not Return "END_PROCESS" if nextActivityId is "endEvent".
            "nextUserEmail": "the email address of next activity's role",
            "result": "IN_PROGRESS | PENDING | DONE", // The result of the next activity
            "messageToUser": "해당 액티비티를 수행할 유저에게 어떤 입력값을 입력해야 (output_data) 하는지, 준수사항(checkpoint)들은 무엇이 있는지, 어떤 정보를 참고해야 하는지(input_data)" // Returns a description of the process end if nextActivityId is "endEvent".
        }}],

        "cannotProceedErrors":   // return errors if cannot proceed to next activity 
        [{{
            "type": "PROCEED_CONDITION_NOT_MET" | "SYSTEM_ERROR" | "DATA_FIELD_NOT_EXIST"
            "reason": "explanation for the error in Korean"
        }}],
        
        "description": "description of the completed activities and the next activities and what the user who will perform the task should do in Korean"

    }}
    """
    )


# Pydantic model for process execution
class Activity(BaseModel):
    nextActivityId: Optional[str] = None
    nextUserEmail: Optional[str] = None
    result: Optional[str] = None

class CompletedActivity(BaseModel):
    completedActivityId: Optional[str] = None
    completedUserEmail: Optional[str] = None
    result: Optional[str] = None

class RoleBindingChange(BaseModel):
    roleName: str
    userId: Any

class FieldMapping(BaseModel):
    key: str
    name: str
    value: Any

class ProceedError(BaseModel):
    type: str
    reason: Any

class ProcessResult(BaseModel):
    instanceId: str
    instanceName: str
    fieldMappings: Optional[List[FieldMapping]] = None
    roleBindingChanges: Optional[List[RoleBindingChange]] = None
    nextActivities: Optional[List[Activity]] = None
    completedActivities: Optional[List[CompletedActivity]] = None
    processDefinitionId: str
    result: Optional[str] = None
    cannotProceedErrors: Optional[List[ProceedError]] = None
    description: str

def check_external_customer_and_send_email(activity_obj, user_email, process_instance, process_definition):
    """
    Check that the next activity's role is assigned to external customer.
    If the next activity's role is assigned to external customer, send an email to the external customer.
    """
    try:
        # Determine if the role is for an external customer
        role_name = activity_obj.role
        role_info = next((role for role in process_definition.roles if role.name == role_name), None)
        
        if role_info and role_info.endpoint == "external_customer":
            # Get customer email from role_info
            if user_email == "external_customer":
                customer_email = next((variable["value"] for variable in process_instance.variables_data if variable["key"] == "customer_email"), None)
            else:
                customer_email = user_email
            
            if customer_email:
                if (process_instance.tenant_id == "localhost"):
                    base_url = "http://localhost:8088/external-forms"
                else:
                    tenant_id = process_instance.tenant_id
                    base_url = f"https://{tenant_id}.process-gpt.io/external-forms"
                
                proc_def_id = process_definition.processDefinitionId
                proc_inst_id = process_instance.proc_inst_id
                external_form_id = activity_obj.tool.replace("formHandler:", "")
                activity_id = activity_obj.id
                
                external_form_url = f"{base_url}/{external_form_id}?process_definition_id={proc_def_id}&activity_id={activity_id}&process_instance_id={proc_inst_id}"
                
                additional_info = {
                    "support_email": "help@uengine.org"
                }
                
                from smtp_handler import generate_email_template, send_email
                # 이메일 템플릿 생성
                email_template = generate_email_template(activity_obj, external_form_url, additional_info)
                title = f"'{activity_obj.name}' 를 진행해주세요."
                # 이메일 전송
                send_email(subject=title, body=email_template, to_email=customer_email)
                
                return True
    except Exception as e:
        # Log the error but don't stop the process
        print(f"Failed to send notification to external customer: {str(e)}")
        return False

def execute_next_activity(process_result_json: dict, tenant_id: Optional[str] = None) -> str:
    try:
        process_result = ProcessResult(**process_result_json)
        process_instance = None
        status = ""
        if not fetch_process_instance(process_result.instanceId, tenant_id):
            if process_result.instanceId == "new" or '.' not in process_result.instanceId:
                instance_id = f"{process_result.processDefinitionId.lower()}.{str(uuid.uuid4())}"
                status = "RUNNING"
            else:
                instance_id = process_result.instanceId
            process_instance = ProcessInstance(
                proc_inst_id=instance_id,
                proc_inst_name=f"{process_result.instanceName}",
                role_bindings=[rb.model_dump() for rb in (process_result.roleBindingChanges or [])],
                current_activity_ids=[],
                current_user_ids=[],
                variables_data=[],
                status=status,
                tenant_id=tenant_id
            )
            
            existing_role_bindings = process_result_json.get("roleBindings", [])
            if existing_role_bindings:
                formatted_role_bindings = [{"roleName": rb.get("name"), "userId": rb.get("endpoint")} for rb in existing_role_bindings]
                if process_instance.role_bindings:
                    process_instance.role_bindings.extend(formatted_role_bindings)
                else:
                    process_instance.role_bindings = formatted_role_bindings
        else:
            process_instance = fetch_process_instance(process_result.instanceId, tenant_id)
           
        process_definition = process_instance.process_definition
        
        if process_result.fieldMappings:
            for data_change in process_result.fieldMappings:
                form_entry = next((item for item in process_instance.variables_data if isinstance(item["value"], dict) and data_change.key in item["value"]), None)
                
                if form_entry:
                    form_entry["value"][data_change.key] = data_change.value
                else:
                    variable = {
                        "key": data_change.key,
                        "name": data_change.name,
                        "value": data_change.value
                    }
                    existing_variable = next((item for item in process_instance.variables_data if item["key"] == data_change.key), None)
                    if existing_variable:
                        existing_variable.update(variable)
                    else:
                        process_instance.variables_data.append(variable)


        all_user_emails = set()
        if process_result.nextActivities:
            for activity in process_result.nextActivities:
                if activity.nextActivityId == "endEvent" or activity.nextActivityId == "END_PROCESS" or activity.nextActivityId == "end_event":
                    process_instance.status = "COMPLETED"
                    process_instance.current_activity_ids = []
                    break
                if process_definition.find_gateway_by_id(activity.nextActivityId):
                    next_activities = process_definition.find_next_activities(activity.nextActivityId)
                    if next_activities:
                        process_instance.current_activity_ids = [act.id for act in next_activities]
                        process_instance.status = "RUNNING"
                        process_result_json["nextActivities"] = []
                        next_activity_dicts = [
                            Activity(
                                nextActivityId=act.id,
                                nextUserEmail=activity.nextUserEmail,
                                result="IN_PROGRESS"
                            ).model_dump() for act in next_activities
                        ]
                        process_result_json["nextActivities"].extend(next_activity_dicts)
                    else:
                        process_instance.status = "COMPLETED"
                        process_instance.current_activity_ids = []
                        process_result_json["nextActivities"] = []
                        break
                        
                elif activity.result == "IN_PROGRESS" and activity.nextActivityId not in process_instance.current_activity_ids:
                    process_instance.current_activity_ids = [activity.nextActivityId]
                    process_instance.status = "RUNNING"
                else:
                    process_instance.current_activity_ids.append(activity.nextActivityId)
                    activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
                
                # check if the next activity is assigned to external customer and send an email
                activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
                check_external_customer_and_send_email(activity_obj, activity.nextUserEmail, process_instance, process_definition)
                
            all_user_emails.update(activity.nextUserEmail for activity in process_result.nextActivities)
        if len(process_result.nextActivities) == 0:
            process_instance.status = "COMPLETED"
            process_instance.current_activity_ids = []
        for activity in process_result.completedActivities:
            all_user_emails.add(activity.completedUserEmail)
        
        current_user_ids_set = set(process_instance.current_user_ids)
        updated_user_emails = current_user_ids_set.union(all_user_emails)
        
        process_instance.current_user_ids = list(updated_user_emails)
        
        result = None

        for activity in process_result.nextActivities:
            activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
            if activity_obj and activity_obj.type == "scriptTask":
                env_vars = {}
                for variable in process_instance.variables_data:
                    if variable["value"] is None:
                        continue
                    if isinstance(variable["value"], list):
                        variable["value"] = ', '.join(map(str, variable["value"]))
                    if isinstance(variable["value"], dict):
                        variable["value"] = json.dumps(variable["value"])
                    env_vars[variable["key"]] = variable["value"]
                result = execute_python_code(activity_obj.pythonCode, env_vars=env_vars)
                
                if result.returncode != 0:
                    # script task 의 python code 실행 에러
                    process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id)]
                    process_result_json["result"] = result.stderr
                else:
                    process_result_json["result"] = result.stdout
                    # script task 의 python code 실행 성공
                    process_instance.current_activity_ids = [
                        act_id for act_id in process_instance.current_activity_ids
                        if act_id != activity_obj.id
                    ]
                    
                    end_activity = process_definition.find_end_activity()
                    if end_activity and activity_obj.id == end_activity.id:
                        process_instance.status = "COMPLETED"
                        process_instance.current_activity_ids = ['end_event']
                        
                    process_result_json["nextActivities"] = [
                        Activity(**act) for act in process_result_json.get("nextActivities", [])
                        if act.get("nextActivityId") != activity_obj.id
                    ]
                    completed_activity = CompletedActivity(
                        completedActivityId=activity_obj.id,
                        completedUserEmail=activity.nextUserEmail,
                        result="DONE"
                    )
                    completed_activity_dict = completed_activity.dict()
                    process_result_json["completedActivities"].append(completed_activity_dict)
                    
                # process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id)]
            else:
                result = (f"Next activity {activity.nextActivityId} is not a ScriptActivity or not found.")
                process_result_json["result"] = result
                
                
        upsert_todo_workitems(process_instance.dict(), process_result_json, process_definition, tenant_id)
        
        workitems = None
        message_json = json.dumps({"description": ""})
        upsert_completed_workitem(process_instance.dict(), process_result_json, process_definition, tenant_id)
        workitems = upsert_next_workitems(process_instance.dict(), process_result_json, process_definition, tenant_id)
        _, process_instance = upsert_process_instance(process_instance, tenant_id)
        message_json = json.dumps({"description": process_result.description})
        if process_result.cannotProceedErrors:
            reason = ""
            for error in process_result.cannotProceedErrors:
                reason += error.reason + "\n"
            message_json = json.dumps({"description": reason})
        upsert_chat_message(process_instance.proc_inst_id, message_json, True, tenant_id)
        
        # Updating process_result_json with the latest process instance details and execution result
        process_result_json["instanceId"] = process_instance.proc_inst_id
        process_result_json["instanceName"] = process_instance.proc_inst_name
        # Ensure workitem is not None before accessing its id
        if workitems:
            process_result_json["workitemIds"] = [workitem.id for workitem in workitems]
        else:
            process_result_json["workitemIds"] = []
        
        content_str = json.dumps(process_instance.dict(exclude={'process_definition'}), ensure_ascii=False, indent=2)
        metadata = {
            "tenant_id": process_instance.tenant_id,
            "type": "process_instance"
        }

        vector_store = get_vector_store()
        vector_store.add_documents([
            Document(
                page_content=content_str,
                metadata=metadata
            )
        ])
        
        return json.dumps(process_result_json)
    except Exception as e:
        message_json = json.dumps({"description": str(e)})
        upsert_chat_message(process_instance.proc_inst_id, message_json, True, tenant_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


# execute_chain = (
#     prompt | model | parser | execute_next_activity
# )


import asyncio
from database import setting_database


async def handle_workitem(workitem):
    if workitem['retry'] >= 3:
        return
    
    activity_id = workitem['activity_id']
    process_definition_id = workitem['proc_def_id']
    process_instance_id = workitem['proc_inst_id']
    tenant_id = workitem['tenant_id']

    process_definition_json = fetch_process_definition(process_definition_id, tenant_id)
    process_instance = fetch_process_instance(process_instance_id, tenant_id) if process_instance_id != "new" else None
    organization_chart = fetch_organization_chart(tenant_id)
    if workitem['user_id'] != "external_customer":
        user_info = fetch_user_info(workitem['user_id'])
    else:
        user_info = {
            "name": "external_customer",
            "email": workitem['user_id']
        }
    today = datetime.now().strftime("%Y-%m-%d")
    ui_definition = fetch_ui_definition_by_activity_id(process_definition_id, activity_id, tenant_id)
    form_fields = ui_definition.fields_json if ui_definition else None
    
    chain_input = {
        "answer": '',
        "instance_id": process_instance_id,
        "instance_variables_data": process_instance.variables_data if process_instance else '',
        "role_bindings": workitem['assignees'],
        "current_activity_ids": activity_id,
        "current_user_ids": workitem['user_id'],
        "processDefinitionJson": process_definition_json,
        "process_definition_id": process_definition_id,
        "activity_id": activity_id,
        "user_info": user_info,
        "user_email": workitem['user_id'],
        "today": today,
        "organizationChart": organization_chart,
        "instance_name_pattern": process_definition_json.get("instanceNamePattern") or "",
        "form_fields": form_fields,
        "form_values": workitem['output']
    }
    
    collected_text = ""
    async for chunk in model.astream(prompt.format(**chain_input)):
        token = chunk.content
        collected_text += token
        upsert_workitem({
            "id": workitem['id'],
            "log": collected_text
        }, tenant_id)
    
    parsed_output = parser.parse(collected_text)
    result = execute_next_activity(parsed_output, tenant_id)
    result_json = json.loads(result)
    
    if result_json.get("instanceId") != "new" and workitem['proc_inst_id'] == "new":
        instance_id = result_json.get("instanceId")
        new_workitem = fetch_workitem_by_proc_inst_and_activity(instance_id, activity_id, tenant_id)
        new_workitem_dict = new_workitem.dict()
        if new_workitem_dict['id'] != workitem['id']:
            upsert_workitem({
                "id": workitem['id'],
                "proc_inst_id": instance_id,
                "status": "DONE",
                "end_date": new_workitem_dict['end_date'].isoformat() if new_workitem_dict['end_date'] else None,
                "due_date": new_workitem_dict['due_date'].isoformat() if new_workitem_dict['due_date'] else None
            }, tenant_id)
            delete_workitem(new_workitem_dict['id'], tenant_id)
        
    else:
        upsert_workitem({
            "id": workitem['id'],
            "status": "DONE",
        }, tenant_id)


async def safe_handle_workitem(workitem):
    try:
        print(f"[DEBUG] Starting safe_handle_workitem for workitem: {workitem['id']}")
        await handle_workitem(workitem)
    except Exception as e:
        print(f"[ERROR] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}")
        workitem['retry'] = workitem['retry'] + 1
        workitem['consumer'] = None
        if workitem['retry'] >= 3:
            workitem['status'] = "DONE"
            workitem['description'] = f"[Workitem Error] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}"
        upsert_workitem(workitem, workitem['tenant_id'])

async def polling_workitem():
    workitems = fetch_workitem_with_submitted_status()
    if not workitems:
        return

    tasks = []
    for workitem in workitems:
        task = asyncio.create_task(safe_handle_workitem(workitem))
        tasks.append(task)
    
    await asyncio.gather(*tasks, return_exceptions=True)

async def start_polling():
    setting_database()

    while True:
        try:
            await polling_workitem()
        except Exception as e:
            print(f"[Polling Loop Error] {e}")
        await asyncio.sleep(5)
