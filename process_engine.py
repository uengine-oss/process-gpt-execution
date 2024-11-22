from fastapi import HTTPException
from langchain.prompts import PromptTemplate
from langchain_community.chat_models import ChatOpenAI
from langserve import add_routes
from langchain.output_parsers.json import SimpleJsonOutputParser  # JsonOutputParser 임포트
from pydantic import BaseModel
from typing import List, Optional, Any
from code_executor import execute_python_code
from langchain_core.runnables import RunnableLambda
from datetime import datetime


from database import upsert_process_instance, upsert_completed_workitem, upsert_next_workitems, parse_token, upsert_chat_message, fetch_ui_definition_by_activity_id, fetch_chat_history, upsert_todo_workitems, fetch_user_info
from database import ProcessInstance
import uuid
import json

# 1. OpenAI Chat Model 생성
# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-4o")
vision_model = ChatOpenAI(model="gpt-4-vision-preview", max_tokens = 4096)

# ConfigurableField를 사용하여 모델 선택 구성

# parser = SimpleJsonOutputParser()
import re
class CustomJsonOutputParser(SimpleJsonOutputParser):
    def parse(self, text: str) -> dict:
        # Remove comments
        text = re.sub(r'//.*?\n|/\*.*?\*/', '', text, flags=re.S)
        
        # Extract JSON from markdown if present
        match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if match:
            text = match.group(1)
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")
# Replace the existing parser with our custom parser
parser = CustomJsonOutputParser()


from process_definition import load_process_definition
from database import fetch_process_definition
from database import fetch_process_instance
from database import fetch_organization_chart

# process_instance = fetch_process_instance(1)
# processDefinitionJson = fetch_process_definition(process_instance.def_id)



# process_definition = load_process_definition(processDefinitionJson)


prompt = PromptTemplate.from_template(
    """
    Now, you're going to create an interactive system similar to a BPM system that helps our company's employees understand various processes and take the next steps when they start a process or are curious about the next steps.

    - Process Definition: {processDefinitionJson}

    - Process Instance Id: {instance_id}
    
    - Process Data:
    {data}
    
    - Organization Chart:
    {organizationChart}
    
    - User Information:
    {user_info}
    
    - Role Bindings:
    {role_bindings}

    - Currently Running Activities: 
    {current_activity_ids}

    - Users Currently Running Activities:
    {current_user_ids}
    
    - Currently Running Activity's Form Definition:
    {form_definition}
    
    - Received Message From Current Step:
    
      activityId: "{activity_id}",  // the activityId is not included in the Currently Running Activities or is the next activityId than Current Running Activities, it must never be added to completedActivities to return the activityId as complete and must be reported in cannotProceedErrors.
      user: "{user_email}",
      submitted data: "{answer}"    // Based on the current running activity form definition html, make sure that the content of the submitted data has entered fields with readonly="false" in the form. If the readonly="true" fields are not entered, never return an error and ignore it. But if fields with readonly="false" are not entered, return the error "DATA_FIELD_NOT_EXIST".
    
    - Chat History:
    {chat_history}
    
    - Today is:  {today}
    
    - Process Instance Name Pattern: "{instance_name_pattern}"  // If there is no process instance name pattern, the key_value format of parameterValue, along with the process definition name, is the default for the instance name pattern. e.g. 휴가신청_이름_홍길동_사유_개인일정_시작일_20240701
    
    Given the current state, tell me which next step activity should be executed. Return the result in a valid json format:
    The data changes and role binding changes should be derived from the user submitted data or attached image OCR. 
    At this point, the data change values must be written in Python format, adhering to the process data types declared in the process definition. For example, if a process variable is declared as boolean, it should be true/false.
    Information about completed activities must be returned.
    The completedUserEmail included in completedActivities must be found in the role bindings and returned. If not, find the organization chart and return it.
    The nextUserEmail included in nextActivities must be found in the role bindings and returned. If not, find the organization chart and return it.
    If the condition of the sequence is not met for progression to the next step, it cannot be included in nextActivities and must be reported in cannotProceedErrors.
    startEvent/endEvent is not an activity id. Never be included in completedActivities/nextActivities.
    If the user-submitted data is insufficient, refer to the chat history to extract the process data values.
    
    result should be in this JSON format:
    {{
        "instanceId": "{instance_id}",
        "instanceName": "process instance name",
        "processDefinitionId": "{process_definition_id}",
        "dataChanges":
        [{{
            "key": "process data name", // Replace with _ if there is a space, Process Definition 에서 없는 데이터는 추가하지 않음.
            "value": <value for changed data>  // Refer to the data type of this process variable. For example, if the type of the process variable is Date, calculate and assign today's date.
        }}],

        "roleBindingChanges":
        [{{
            "roleName": "name of role",
            "userId": "email address for the role"
        }}],
        
        "completedActivities":
        [{{
            "completedActivityId": "the id of completed activity id", // Not Return if completedActivityId is "startEvent".
            "completedUserEmail": "the email address of completed activity’s role",
            "result": "DONE" // The result of the completed activity
        }}],
        
        "nextActivities":
        [{{
            "nextActivityId": "the id of next activity id", // Not Return "END_PROCESS" if nextActivityId is "endEvent".
            "nextUserEmail": "the email address of next activity’s role",
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
    userId: str

class DataChange(BaseModel):
    key: str
    value: Any

class ProceedError(BaseModel):
    type: str
    reason: Any

class ProcessResult(BaseModel):
    instanceId: str
    instanceName: str
    dataChanges: Optional[List[DataChange]] = None
    roleBindingChanges: Optional[List[RoleBindingChange]] = None
    nextActivities: List[Activity]
    completedActivities: List[CompletedActivity]
    processDefinitionId: str
    result: Optional[str] = None
    cannotProceedErrors: List[ProceedError]
    description: str

def execute_next_activity(process_result_json: dict) -> str:
    try:
        process_result = ProcessResult(**process_result_json)
        process_instance = None
        status = ""
        if not fetch_process_instance(process_result.instanceId):
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
                variables_data={},
                status=status,
                tenant_id=""
            )
        else:
            process_instance = fetch_process_instance(process_result.instanceId)
        
        process_definition = process_instance.process_definition

        if process_result.dataChanges:
            for data_change in process_result.dataChanges:
                process_instance.variables_data[data_change.key] = data_change.value
        # for data_change in process_result.dataChanges or []:
        #     setattr(process_instance, data_change.key, data_change.value)
            
        all_user_emails = set()
        if process_result.nextActivities:
            for activity in process_result.nextActivities:
                if activity.result == "IN_PROGRESS":
                    process_instance.current_activity_ids = [activity.nextActivityId]
                    process_instance.status = "RUNNING"
                if activity.nextActivityId == "endEvent" or activity.nextActivityId == "END_PROCESS" or activity.nextActivityId == "end_event":
                    process_instance.status = "COMPLETED"
                    process_instance.current_activity_ids = []
            if not process_instance.current_activity_ids:
                process_instance.current_activity_ids.append(process_result.nextActivities[0].nextActivityId)
            all_user_emails.update(activity.nextUserEmail for activity in process_result.nextActivities)
        for activity in process_result.completedActivities:
            all_user_emails.add(activity.completedUserEmail)
        
        current_user_ids_set = set(process_instance.current_user_ids)
        updated_user_emails = current_user_ids_set.union(all_user_emails)
        
        process_instance.current_user_ids = list(updated_user_emails)
        
        result = None

        for activity in process_result.nextActivities:
            activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
            if activity_obj and activity_obj.type == "ScriptActivity":
                env_vars = {key.upper(): value for key, value in process_instance.get_data().items()}
                result = execute_python_code(activity_obj.pythonCode, env_vars=env_vars)

                process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id)]
            else:
                result = (f"Next activity {activity.nextActivityId} is not a ScriptActivity or not found.")
                
        upsert_todo_workitems(process_instance.dict(), process_result.dict(), process_definition)
        
        workitems = None
        message_json = json.dumps({"description": ""})
        if not process_result.cannotProceedErrors:
            _, process_instance = upsert_process_instance(process_instance)
            upsert_completed_workitem(process_instance.dict(), process_result.dict(), process_definition)
            workitems = upsert_next_workitems(process_instance.dict(), process_result.dict(), process_definition)
            message_json = json.dumps({"description": process_result.description})
        else:
            reason = ""
            for error in process_result.cannotProceedErrors:
                reason += error.reason + "\n"
            message_json = json.dumps({"description": reason})
        upsert_chat_message(process_instance.proc_inst_id, message_json, True)
        
        # Updating process_result_json with the latest process instance details and execution result
        process_result_json["instanceId"] = process_instance.proc_inst_id
        process_result_json["instanceName"] = process_instance.proc_inst_name
        process_result_json["result"] = result
        # Ensure workitem is not None before accessing its id
        if workitems:
            process_result_json["workitemIds"] = [workitem.id for workitem in workitems]
        else:
            process_result_json["workitemIds"] = []

        return json.dumps(process_result_json)
    except Exception as e:
        message_json = json.dumps({"description": str(e)})
        upsert_chat_message(process_instance.proc_inst_id, message_json, True)
        raise HTTPException(status_code=500, detail=str(e)) from e

import base64
from langchain.schema.messages import HumanMessage, AIMessage

# 이미지 인코딩 함수
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# image = encode_image("./resume_real.png")

def vision_model_chain(input):
    formatted_prompt = prompt.format(**input)
    
    msg = vision_model.invoke(
        [   AIMessage(
                content=formatted_prompt
            ),
            HumanMessage(
                content=[
                    {"type": "text", "text": input['answer']},
                    {
                        "type": "image_url",
                        "image_url": {
                           "url": input['image'],
                            # "url": f"data:image/png;base64,{image}",
                            'detail': 'high'
                        },
                    },
                ]
            )
        ]
    )
    return msg

chain = (
    prompt | model | parser | execute_next_activity
)

vision_chain = (
    vision_model_chain | parser | execute_next_activity
)


def combine_input_with_process_definition(input):
    # 프로세스 인스턴스를 DB에서 검색
    try:
        process_instance_id = input.get('process_instance_id')  # 'process_instance_id' 키에 대한 접근 추가
        activity_id = input.get('activity_id') 
        image = input.get("image")
        user_info = input.get('userInfo')
        user_email = user_info.get('email')
        role_bindings = input.get('role_mappings')
        
        now = datetime.now()
        today = now.date()
        
        organizationChart = fetch_organization_chart()

        processDefinitionJson = None
        
        if process_instance_id!="new":
            process_instance = fetch_process_instance(process_instance_id)
            chat_history = fetch_chat_history(process_instance_id)
            
            message_json = json.dumps({"description": f"워크아이템 '{activity_id}' 을/를 실행합니다."})        
            upsert_chat_message(process_instance_id, message_json, True)

            if not process_instance:
                raise HTTPException(status_code=404, detail=f"Process instance with ID {process_instance_id} not found.")
        
            processDefinitionJson = fetch_process_definition(process_instance.get_def_id())
            process_definition_id = input.get('process_definition_id')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가
            
            form_definition = None
            if processDefinitionJson.get("activities"):
                for activity in processDefinitionJson["activities"]:
                    if activity["tool"]:
                        ui_definition = fetch_ui_definition_by_activity_id(process_definition_id, activity_id)
                        form_definition = ui_definition.html

            chain_input = {
                "answer": input['answer'],
                "instance_id": process_instance.proc_inst_id,
                "instance_name": process_instance.proc_inst_name,
                "role_bindings": process_instance.role_bindings,
                "data": process_instance.model_dump_json(),   #TODO 속성 중에 processdefinition 은 불필요한데 들어있어서 사이즈를 차지 하니 제외처리필요
                "current_activity_ids": process_instance.current_activity_ids,
                "current_user_ids": process_instance.current_user_ids,
                "processDefinitionJson": processDefinitionJson,
                "process_definition_id": process_instance.get_def_id(),
                "activity_id": activity_id,
                "image": image,
                "user_info": user_info,
                "user_email": user_email,
                "today": today,
                "organizationChart": organizationChart,
                "instance_name_pattern": processDefinitionJson.get("instanceNamePattern") or "",
                "form_definition": form_definition,
                "chat_history": chat_history
            }
        else:
            process_definition_id = input.get('process_definition_id')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가
            chat_history = fetch_chat_history(input['chat_room_id'])

            if not process_definition_id:
                raise HTTPException(status_code=404, detail="Neither process definition ID nor process instance ID was provided. Cannot start or proceed with the process.")
            
            processDefinitionJson = fetch_process_definition(process_definition_id)
            # processDefinition = load_process_definition(processDefinitionJson)

            form_definition = None  
            if processDefinitionJson.get("data"):
                for data_item in processDefinitionJson["data"]:
                    if data_item["type"] == "Form":
                        ui_definition = fetch_ui_definition_by_activity_id(process_definition_id, activity_id)
                        form_definition = ui_definition.html

            chain_input = {
                "answer": input['answer'],  
                "instance_id": input['chat_room_id'] or "new",
                "instance_name": "",
                "role_bindings": role_bindings or "no bindings",
                "data": "no data",
                "current_activity_ids": "there's no currently running activities",
                "current_user_ids": "there's no user currently running activities",
                "processDefinitionJson": processDefinitionJson,
                "process_definition_id": process_definition_id,
                "activity_id": activity_id or "id of the start event or start activity", #processDefinition.find_initial_activity().id,
                "image": image,
                "user_info": user_info,
                "user_email": user_email,
                "today": today,
                "organizationChart": organizationChart,
                "instance_name_pattern": processDefinitionJson.get("instanceNamePattern") or "",
                "form_definition": form_definition,
                "chat_history": chat_history
            }

        if image:
            return vision_chain.invoke(chain_input)
        else:
            return chain.invoke(chain_input)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

combine_input_with_process_definition_lambda = RunnableLambda(combine_input_with_process_definition)

from fastapi import Request

async def combine_input_with_token(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    
    token_data = parse_token(request)
    if token_data:
        user_info = fetch_user_info(token_data.get('email'))
        input['userInfo'] = user_info
        
        return combine_input_with_process_definition(input)
    else:
        raise HTTPException(status_code=401, detail="Invalid token")

### role binding
role_binding_prompt = PromptTemplate.from_template(
    """
    Now, we will create a system that recommends role performers at each stage when our employees start the process. Please refer to the resolution rule of the role in the process definition provided and our organization chart to find and return the best person for each role. If there is no suitable person, select yourself.

    - Roles in Process Definition: {roles}

    - Organization Chart: {organizationChart}
    
    - My Email: {myEmail}
    
    result should be in this JSON format:
    {{
        "roleBindings": [{{
            "roleName": "role name",
            "userId": "user email"
        }}]
    }}
    """
    )

def process_role_binding(result_json: dict) -> str:
    try:
        return json.dumps(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

role_binding_chain = (
    role_binding_prompt | model | parser | process_role_binding
)

async def combine_input_with_role_binding(request: Request):
    try:
        json_data = await request.json()
        input = json_data.get('input')
        token_data = parse_token(request)
        if token_data:
            my_email = token_data.get('email')
        roles = input.get('roles')
        organizationChart = fetch_organization_chart()
        
        chain_input = {
            "roles": roles,
            "organizationChart": organizationChart,
            "myEmail": my_email
        }
        
        return role_binding_chain.invoke(chain_input)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    

def add_routes_to_app(app) :
    app.add_api_route("/complete", combine_input_with_token, methods=["POST"])
    app.add_api_route("/vision-complete", combine_input_with_token, methods=["POST"])
    app.add_api_route("/role-binding", combine_input_with_role_binding, methods=["POST"])
    
    # add_routes(
    #     app,
    #     combine_input_with_process_definition_lambda | prompt | model | parser | execute_next_activity,
    #     path="/complete",
    # )

    # add_routes(
    #     app,
    #     combine_input_with_process_definition_lambda | vision_model_chain | parser | execute_next_activity,
    #     path="/vision-complete",
    # )

"""

# try this: 
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="company_entrance" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="$INST_ID" input[activity_id]="congrate" # 400  error
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="invalid instance id" input[activity_id]="registration"  # 404 error
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="$INST_ID" input[activity_id]="registration"  | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['nextActivities'])" 
# next activity id should be 'nextMail'
http :8000/complete/invoke input[answer]="no comment" input[process_instance_id]="$INST_ID" input[activity_id]="nextMail"


# 입사지원2: 입사 지원서 이미지 파일을 기반으로한: 
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="company_entrance" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID

http :8000/vision-complete/invoke input[answer]="세부 지원사항은 지원서에 확인해주십시오" input[process_instance_id]="$INST_ID" input[activity_id]="registration" 


# vacation use process
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="vacation_request" input[answer]="The total number of vacation days requested is 5, starting from February 5, 2024, to February 10, 2024, for the reason of travel" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="승인합니다" input[process_instance_id]="$INST_ID" input[activity_id]="manager_approval" # 400  error

# vacation addition process
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="vacation_addition" input[answer]="5일간 휴가를 추가합니다" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="승인합니다" input[process_instance_id]="$INST_ID" input[activity_id]="manager_approval" # 400  error



# TO-DO
1. 다음 시스템 활동은 재귀적으로 실행되어야 하므로, "congrate"에 이어서 실행되는 모든 활동이 연속적으로 실행됩니다. 따라서 여기서 다음 활동 ID는 'end' 또는 None이어야 합니다.
2. 시스템 액티비티 실행은 유저의 입력과 관계없이 완료가 이루어져야 하고, 실패시에 적절한 횟수의 재시도를 해야하기 때문에 유저에게 제공되는 웹서버가 사용하는 같은 쓰레드 상에서 처리해서는 안됨. 이를 제대로 처리하려면 별도 파이썬 인스턴스가 큐에(카프카 등) 쌓인 시스템 액티비티 실행 목록을 얻어와 실행을 하고 인스턴스 정보를 갱신처리하는 것이 맞음

pip install confluent_kafka

```
from confluent_kafka import Producer

def kafka_execute_python_code(activity_obj, env_vars):
    conf = {'bootstrap.servers': "localhost:9092"}  # Kafka 서버 설정
    producer = Producer(**conf)
    topic = 'execute_python_code_topic'

    # 실행 명령을 JSON 형태로 변환
    message = json.dumps({
        'py_code': activity_obj.py_code,
        'env_vars': env_vars
    })

    # Kafka 토픽으로 메시지 전송
    producer.produce(topic, value=message)
    producer.flush()

# 이전에 execute_python_code를 호출하던 부분을 kafka_execute_python_code로 대체
if activity_obj and activity_obj.type == "ScriptActivity":
    env_vars = {key.upper(): value for key, value in process_instance.data.items()}
    kafka_execute_python_code(activity_obj, env_vars)
```

---

Consumer 구현

별도의 Python 스크립트를 생성하여 Kafka Consumer를 구현합니다. 이 스크립트는 Kafka 토픽에서 메시지를 폴링하고, 받은 메시지에 따라 execute_python_code 함수를 실행합니다.


```
from confluent_kafka import Consumer, KafkaError
import json
from code_executor import execute_python_code  # 가정한 함수 임포트

conf = {
    'bootstrap.servers': "localhost:9092",
    'group.id': "python_code_executor_group",
    'auto.offset.reset': 'earliest'
}

consumer = Consumer(**conf)
consumer.subscribe(['execute_python_code_topic'])

try:
    while True:
        msg = consumer.poll(timeout=1.0)  # 1초 타임아웃으로 폴링

        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                print(msg.error())
                break

        # 메시지 처리
        message = json.loads(msg.value().decode('utf-8'))
        py_code = message['py_code']
        env_vars = message['env_vars']
        execute_python_code(py_code, env_vars=env_vars)  # 실제 코드 실행

finally:
    consumer.close()
```


3. 
"""