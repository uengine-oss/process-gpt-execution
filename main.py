from fastapi import FastAPI, HTTPException
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langserve import add_routes
from fastapi.staticfiles import StaticFiles
from langchain.output_parsers.json import SimpleJsonOutputParser  # JsonOutputParser 임포트
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from code_executor import execute_python_code
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables import ConfigurableField, RunnablePassthrough


from database import upsert_process_instance
from database import ProcessInstance
import uuid
import json
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="A simple api server using Langchain's Runnable interfaces",
)

app.mount("/static", StaticFiles(directory="static"), name="static")

import os
openai_api_key = os.getenv("OPENAI_API_KEY")

# 1. OpenAI Chat Model 생성
# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-3.5-turbo")
vision_model = ChatOpenAI(model="gpt-4-vision-preview", max_tokens = 4096)

# ConfigurableField를 사용하여 모델 선택 구성

parser = SimpleJsonOutputParser()


from process_definition import load_process_definition
from database import fetch_process_definition
from database import fetch_process_instance

# process_instance = fetch_process_instance(1)
# processDefinitionJson = fetch_process_definition(process_instance.def_id)



# process_definition = load_process_definition(processDefinitionJson)


prompt = PromptTemplate.from_template(
    """
    Now, you're going to create an interactive system similar to a BPM system that helps our company's employees understand various processes and take the next steps when they start a process or are curious about the next steps.

    - Process Definition:
    {processDefinitionJson}

    - Process Instance Id: {instance_id}

    - Process Data:
    {data}
    
    - Role Bindings:
    {role_bindings}

    - Currently Running Activities: 
    {current_activity_ids}

    - Received Message From Current Step:
    
      activityId: "{activity_id}",
      user: "jyjang@uengine.org",
      submitted data: {answer}
    

    
    Given the current state, tell me which next step activity should be executed. Return the result in a valid json format:
    The data changes and role binding changes should be derived from the user submitted data or attached image OCR. 
    At this point, the data change values must be written in Python format, adhering to the process data types declared in the process definition. For example, if a process variable is declared as boolean, it should be true/false.
    If the condition of the sequence is not met for progression to the next step, it cannot be included in nextActivities and must be reported in cannotProceedErrors.
    Return the result with the following description in markdown (three backticks):
    ```
    {{
        "instanceId": "{instance_id}",
        "processDefinitionId": "{process_definition_id}",
        "dataChanges":
        [{{
            "key": "process data name",
            "value": "value for chaned data"
        }}],

        "roleBindingChanges":
        [{{
            "roleName": "name of role",
            "userId": "email address for the role"
        }}],
    
        "nextActivities":
        [{{
            "nextActivityId": "the id of next activity id",
            "nextUserEmail": "the email address of next activity’s role"
        }}],

        "cannotProceedErrors":   // return errors if cannot proceed to next activity 
        [{{
            "type": "PROCEED_CONDITION_NOT_MET" | "SYSTEM_ERROR" 
            "reason": "explanation for the error"
        }}]

    }}
    
    ```
                                 
                                      
    """)


# Pydantic model for process execution
class Activity(BaseModel):
    nextActivityId: str
    nextUserEmail: Optional[str] = None

class RoleBindingChange(BaseModel):
    roleName: str
    userId: str

class DataChange(BaseModel):
    key: str
    value: Any

class ProcessResult(BaseModel):
    instanceId: str
    dataChanges: Optional[List[DataChange]] = None
    roleBindingChanges: Optional[List[RoleBindingChange]] = None
    nextActivities: List[Activity]
    processDefinitionId: str
    result: Optional[str] = None

def execute_next_activity(process_result_json: dict) -> str:
    process_result = ProcessResult(**process_result_json)
    process_instance = None

    if process_result.instanceId == "new":
        process_instance = ProcessInstance(
            proc_inst_id=f"{process_result.processDefinitionId}.{str(uuid.uuid4())}",
            proc_inst_name="please name me",
            role_bindings={},
            current_activity_ids=[]
        )
    else:
        process_instance = fetch_process_instance(process_result.instanceId)

    process_definition = process_instance.process_definition

    for data_change in process_result.dataChanges or []:
        setattr(process_instance, data_change.key, data_change.value)

    if process_result.nextActivities:
        process_instance.current_activity_ids = [activity.nextActivityId for activity in process_result.nextActivities]

    result = None

    for activity in process_result.nextActivities:
        activity_obj = process_definition.find_activity_by_id(activity.nextActivityId)
        if activity_obj and activity_obj.type == "ScriptActivity":
            env_vars = {key.upper(): value for key, value in process_instance.get_data().items()}
            result = execute_python_code(activity_obj.pythonCode, env_vars=env_vars)

            process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id)]
        else:
            result = (f"Next activity {activity.nextActivityId} is not a ScriptActivity or not found.")
  
    _, process_instance = upsert_process_instance(process_instance)

    
    # Updating process_result_json with the latest process instance details and execution result
    process_result_json["instanceId"] = process_instance.proc_inst_id
    process_result_json["nextActivities"] = process_instance.current_activity_ids
    process_result_json["result"] = result

    return json.dumps(process_result_json)

import base64
from langchain.schema.messages import HumanMessage, AIMessage

# 이미지 인코딩 함수
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

image = encode_image("./resume_real.png")

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
#                            "url": input['image'],
                            "url": f"data:image/png;base64,{image}",
                            'detail': 'high'
                        },
                    },
                ]
            )
        ]
    )
    return msg

def combine_input_with_process_definition(input):
    # 프로세스 인스턴스를 DB에서 검색
    
    process_instance_id = input.get('process_instance_id')  # 'process_instance_id' 키에 대한 접근 추가
    activity_id = input.get('activity_id') 
    image = input.get("image")

    processDefinitionJson = None
    
    if process_instance_id!="new":
        process_instance = fetch_process_instance(process_instance_id)

        if not process_instance:
            raise HTTPException(status_code=404, detail=f"Process instance with ID {process_instance_id} not found.")

        if activity_id not in process_instance.current_activity_ids:
            raise HTTPException(status_code=400, detail=f"Activity ID {activity_id} is not among the currently executing activities.")
    
        processDefinitionJson = fetch_process_definition(process_instance.get_def_id())

        return {
            "answer": input['answer'],  
            "instance_id": process_instance.proc_inst_id,
            "role_bindings": process_instance.role_bindings,
            "data": process_instance.model_dump_json(),
            "current_activity_ids": process_instance.current_activity_ids,
            "processDefinitionJson": processDefinitionJson,
            "process_definition_id": process_instance.get_def_id(),
            "activity_id": activity_id,
            "image": image
        }
    else:
        process_definition_id = input.get('process_definition_id')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가

        if not process_definition_id:
            raise HTTPException(status_code=404, detail="Neither process definition ID nor process instance ID was provided. Cannot start or proceed with the process.")
        
        processDefinitionJson = fetch_process_definition(process_definition_id)
        processDefinition = load_process_definition(processDefinitionJson)

        return {
            "answer": input['answer'],  
            "instance_id": "new",
            "role_bindings": "no bindings",
            "data": "no data",
            "current_activity_ids": "there's no currently running activities",
            "processDefinitionJson": processDefinitionJson,
            "process_definition_id": process_definition_id,
            "activity_id": processDefinition.find_initial_activity().id,
            "image": image
        }

combine_input_with_process_definition_lambda = RunnableLambda(combine_input_with_process_definition)

add_routes(
    app,
    combine_input_with_process_definition_lambda | prompt | model | parser | execute_next_activity,
    path="/complete",
)

add_routes(
    app,
    combine_input_with_process_definition_lambda | vision_model_chain | parser | execute_next_activity,
    path="/vision-complete",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)

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

http :8000/vision-complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="$INST_ID" input[activity_id]="registration" 


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