from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import Document
from langchain.output_parsers.json import SimpleJsonOutputParser
from pydantic import BaseModel
from typing import List, Optional, Any, Tuple
import json
import re
import uuid
import requests
import os
import asyncio
from dotenv import load_dotenv
from datetime import datetime
from fastapi import HTTPException
import threading
import queue
import time

from database import (
    fetch_process_definition, fetch_process_instance, fetch_ui_definition,
    fetch_ui_definition_by_activity_id, fetch_user_info, fetch_assignee_info, 
    get_vector_store, fetch_workitem_by_proc_inst_and_activity, upsert_process_instance, 
    upsert_completed_workitem, upsert_next_workitems, upsert_chat_message, 
    upsert_todo_workitems, upsert_workitem, delete_workitem, ProcessInstance,
    fetch_todolist_by_proc_inst_id
)
from process_definition import load_process_definition
from code_executor import execute_python_code
from smtp_handler import generate_email_template, send_email
from agent_processor import handle_workitem_with_agent
from mcp_processor import mcp_processor


if os.getenv("ENV") != "production":
    load_dotenv(override=True)

# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-4o", streaming=True, temperature=0)

# parser 생성
class CustomJsonOutputParser(SimpleJsonOutputParser):
    def parse(self, text: str) -> dict:
        # Multiple parsing strategies to handle various response formats
        
        # Strategy 1: Extract JSON from markdown code blocks
        json_patterns = [
            r'```json\n(.*?)\n```',  # Standard markdown JSON
            r'```\n(.*?)\n```',      # Generic code block
            r'```(.*?)```',           # Code block without newlines
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue
        
        # Strategy 2: Try to find JSON object directly in the text
        # Look for content that starts with { and ends with }
        json_start = text.find('{')
        json_end = text.rfind('}')
        
        if json_start != -1 and json_end != -1 and json_end > json_start:
            json_content = text[json_start:json_end + 1]
            try:
                return json.loads(json_content)
            except json.JSONDecodeError:
                pass
        
        # Strategy 3: Clean up common LLM artifacts and try again
        cleaned_text = text.strip()
        # Remove common prefixes
        prefixes_to_remove = [
            "Here is the JSON output based on the provided information and process definition:",
            "Here is the JSON response:",
            "The result is:",
            "JSON output:",
            "Response:",
        ]
        
        for prefix in prefixes_to_remove:
            if cleaned_text.startswith(prefix):
                cleaned_text = cleaned_text[len(prefix):].strip()
        
        # Try parsing the cleaned text
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            pass
        
        # Strategy 4: Try to extract and fix common JSON formatting issues
        # Remove any text before the first { and after the last }
        first_brace = cleaned_text.find('{')
        last_brace = cleaned_text.rfind('}')
        
        if first_brace != -1 and last_brace != -1:
            json_content = cleaned_text[first_brace:last_brace + 1]
            try:
                return json.loads(json_content)
            except json.JSONDecodeError as e:
                # Try to fix common issues
                fixed_content = self._fix_common_json_issues(json_content)
                try:
                    return json.loads(fixed_content)
                except json.JSONDecodeError:
                    pass
        
        raise ValueError(f"Could not parse JSON from text: {text[:200]}...")
    
    def _fix_common_json_issues(self, json_content: str) -> str:
        """Fix common JSON formatting issues from LLM responses"""
        # Remove trailing commas before closing brackets/braces
        json_content = re.sub(r',(\s*[}\]])', r'\1', json_content)
        
        # Fix unquoted property names
        json_content = re.sub(r'(\s*)(\w+)(\s*):', r'\1"\2"\3:', json_content)
        
        # Fix single quotes to double quotes
        json_content = json_content.replace("'", '"')
        
        # Fix boolean values
        json_content = re.sub(r':\s*true\s*([,}])', r': true\1', json_content)
        json_content = re.sub(r':\s*false\s*([,}])', r': false\1', json_content)
        
        # Fix missing quotes around string values
        json_content = re.sub(r':\s*([^"][^,}\]]*[^"\s,}\]])', r': "\1"', json_content)
        
        # Fix newlines and special characters in strings
        json_content = json_content.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        
        # Fix unescaped quotes within strings
        json_content = re.sub(r'([^\\])"([^"]*?)([^\\])"', r'\1"\2\\"\3"', json_content)
        
        return json_content

parser = CustomJsonOutputParser()

prompt = PromptTemplate.from_template(
"""
You are a BPMN Execution Agent.

Your task is to analyze the current process state and determine the next executable steps based on the process definition, activity outputs, and role bindings. You must return a valid JSON response as described below.

Process Definition:
- activities: {activities}
- gateways: {gateways}
- events: {events}
- sequences: {sequences}

Current Step:
- activity_id: {activity_id}
- user: {user_email}
- submitted_output: {output}

Runtime Context:
- next_activities: {next_activities}
- previous_outputs: {previous_outputs}
- today: {today}
- gateway_condition_data: {gateway_condition_data}
- instance_name_pattern: {instance_name_pattern} // If empty, fallback to key-value based logic from process variables (max 20 characters).

--- OPTIONAL USER FEEDBACK ---

User Feedback (Optional):
- message_from_user: "{user_feedback_message}"

If message_from_user is not empty:
- Carefully interpret the message to determine if any part of the result should be temporarily modified.
- Common changes include:
  - Wrong user assignment (e.g., 담당자 잘못 지정)
  - Incorrect or missing variables
  - Incorrect description wording
  - Request for different activity routing
- Use your best judgment to revise output accordingly.
- Changes should be applied **provisionally** and marked as feedback-applied.
- Indicate in the `description` (in Korean) that the result has been adjusted based on user feedback.
- Do not assume the user wants to override everything — only update what's explicitly or implicitly requested.

Instructions:

Step 1. Merge output variables
- Merge submitted_output and previous_outputs into a single key-value dictionary called merged_outputs.
- Use merged_outputs for all condition evaluation and variable extraction.
- Do not fabricate or infer values that are not present.

Step 2. Extract updated process variables (fieldMappings)
- Parse variables from submitted_output.
- Match value types to the declared types in the process definition (e.g., string, number, boolean).
- If no new values are found, return an empty list.

Step 3. Determine valid next activities
- For each item in next_activities, check the sequence condition from the current activity.
- If there is no condition, include the target activity.
- If a condition exists, evaluate it using merged_outputs.
  - Example: "stock_quantity >= order_quantity"
  - Only include the activity if the condition evaluates to true.
- Same inputs must always produce the same nextActivities. Do not randomly vary this.
- If no conditions are satisfied, return a PROCEED_CONDITION_NOT_MET error in cannotProceedErrors.
- Do not return multiple conflicting nextActivities for exclusive branches.

Step 4. Assign next user
- Use roleBindings.endpoint to assign nextUserEmail. If a list, pick the first item.
- If the target role is an external customer, use email from merged_outputs.
- If no valid email is found, return DATA_FIELD_NOT_EXIST error.

Step 5. Generate instanceName
- Use instance_name_pattern if provided.
- If empty, use a fallback such as "processDefinitionId.key", using a value from submitted_output.
- Ensure result is 20 characters or less.

Step 6. Compose process description
- In Korean, explain what activity was completed, what decisions were made, and what happens next.
- If useful data is available, include a list of reference info at the end in the format:
  - 주문 상품: 삼성 노트북
  - 재고 수량: 10
- Omit the list entirely if no meaningful information is available.

Output format (must be wrapped in ```json and ``` markers):
{{
  "instanceId": "{instance_id}",
  "instanceName": "process instance name",
  "processDefinitionId": "{process_definition_id}",
  "fieldMappings": [
    {{
      "key": "process_variable_key",
      "name": "process_variable_name",
      "value": <value_matching_type>
    }}
  ],
  "roleBindings": {role_bindings},
  "completedActivities": [
    {{
      "completedActivityId": "activity_id",
      "completedActivityName": "activity_name",
      "completedUserEmail": "user_email",
      "result": "DONE",
      "description": "완료된 활동에 대한 설명 (Korean)"
    }}
  ],
  "nextActivities": [
    {{
      "nextActivityId": "activity_id",
      "nextActivityName": "activity_name",
      "nextUserEmail": "email_or_agent_id", 
      "result": "IN_PROGRESS",
      "description": "다음 활동에 대한 설명 (Korean)"
    }}
  ],
  "cannotProceedErrors": [
    {{
      "type": "PROCEED_CONDITION_NOT_MET" | "SYSTEM_ERROR" | "DATA_FIELD_NOT_EXIST",
      "reason": "설명 (Korean)"
    }}
  ],
  "referenceInfo": [
    {{
      "key": "이전 산출물에서 참조한 키 (in Korean)",
      "value": "이전 산출물에서 참조한 값 (in Korean)"
    }}
  ]
}}
"""
)

# Pydantic model for process execution
class Activity(BaseModel):
    nextActivityId: Optional[str] = None
    nextActivityName: Optional[str] = None
    nextUserEmail: Optional[str] = None
    result: Optional[str] = None
    description: Optional[str] = None

class CompletedActivity(BaseModel):
    completedActivityId: Optional[str] = None
    completedActivityName: Optional[str] = None
    completedUserEmail: Optional[str] = None
    result: Optional[str] = None
    description: Optional[str] = None

class ReferenceInfo(BaseModel):
    key: Optional[str] = None
    value: Optional[str] = None

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
    nextActivities: Optional[List[Activity]] = None
    completedActivities: Optional[List[CompletedActivity]] = None
    processDefinitionId: str
    result: Optional[str] = None
    cannotProceedErrors: Optional[List[ProceedError]] = None
    referenceInfo: Optional[List[ReferenceInfo]] = None
    
# upsert 디바운스 큐 및 쓰레드 정의 (파일 상단에 위치)
upsert_queue = queue.Queue()

def upsert_worker():
    last_upsert_time = 0
    last_item = None
    DEBOUNCE_SEC = 1  # 0.5초에 한 번만 upsert
    while True:
        try:
            item, tenant_id = upsert_queue.get(timeout=DEBOUNCE_SEC)
            last_item = (item, tenant_id)
            upsert_queue.task_done()
        except queue.Empty:
            pass  # 큐가 비어있으면 넘어감
        now = time.time()
        if last_item and (now - last_upsert_time) >= DEBOUNCE_SEC:
            upsert_workitem(last_item[0], last_item[1])
            last_upsert_time = now
            last_item = None

# 프로그램 시작 시 한 번만 실행
threading.Thread(target=upsert_worker, daemon=True).start()

def initialize_role_bindings(process_result_json: dict) -> list:
    """Initialize role_bindings from process_result_json"""
    existing_role_bindings = process_result_json.get("roleBindings", [])
    initial_role_bindings = []
    if existing_role_bindings:
        for rb in existing_role_bindings:
            role_binding = {
                "name": rb.get("name"),
                "endpoint": rb.get("endpoint"),
                "resolutionRule": rb.get("resolutionRule")
            }
            initial_role_bindings.append(role_binding)
    return initial_role_bindings

def check_external_customer_and_send_email(activity_obj, process_instance, process_definition):
    """
    Check that the next activity's role is assigned to external customer.
    If the next activity's role is assigned to external customer, send an email to the external customer.
    """
    try:
        # Determine if the role is for an external customer
        role_name = activity_obj.role
        role_info = next((role for role in process_definition.roles if role.name == role_name), None)
        
        if role_info and role_info.endpoint == "external_customer":
            customer_email = None
            workitems = fetch_todolist_by_proc_inst_id(process_instance.proc_inst_id)
            completed_workitems = [workitem for workitem in workitems if workitem.status == "DONE"]
            completed_outputs = [workitem.output for workitem in completed_workitems]
            for output in completed_outputs:
                if output:
                    try:
                        output_json = json.loads(output) if isinstance(output, str) else output
                        # output_json이 딕셔너리인지 확인
                        if isinstance(output_json, dict):
                            # 각 폼 필드에서 customer_email 찾기
                            for form_key, form_data in output_json.items():
                                if isinstance(form_data, dict) and "customer_email" in form_data:
                                    customer_email = form_data["customer_email"]
                                    break
                            # customer_email을 찾았으면 루프 종료
                            if customer_email:
                                break
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"[WARNING] Failed to parse output JSON: {e}")
                        continue
            
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
                
                # 이메일 템플릿 생성
                email_template = generate_email_template(activity_obj, external_form_url, additional_info)
                title = f"'{activity_obj.name}' 를 진행해주세요."
                print(f"Sending email to {customer_email} with title {title}")
                # 이메일 전송
                send_email(subject=title, body=email_template, to_email=customer_email)
                
                return True
            else:
                print(f"No customer email found for {process_instance.proc_inst_id}")
                return False
    except Exception as e:
        # Log the error but don't stop the process
        print(f"Failed to send notification to external customer: {str(e)}")
        return False

def _create_or_get_process_instance(process_result: ProcessResult, process_result_json: dict, tenant_id: Optional[str] = None) -> ProcessInstance:
    """Create new process instance or get existing one"""
    if not fetch_process_instance(process_result.instanceId, tenant_id):
        if process_result.instanceId == "new" or '.' not in process_result.instanceId:
            instance_id = f"{process_result.processDefinitionId.lower()}.{str(uuid.uuid4())}"
        else:
            instance_id = process_result.instanceId
        return ProcessInstance(
            proc_inst_id=instance_id,
            proc_inst_name=f"{process_result.instanceName}",
            role_bindings=initialize_role_bindings(process_result_json),
            current_activity_ids=[],
            participants=[],
            variables_data=[],
            status="RUNNING",
            tenant_id=tenant_id
        )
    else:
        process_instance = fetch_process_instance(process_result.instanceId, tenant_id)
        if process_instance.status == "NEW":
            process_instance.proc_inst_name = process_result.instanceName
        return process_instance

def _update_process_variables(process_instance: ProcessInstance, field_mappings: List[FieldMapping]):
    """Update process instance variables from field mappings"""
    if not field_mappings:
        return
    
    # Ensure variables_data is initialized
    if process_instance.variables_data is None:
        process_instance.variables_data = []
    
    for data_change in field_mappings:
        form_entry = next((item for item in process_instance.variables_data 
                          if isinstance(item["value"], dict) and data_change.key in item["value"]), None)
        
        if form_entry:
            form_entry["value"][data_change.key] = data_change.value
        else:
            variable = {
                "key": data_change.key,
                "name": data_change.name,
                "value": data_change.value
            }
            existing_variable = next((item for item in process_instance.variables_data 
                                    if item["key"] == data_change.key), None)
            if existing_variable:
                existing_variable.update(variable)
            else:
                process_instance.variables_data.append(variable)

def _process_next_activities(process_instance: ProcessInstance, process_result: ProcessResult, 
                           process_result_json: dict, process_definition):
    """Process next activities"""
    # Ensure current_activity_ids is initialized
    if process_instance.current_activity_ids is None:
        process_instance.current_activity_ids = []
    
    for activity in process_result.nextActivities:
        if activity.nextActivityId in ["endEvent", "END_PROCESS", "end_event"]:
            process_instance.current_activity_ids = []
            break
            
        if process_definition.find_gateway_by_id(activity.nextActivityId):
            next_activities = process_definition.find_next_activities(activity.nextActivityId, False)
            if next_activities:
                process_instance.current_activity_ids = [act.id for act in next_activities]
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
                process_instance.current_activity_ids = []
                process_result_json["nextActivities"] = []
                break
                
        elif activity.result == "IN_PROGRESS" and activity.nextActivityId not in process_instance.current_activity_ids:
            process_instance.current_activity_ids = [activity.nextActivityId]
        else:
            process_instance.current_activity_ids.append(activity.nextActivityId)
        
        # Check external customer and send email
        activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
        check_external_customer_and_send_email(activity_obj, process_instance, process_definition)

def _execute_script_tasks(process_instance: ProcessInstance, process_result: ProcessResult, 
                         process_result_json: dict, process_definition):
    """Execute script tasks in next activities"""
    for activity in process_result.nextActivities:
        activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
        if activity_obj and activity_obj.type == "scriptTask":
            env_vars = {}
            # Ensure variables_data is not None
            if process_instance.variables_data:
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
                # Script task execution error
                process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id, False)]
                process_result_json["result"] = result.stderr
            else:
                process_result_json["result"] = result.stdout
                # Script task execution success
                process_instance.current_activity_ids = [
                    act_id for act_id in process_instance.current_activity_ids
                    if act_id != activity_obj.id
                ]
                    
                process_result_json["nextActivities"] = [
                    Activity(**act) for act in process_result_json.get("nextActivities", [])
                    if act.get("nextActivityId") != activity_obj.id
                ]
                completed_activity = CompletedActivity(
                    completedActivityId=activity_obj.id,
                    completedUserEmail=activity.nextUserEmail,
                    result="DONE"
                )
                completed_activity_dict = completed_activity.model_dump()
                process_result_json["completedActivities"].append(completed_activity_dict)
        else:
            result = f"Next activity {activity.nextActivityId} is not a ScriptActivity or not found."
            process_result_json["result"] = result

def _persist_process_data(process_instance: ProcessInstance, process_result: ProcessResult, 
                         process_result_json: dict, process_definition, tenant_id: Optional[str] = None):
    """Persist process data to database and vector store"""
    # Upsert workitems
    upsert_todo_workitems(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    completed_workitems = upsert_completed_workitem(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    next_workitems = upsert_next_workitems(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    
    # Upsert process instance
    if process_instance.status == "NEW":
        process_instance.proc_inst_name = process_result.instanceName
    _, process_instance = upsert_process_instance(process_instance, tenant_id)
    
    if completed_workitems:
        for completed_workitem in completed_workitems:
            user_info = fetch_assignee_info(completed_workitem.user_id)
            ui_definition = fetch_ui_definition_by_activity_id(completed_workitem.proc_def_id, completed_workitem.activity_id, tenant_id)
            form_html = ui_definition.html if ui_definition else None
            form_id = ui_definition.id if ui_definition else None
            if completed_workitem.output:
                output = completed_workitem.output.get(form_id)
            else:
                output = {}
            message_data = {
                "role": "system" if user_info.get("name") == "external_customer" else "user",
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "profile": user_info.get("info", {}).get("profile", ""),
                "content": "",
                "jsonContent": output if output else {},
                "htmlContent": form_html if form_html else "",
                "contentType": "html" if form_html else "text"
            }
            upsert_chat_message(completed_workitem.proc_inst_id, message_data, tenant_id)

    if process_result.cannotProceedErrors:
        reason = "\n".join(error.reason for error in process_result.cannotProceedErrors)
        message_json = json.dumps({"role": "system", "content": reason})
        upsert_chat_message(process_instance.proc_inst_id, message_json, tenant_id)
    else:
        description = {
            "referenceInfo": process_result_json.get("referenceInfo", []),
            "completedActivities": process_result_json.get("completedActivities", []),
            "nextActivities": process_result_json.get("nextActivities", [])
        }
        message_json = json.dumps({
            "role": "system",
            "contentType": "json",
            "jsonContent": description
        })
        upsert_chat_message(process_instance.proc_inst_id, message_json, tenant_id)
    
    # Update process_result_json
    process_result_json["instanceId"] = process_instance.proc_inst_id
    process_result_json["instanceName"] = process_instance.proc_inst_name
    process_result_json["workitemIds"] = [workitem.id for workitem in next_workitems] if next_workitems else []
    
    # Add to vector store
    content_str = json.dumps(process_instance.dict(exclude={'process_definition'}), ensure_ascii=False, indent=2)
    metadata = {
        "tenant_id": process_instance.tenant_id,
        "type": "process_instance"
    }
    vector_store = get_vector_store()
    vector_store.add_documents([Document(page_content=content_str, metadata=metadata)])

def _check_service_tasks(process_instance: ProcessInstance, process_result_json: dict, process_definition):
    try:
        for activity in process_result_json.get("nextActivities", []):
            activity_obj = process_definition.find_activity_by_id(activity.get("nextActivityId"))
            if activity_obj and activity_obj.type == "serviceTask":
                next_workitem = fetch_workitem_by_proc_inst_and_activity(process_instance.proc_inst_id, activity_obj.id, process_instance.tenant_id)
                if next_workitem:
                    upsert_workitem({
                        "id": next_workitem.id,
                        "status": "SUBMITTED",
                    }, process_instance.tenant_id)
    except Exception as e:
        print(f"[ERROR] Failed to check service tasks: {str(e)}")
        raise e
    
def execute_next_activity(process_result_json: dict, tenant_id: Optional[str] = None) -> str:
    try:
        process_result = ProcessResult(**process_result_json)
        
        # Create or get process instance
        process_instance = _create_or_get_process_instance(process_result, process_result_json, tenant_id)
        process_definition = process_instance.process_definition
        
        # Update process variables
        _update_process_variables(process_instance, process_result.fieldMappings)
        
        # Process next activities
        _process_next_activities(process_instance, process_result, process_result_json, process_definition)
        
        # Execute script tasks
        _execute_script_tasks(process_instance, process_result, process_result_json, process_definition)
        
        # Persist data
        _persist_process_data(process_instance, process_result, process_result_json, process_definition, tenant_id)
        
        # Check service tasks
        _check_service_tasks(process_instance, process_result_json, process_definition)
        
        return json.dumps(process_result_json)
    except Exception as e:
        message_json = json.dumps({"role": "system", "content": str(e)})
        upsert_chat_message(process_instance.proc_inst_id, message_json, tenant_id)
        raise HTTPException(status_code=500, detail=str(e)) from e

MEMENTO_SERVICE_URL = os.getenv("MEMENTO_SERVICE_URL", "http://memento-service:8005")

def process_output(workitem, tenant_id):
    try:
        if workitem["output"] is None or workitem["output"] == {}:
            return
        url = f"{MEMENTO_SERVICE_URL}/process/database"
        response = requests.post(url, json={
            "storage_type": "database",
            "options": {
                "proc_inst_id": workitem["proc_inst_id"],
                "activity_id": workitem["activity_id"],
                "tenant_id": tenant_id
            }
        })
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



def get_workitem_position(workitem: dict) -> Tuple[bool, bool]:
    """
    워크아이템이 프로세스 정의에서 첫 번째 또는 마지막 워크아이템인지 판별
    startEvent와 연결된 액티비티가 첫 번째, endEvent와 연결된 액티비티가 마지막
    
    Returns:
        Tuple[bool, bool]: (is_first, is_last)
    """
    proc_inst_id = workitem.get('proc_inst_id')
    proc_def_id = workitem.get('proc_def_id')
    activity_id = workitem.get('activity_id')
    tenant_id = workitem.get('tenant_id')
    
    if not proc_inst_id or proc_inst_id == "new" or not proc_def_id or not activity_id:
        return False, False
    
    try:
        # 프로세스 정의 조회
        process_definition_json = fetch_process_definition(proc_def_id, tenant_id)
        process_definition = load_process_definition(process_definition_json)
        
        # 첫 번째 액티비티 확인 (startEvent와 연결된 액티비티)
        is_first = process_definition.is_starting_activity(activity_id)
        
        # 마지막 액티비티 확인 (endEvent와 연결된 액티비티)
        end_activity = process_definition.find_end_activity()
        is_last = end_activity and end_activity.id == activity_id
        
        return is_first, is_last
        
    except Exception as e:
        print(f"[ERROR] Failed to determine workitem position for {workitem.get('id')}: {str(e)}")
        return False, False

def update_instance_status_on_error(workitem: dict, is_first: bool, is_last: bool):
    """
    예외 발생 시 인스턴스 상태를 업데이트
    """
    proc_inst_id = workitem.get('proc_inst_id')
    if not proc_inst_id or proc_inst_id == "new":
        return
    
    try:
        if is_first:
            process_instance = fetch_process_instance(proc_inst_id, workitem.get('tenant_id'))
            if process_instance:
                process_instance.status = "RUNNING"
                upsert_process_instance(process_instance, workitem.get('tenant_id'))
                print(f"[INFO] Updated instance {proc_inst_id} status to RUNNING due to first workitem failure")
        
        elif is_last:
            process_instance = fetch_process_instance(proc_inst_id, workitem.get('tenant_id'))
            if process_instance:
                process_instance.status = "COMPLETED"
                upsert_process_instance(process_instance, workitem.get('tenant_id'))
                print(f"[INFO] Updated instance {proc_inst_id} status to COMPLETED due to last workitem failure")
                
    except Exception as e:
        print(f"[ERROR] Failed to update instance status for {proc_inst_id}: {str(e)}")

def get_field_value(field_info: str, process_definition: Any, process_instance_id: str, tenant_id: str):
    """
    산출물에서 특정 필드의 값을 추출
    """
    try:
        field_value = {}
        process_definition_id = process_definition.processDefinitionId
        split_field_info = field_info.split('.')
        form_id = split_field_info[0]
        field_id = split_field_info[1]
        activity_id = form_id.replace("_form", "").replace(f"{process_definition_id}_", "")
        
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_id, activity_id, tenant_id)
        if workitem:
            field_value[form_id] = {}
            output = workitem.output
            if output:
                if output.get(form_id) and output.get(form_id).get(field_id):
                    field_value[form_id][field_id] = output.get(form_id).get(field_id)
                else:
                    return None
            else:
                return None

        return field_value
    except Exception as e:
        print(f"[ERROR] Failed to get output field value for {field_info}: {str(e)}")
        return None

def group_fields_by_form(field_values: dict) -> dict:
    """
    필드 값들을 폼별로 그룹화하는 공통 함수
    
    Args:
        field_values: {'form_id.field_name': {'form_id': {'field_name': value}}, ...} 형태의 딕셔너리
    
    Returns:
        {'form_id': {'field_name': value, ...}, ...} 형태의 그룹화된 딕셔너리
    """
    form_groups = {}
    
    for field_key, field_value in field_values.items():
        if not field_value:
            continue
            
        form_id = field_key.split('.')[0]
        if form_id not in form_groups:
            form_groups[form_id] = {}
        
        field_id = field_key.split('.')[1] if '.' in field_key else field_key
        
        if isinstance(field_value, dict) and form_id in field_value:
            actual_value = field_value[form_id].get(field_id)
            if actual_value is not None:
                form_groups[form_id][field_id] = actual_value
    
    return {form_id: fields for form_id, fields in form_groups.items() if fields}

def get_input_data(workitem: dict, process_definition: Any):
    """
    워크아이템 실행에 필요한 입력 데이터 추출
    """
    try:
        activity_id = workitem.get('activity_id')
        activity = process_definition.find_activity_by_id(activity_id)

        if not activity:
            return None
        
        input_data = {}
        input_fields = activity.inputData
        if len(input_fields) != 0:
            # 각 필드의 값을 가져오기
            field_values = {}
            for input_field in input_fields:
                field_value = get_field_value(input_field, process_definition, workitem.get('proc_inst_id'), workitem.get('tenant_id'))
                if field_value:
                    field_values[input_field] = field_value
            
            # 폼별로 그룹화
            grouped_data = group_fields_by_form(field_values)
            input_data.update(grouped_data)

        return input_data

    except Exception as e:
        print(f"[ERROR] Failed to get selected info for {workitem.get('id')}: {str(e)}")
        return None

def get_gateway_condition_data(workitem: dict, process_definition: Any, gateway_id: str):
    """
    워크아이템 실행에 필요한 게이트웨이 조건 데이터 추출
    """
    try:
        gateway = process_definition.find_gateway_by_id(gateway_id)
        if not gateway:
            return None
        
        condition_data = {}
        if gateway.conditionData:
            process_instance_id = workitem.get('proc_inst_id')
            # 각 필드의 값을 가져오기
            field_values = {}
            for condition_field in gateway.conditionData:
                field_value = get_field_value(condition_field, process_definition, process_instance_id, workitem.get('tenant_id'))
                if field_value:
                    field_values[condition_field] = field_value
            
            # 폼별로 그룹화
            grouped_data = group_fields_by_form(field_values)
            condition_data.update(grouped_data)

        return condition_data
    except Exception as e:
        print(f"[ERROR] Failed to get gateway condition data for {workitem.get('id')}: {str(e)}")
        return None

async def handle_workitem(workitem):
    # 워크아이템 위치 판별
    is_first, is_last = get_workitem_position(workitem)

    if workitem['retry'] >= 3:
        update_instance_status_on_error(workitem, is_first, is_last)
        return

    activity_id = workitem['activity_id']
    process_definition_id = workitem['proc_def_id']
    process_instance_id = workitem['proc_inst_id']
    tenant_id = workitem['tenant_id']

    process_definition_json = fetch_process_definition(process_definition_id, tenant_id)
    process_definition = load_process_definition(process_definition_json)
    
    if workitem['user_id'] != "external_customer":
        if workitem['user_id'] and ',' in workitem['user_id']:
            user_ids = workitem['user_id'].split(',')
            user_info = []
            for user_id in user_ids:
                assignee_info = fetch_assignee_info(user_id)
                user_info.append({
                    "name": assignee_info.get("name", user_id),
                    "email": assignee_info.get("email", user_id),
                    "type": assignee_info.get("type", "unknown"),
                    "info": assignee_info.get("info", {})
                })
        else:
            assignee_info = fetch_assignee_info(workitem['user_id'])
            user_info = {
                "name": assignee_info.get("name", workitem['user_id']),
                "email": assignee_info.get("email", workitem['user_id']),
                "type": assignee_info.get("type", "unknown"),
                "info": assignee_info.get("info", {})
            }
    else:
        user_info = {
            "name": "외부 고객",
            "type": "external_customer",
            "email": workitem['user_id'],
            "info": {}
        }

    today = datetime.now().strftime("%Y-%m-%d")
    ui_definition = fetch_ui_definition_by_activity_id(process_definition_id, activity_id, tenant_id)
    output = {}
    if workitem['output'] and isinstance(workitem['output'], str):
        output = json.loads(workitem['output'])
    else:
        output = workitem['output']
    form_id = ui_definition.id if ui_definition else None
    if form_id and output.get(form_id):
        output = output.get(form_id)
        
    try:
        next_activities = []
        gateway_condition_data = None
        if process_definition:
            next_activities = [activity.id for activity in process_definition.find_next_activities(activity_id, True)]
            for act_id in next_activities:
                if process_definition.find_gateway_by_id(act_id):
                    try:
                        gateway_condition_data = get_gateway_condition_data(workitem, process_definition, act_id)
                    except Exception as e:
                        print(f"[ERROR] Failed to get gateway condition data for {workitem.get('id')}: {str(e)}")
                        gateway_condition_data = None

        workitem_input_data = None
        try:
            workitem_input_data = get_input_data(workitem, process_definition)
        except Exception as e:
            print(f"[ERROR] Failed to get selected info for {workitem.get('id')}: {str(e)}")
    
        chain_input = {
            "activities": process_definition.activities,
            "gateways": process_definition_json.get('gateways', []),
            "events": process_definition_json.get('events', []),
            "sequences": process_definition.sequences,
            "instance_id": process_instance_id,
            "instance_name_pattern": process_definition_json.get("instanceNamePattern") or "",
            "process_definition_id": process_definition_id,
            "activity_id": activity_id,
            "user_email": workitem['user_id'] if not workitem['user_id'] or ',' not in workitem['user_id'] else ','.join(workitem['user_id'].split(',')),
            "output": output,
            "today": today,
            "role_bindings": workitem.get('assignees', []),
            "next_activities": next_activities,
            "previous_outputs": workitem_input_data,
            "user_feedback_message": workitem.get('temp_feedback', ''),
            "gateway_condition_data": gateway_condition_data
        }
        
        collected_text = ""
        num_of_chunk = 0
        async for chunk in model.astream(prompt.format(**chain_input)):
            token = chunk.content
            collected_text += token
            upsert_queue.put((
                {
                    "id": workitem['id'],
                    "log": collected_text
                },
                tenant_id
            ))
            num_of_chunk += 1
            if num_of_chunk % 10 == 0:
                upsert_workitem({"id": workitem['id'], "log": collected_text}, tenant_id)

        # Enhanced JSON parsing with retry mechanism
        parsed_output = None
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                parsed_output = parser.parse(collected_text)
                break
            except Exception as parse_error:
                retry_count += 1
                print(f"[WARNING] JSON parsing attempt {retry_count} failed for workitem {workitem['id']}: {str(parse_error)}")
                
                if retry_count >= max_retries:
                    # Log the problematic response for debugging
                    print(f"[ERROR] All JSON parsing attempts failed. Raw response: {collected_text[:500]}...")
                    
                    # Update workitem with error status
                    upsert_workitem({
                        "id": workitem['id'],
                        "status": "ERROR",
                        "log": f"JSON parsing failed after {max_retries} attempts: {str(parse_error)}"
                    }, tenant_id)
                    
                    # Send error message to chat
                    error_message = json.dumps({
                        "role": "system", 
                        "content": f"JSON 파싱 오류가 발생했습니다: {str(parse_error)}"
                    })
                    upsert_chat_message(process_instance_id, error_message, tenant_id)
                    
                    raise parse_error
                
                # Wait a bit before retrying
                await asyncio.sleep(0.5)
        
        if parsed_output is None:
            raise Exception("Failed to parse JSON response after all retry attempts")
        
        result = execute_next_activity(parsed_output, tenant_id)
        result_json = json.loads(result)
        
    except Exception as e:
        print(f"[ERROR] Error in handle_workitem for workitem {workitem['id']}: {str(e)}")
        raise e

    if result_json:
        if result_json.get("cannotProceedErrors"):
            upsert_workitem({
                "id": workitem['id'],
                "status": "IN_PROGRESS",
            }, tenant_id)
            return
        else:
            upsert_workitem({
                "id": workitem['id'],
                "status": "DONE",
            }, tenant_id)
        
        try:
            print(f"[DEBUG] process_output for workitem {workitem['id']}")
            process_output(workitem, tenant_id)
        except Exception as e:
            print(f"[ERROR] Error in process_output for workitem {workitem['id']}: {str(e)}")

async def handle_agent_workitem(workitem):
    """
    에이전트 업무를 처리하는 함수
    agent_processor의 handle_workitem_with_agent를 사용합니다.
    """
    # 워크아이템 위치 판별
    is_first, is_last = get_workitem_position(workitem)

    if workitem['retry'] >= 3:
        # 예외 발생 시 인스턴스 상태 업데이트
        update_instance_status_on_error(workitem, is_first, is_last)
        return
    
    try:
        print(f"[DEBUG] Starting agent workitem processing for: {workitem['id']}")
        
        # 에이전트 정보 가져오기
        if workitem['user_id'] and ',' in workitem['user_id']:
            agent_ids = workitem['user_id'].split(',')
            agent_info = []
            for agent_id in agent_ids:
                agent_info.append(fetch_user_info(agent_id))
        else:
            agent_id = workitem['user_id']
            agent_info = [fetch_user_info(agent_id)] if agent_id else []
        
        if not agent_info:
            print(f"[ERROR] Agent not found: {agent_id}")
            upsert_workitem({
                "id": workitem['id'],
                "status": "DONE",
                "description": f"Agent not found: {agent_id}"
            }, workitem['tenant_id'])
            return
        
        # 프로세스 정의와 액티비티 정보 가져오기
        process_definition_json = fetch_process_definition(workitem['proc_def_id'], workitem['tenant_id'])
        process_definition = load_process_definition(process_definition_json)
        activity = process_definition.find_activity_by_id(workitem['activity_id'])
        
        if not activity:
            print(f"[ERROR] Activity not found: {workitem['activity_id']}")
            return
        
        # handle_workitem_with_agent 호출
        result = await handle_workitem_with_agent(workitem, activity, agent_info)
        
        if result is not None:
            print(f"[DEBUG] Agent workitem completed successfully: {workitem['id']}")
        else:
            print(f"[ERROR] Agent workitem failed: {workitem['id']}")
            upsert_workitem({
                "id": workitem['id'],
                "log": "Agent processing failed"
            }, workitem['tenant_id'])
        
    except Exception as e:
        print(f"[ERROR] Error in handle_agent_workitem for workitem {workitem['id']}: {str(e)}")
        raise e 


async def handle_service_workitem(workitem):
    """
    서비스 업무를 처리하는 함수
    """
    # 워크아이템 위치 판별
    is_first, is_last = get_workitem_position(workitem)

    if workitem['retry'] >= 3:
        # 예외 발생 시 인스턴스 상태 업데이트
        update_instance_status_on_error(workitem, is_first, is_last)
        return

    def extract_tool_results_from_agent_messages(messages):
        """
        LangChain agent의 메시지 리스트에서 도구 실행 결과만 추출하여
        {tool_name: {status, ...}} 형태의 딕셔너리로 반환
        """
        tool_results = {}
        for msg in messages:
            # ToolMessage: content가 JSON 문자열일 수 있음
            if hasattr(msg, "name") and hasattr(msg, "content"):
                try:
                    content = msg.content
                    if content and (content.startswith("{") or content.startswith("[")):
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "status" in parsed:
                            tool_results[msg.name] = parsed
                        elif isinstance(parsed, list):
                            for item in parsed:
                                if isinstance(item, dict) and "status" in item:
                                    tool_results[msg.name] = item
                except Exception:
                    continue
            # AIMessage: additional_kwargs에 tool_calls가 있을 수 있음
            elif hasattr(msg, "additional_kwargs"):
                tool_calls = msg.additional_kwargs.get("tool_calls", [])
                for call in tool_calls:
                    tool_name = call.get("function", {}).get("name")
                    arguments = call.get("function", {}).get("arguments")
                    if tool_name and arguments:
                        try:
                            args = json.loads(arguments)
                            tool_results[tool_name] = args
                        except Exception:
                            tool_results[tool_name] = arguments
        return tool_results

    try:
        print(f"[DEBUG] Starting service workitem processing for: {workitem['id']}")
        
        agent_id = workitem['user_id']
        tenant_id = workitem['tenant_id']
        agent_info = None
        if not agent_id:
            print(f"[ERROR] No agent ID found in workitem: {workitem['id']}")
            upsert_workitem({
                "id": workitem['id'],
                "log": "No agent ID found"
            }, tenant_id)
            return
        
        if agent_id and ',' in agent_id:
            agent_ids = workitem['user_id'].split(',')
            for agent_id in agent_ids:
                assignee_info = fetch_assignee_info(agent_id)
                if assignee_info and assignee_info.get("type") == "agent":
                    agent_info = fetch_user_info(agent_id)
                    break
        else:
            assignee_info = fetch_assignee_info(agent_id)
            if assignee_info and assignee_info.get("type") == "agent":
                agent_info = fetch_user_info(agent_id)

        if not agent_info:
            print(f"[ERROR] Agent not found: {agent_id}")
            upsert_workitem({
                "id": workitem['id'],
                "log": f"Agent not found: {agent_id}"
            }, tenant_id)
            return

        results = await mcp_processor.execute_mcp_tools(workitem, agent_info, tenant_id)
        messages = results.get("messages", [])
        
        if messages:
            tool_results = extract_tool_results_from_agent_messages(messages)
        else:
            tool_results = {}

        if not tool_results:
            print(f"[ERROR] MCP tools execution failed: No tool results found")
            upsert_workitem({
                "id": workitem['id'],
                "log": "MCP tools execution failed: No tool results found"
            }, tenant_id)
            # return

        error_count = 0
        success_count = 0
        result_summary = []
        
        for tool_name, result in tool_results.items():
            if isinstance(result, dict) and result.get("status") == "success":
                success_count += 1
                connection_type = result.get("connection_type", "unknown")
                result_summary.append(f"{tool_name} ({connection_type}): 성공")
            else:
                error_count += 1
                connection_type = result.get("connection_type", "unknown") if isinstance(result, dict) else "unknown"
                error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else str(result)
                result_summary.append(f"{tool_name} ({connection_type}): 실패 - {error_msg}")
        
        if error_count == 0:
            log_message = f"모든 MCP 도구 실행 완료: {', '.join(result_summary)}"
        elif success_count > 0:
            log_message = f"일부 MCP 도구 실행 완료: {', '.join(result_summary)}"
        else:
            log_message = f"모든 MCP 도구 실행 실패: {', '.join(result_summary)}"
        
        upsert_workitem({
            "id": workitem['id'],
            "status": "DONE",
            "log": log_message,
            "output": tool_results
        }, tenant_id)
        
        # 채팅 메시지 추가
        def summarize_agent_messages(messages):
            lines = []
            for msg in messages:
                role = getattr(msg, 'role', None) or getattr(msg, 'name', None) or msg.__class__.__name__
                content = getattr(msg, 'content', None)
                if content:
                    lines.append(f"[{role}] {content}")
            return '\n'.join(lines)

        summarized_messages = summarize_agent_messages(messages)
        # 채팅 메시지 추가
        def get_last_ai_message_content(messages):
            last_content = ""
            for msg in reversed(messages):
                if msg.__class__.__name__ == "AIMessage" and hasattr(msg, "content"):
                    last_content = msg.content
                    break
            return last_content

        last_ai_content = get_last_ai_message_content(messages)
        message_data = {
            "role": "system",
            "content": last_ai_content,
            "jsonContent": tool_results
        }
        upsert_chat_message(workitem['proc_inst_id'], message_data, tenant_id)
        
        # 리소스 정리
        await mcp_processor.cleanup()
                
    except Exception as e:
        print(f"[ERROR] Error in handle_service_workitem for workitem {workitem['id']}: {str(e)}")
        
        # 에러 상태로 워크아이템 업데이트
        upsert_workitem({
            "id": workitem['id'],
            "log": f"Service workitem processing failed: {str(e)}"
        }, workitem['tenant_id'])
        
        # 에러 메시지를 채팅에 추가
        error_message = json.dumps({
            "role": "system",
            "content": f"서비스 업무 처리 중 오류가 발생했습니다: {str(e)}"
        })
        upsert_chat_message(workitem['proc_inst_id'], error_message, workitem['tenant_id'])
        
        # 리소스 정리
        try:
            await mcp_processor.cleanup()
        except:
            pass
        
        raise e