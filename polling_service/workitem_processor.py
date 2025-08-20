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
    upsert_todo_workitems, upsert_workitem, ProcessInstance,
    fetch_todolist_by_proc_inst_id, execute_rpc, upsert_cancelled_workitem, insert_process_instance
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

prompt_completed = PromptTemplate.from_template(
"""
You are a BPMN Completion Extractor.

Goal:
- 이번 스텝에서 **완료된 액티비티/이벤트만** 산출한다.
- 다음 액티비티는 계산하지 않는다.

Inputs:
Process Definition:
- activities: {activities}
- events and gateways: {gateways}
- sequences: {sequences}
- attached_activities: {attached_activities}
- subProcesses: {subProcesses}

Current Step:
- activity_id: {activity_id}
- user: {user_email}
- submitted_output: {output}

Runtime Context:
- previous_outputs: {previous_outputs}
- today: {today}
- gateway_condition_data: {gateway_condition_data}
- sequence_condition_data: {sequence_conditions}

Instructions:
1) 기본 완료 기록
- 현재 activity_id를 type="activity", result="DONE" or result="PENDING"으로 completedActivities에 추가한다.
- result="PENDING"인 경우 cannotProceedErrors에 추가한다.

2) 동일 레벨 집합 계산(피드백 제외) — merged_outputs에 채운다
- 변경된(보수적) 정의:
  1. 먼저 current의 즉시 타겟 집합 T를 구한다:
     T = {{ seq.target | seq ∈ sequences AND seq.source == activity_id }}.
  2. 만약 T에 게이트웨이 ID가 포함되어 있다면(즉 current가 게이트웨이로 이어져 분기를 트리거하는 경우):
     - 각 게이트웨이 G ∈ T에 대해 G의 타입을 확인한다 (gateways에 정의된 G.type).
     - **G.type == "parallelGateway"** 인 경우에만, 동일 레벨 집합에 G의 outgoing targets(=브랜치 시작 노드들)를 포함한다:
         branch_nodes_G = {{ s.target | s ∈ sequences AND s.source == G }}.
       동일 레벨 집합 = {activity_id} ∪ (⋃ branch_nodes_G over parallel gateways in T).
     - **G.type == "exclusiveGateway" 또는 "inclusiveGateway"** (또는 기타 조건부 게이트웨이) 인 경우:
       - 보수적 접근으로 자동 확장을 하지 않는다. 동일 레벨 집합 = {activity_id}.
  3. 만약 T에 게이트웨이가 없다면(=current가 단순히 다음 노드로 연결되는 경우):
     동일 레벨 집합 = {activity_id}.
  4. **중요:** 이전 로직에서 사용하던 역방향 집계(`same_level_sources = {{ seq.source | seq.target ∈ T }}`)는 사용하지 않는다. 이로써 게이트웨이를 통해 연결된 다른 독립 분기(형제 노드)들이 잘못 포함되는 것을 방지한다.
  5. 동일 레벨 집합에서 activities[id].type == "feedback" 인 항목은 제외한다.
  6. 이 동일 레벨 집합의 id들로만 merged_outputs 배열을 구성한다(중복 제거).
  7. 동일 레벨 집합의 id들 중 completedActivities에 아직 없는 항목은 type="activity", result="DONE"으로 추가한다.
     - description에는 "동일 레벨 완료 세트 추가"라고 표기한다.

(설명: 위 절차는 BPMN 2.0의 분기 의미를 존중합니다. parallel은 병렬 실행의 동등 레벨로 간주될 수 있어 branch 시작 노드를 merged_outputs에 포함할 수 있지만, exclusive/inclusive 등 조건 분기에서는 자동으로 형제 노드를 완료로 처리하면 안 되므로 포함하지 않습니다.)

3) 붙은 이벤트의 완료(오늘 기준)
- 현재 activity_id에 directly attached된 이벤트(attached_activities)를 확인한다.
- today 기준으로 도래한 이벤트만 completedActivities에 type="event", result="DONE"으로 추가한다.
  - expression은 "0 0 DD MM *", dueDate는 "YYYY-MM-DD".
  - 이 이벤트 id는 merged_outputs에는 **추가하지 않는다**(merged_outputs는 동일 레벨 액티비티 id 전용).

4) Output
- 반드시 아래 JSON만 출력한다. 추가 설명 금지.

5) InstanceName
- `instance_name_pattern`을 우선 사용. 비어 있으면 반드시 한글로 `processDefinitionName_key_value` 형식을 따라 20자 이내 생성.

```json
{{
  "instanceId": "{instance_id}",
  "instanceName": "process instance name",
  "processDefinitionId": "{process_definition_id}",
  "interruptByEvent": false,
  "fieldMappings": [],
  "merged_outputs": ["activity_or_event_id"],
  "roleBindings": {role_bindings},
  "completedActivities": [
    {{
      "completedActivityId": "activity_or_event_id",
      "completedActivityName": "name_if_available",
      "completedUserEmail": "{user_email}",
      "type": "activity" | "event",
      "expression": "cron expression if event",
      "dueDate": "YYYY-MM-DD if event",
      "result": "DONE",
      "description": "완료된 활동에 대한 설명 (Korean)",
      "cannotProceedErrors": []
    }}
  ],
  "nextActivities": [],
  "cancelledActivities": [],
  "referenceInfo": []
}}
"""
)

prompt_next = PromptTemplate.from_template(
"""
You are a BPMN Next Activity Planner.

Goal:
- 완료 추출기의 출력(`completedActivities`)을 받아 BPMN 2.0 토큰 규칙을 준수하여 **다음으로 활성화될 수 있는 노드만** `nextActivities`에 산출한다.
- completedActivities 의 결과 상태 값이 PENDING 으로 존재하는 경우에는 nextActivities 를 산출하지 않는다.
- **조건/데이터 평가는 오직 아래 입력들 내부에 존재하는 값만** 사용한다.
  - activities / gateways / events / sequences / attached_activities / subProcesses / roleBindings / next_activities / today

Inputs:
Process Definition:
- activities: {activities}
- gateways: {gateways}
- events: {events}
- sequences: {sequences}
- attached_activities: {attached_activities}
- subProcesses: {subProcesses}

Runtime Context:
- next_activities: {next_activities}
- roleBindings: {role_bindings}
- instance_name_pattern: {instance_name_pattern}
- today: {today}

From Completion Extractor:
- branch_merged_workitems: {branch_merged_workitems}

Instructions:
0) 데이터/그래프 원칙
- **없는 key를 만들거나 추론하지 않는다.** 값은 반드시 위 입력 구조 내부에 있어야 한다.
- 도달 가능성은 `sequences` 그래프와 `next_activities`(직접 outgoings 후보)를 사용해 판정한다. 여러 홉을 건너뛰지 않는다.
- 진행 불가(값 부재/조건 미결정/조인 미충족 추정/이벤트 미발생) 시 **오류 없이** `nextActivities: []`로 대기.
- nextActivities에는 오직 activity, event, subProcess, callActivity만 포함되어야 하며, gateway id는 절대 포함하면 안 된다.

1) Interrupt-first (이벤트)
- 오늘 날짜(`today`)와 `events`/`attached_activities`/`sequences` 상의 정보만으로 **due가 명확한 이벤트**가 있고, 현재 지점에서 **도달 가능**하면:
  - `interruptByEvent=true`, 해당 이벤트 **하나만** `nextActivities`에 넣고 종료.
- 판단 불가/미도래면 `interruptByEvent=false`로 두고 진행.

2) Non-gateway 대상 처리
- `next_activities` 후보 중 게이트웨이가 **아닌** 대상(액티비티/서브프로세스/이벤트)에 대해:
  - 해당 시퀀스의 조건(있다면 `sequences` 또는 `gateways`에 명시된 표현)을 **입력 구조 내부 값으로만** 평가한다.
  - 참으로 판정 가능한 후보만 `nextActivities`에 포함한다. 거짓/판단불가는 제외(대기).
- target이 `subProcesses`에 존재하면:
  - type="subProcess", nextUserEmail="system",
  - description="서브프로세스를 시작합니다. 내부 액티비티는 서브프로세스 컨텍스트에서 할당됩니다."

3) Gateways (explicit only; from `gateways.type`)
- 다음 노드가 `gateways`에 존재하면 그 `type`으로만 동작한다:
  - **exclusiveGateway (XOR)**:
    - `sequences`/`gateways` 내부의 조건을 입력 구조 값으로 평가해 **참 하나**가 명확하면 그 경로만 진행.
    - 여러 개가 동시 참이면 모델의 우선순위/디폴트가 명시돼 있을 때만 그 규칙을 적용, 없으면 **대기**.
    - 전혀 참이 없고 default flow가 명시돼 있으면 default로 진행, 아니면 **대기**.
  - **inclusiveGateway (OR)**:
    - 참으로 판정 가능한 모든 아웃고잉을 활성화.
    - 이후 조인이 필요하면(모델 상 대응 OR-join 존재) **모든 선택 분기의 즉시 선행이 `branch_merged_workitems`에 존재**할 때만 조인 뒤 1-hop 타겟을 next로 산출. 아니면 **대기**.
  - **parallelGateway (AND)**:
    - Split: 조건 평가 없이 **모든 아웃고잉**을 next에 포함.
    - Join: `branch_merged_workitems`와 `sequences`만으로 **모든 즉시 선행 분기가 완료**되었음이 명확할 때만 조인 뒤 1-hop 타겟을 next로 산출. 불명확/미충족이면 **대기**.
  - **eventBasedGateway**:
    - 실제 발생한 이벤트가 `events`/`attached_activities`/`sequences`에서 판정 가능할 때만 그 단일 경로 진행. 아니면 **대기**.

4) Attached Events (simultaneous inclusion)
- `nextActivities`에 포함된 activity/subProcess가 `attached_activities.activity_id`로 존재하면,
  - 그 `attached_events` 각각을 type="event"로 **별도 엔트리**로 추가한다(이미 완료/취소 제외).

5) Assignment
- `roleBindings`의 endpoint가 배열이면 `,`으로 조인하여 nextUserEmail을 결정한다.
- 외부 고객 역할이면 입력 구조 내에서 email을 찾을 수 있을 때만 사용한다(없으면 해당 항목 제외).
- 유효 email을 결정할 수 없으면 **오류 없이 제외**하고, 나머지 항목은 계속 검토한다.

6) InstanceName
- `instance_name_pattern`을 우선 사용. 비어 있으면 반드시 한글로 `processDefinitionName_key_value` 형식을 따라 20자 이내 생성.

7) 출력 형식
- 반드시 JSON만 출력(설명 금지). 진행 불가 시 `interruptByEvent=false`, `nextActivities: []`.

Return ONLY the JSON block below, no extra text, no explanation.

```json
{{
  "instanceId": "{instance_id}",
  "instanceName": "process instance name",
  "processDefinitionId": "{process_definition_id}",
  "interruptByEvent": true | false,
  "fieldMappings": [],
  "roleBindings": {role_bindings},
  "completedActivities": {completedActivities}, 
  "nextActivities": [
    {{
      "nextActivityId": "id",
      "nextActivityName": "name",
      "nextUserEmail": "email_or_system",
      "type": "activity" | "subProcess" | "event",
      "expression": "cron if event",
      "dueDate": "YYYY-MM-DD if event",
      "result": "IN_PROGRESS",
      "description": "Korean description"
    }}
  ],
  "cancelledActivities": [],
  "referenceInfo": []
}}
"""
)

# Pydantic model for process execution
class ProceedError(BaseModel):
    type: str
    reason: str

class Activity(BaseModel):
    nextActivityId: Optional[str] = None
    nextActivityName: Optional[str] = None
    nextUserEmail: Optional[str] = None
    result: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    expression: Optional[str] = None

class CompletedActivity(BaseModel):
    completedActivityId: Optional[str] = None
    completedActivityName: Optional[str] = None
    completedUserEmail: Optional[str] = None
    result: Optional[str] = None
    description: Optional[str] = None
    cannotProceedErrors: Optional[List[ProceedError]] = None

class ReferenceInfo(BaseModel):
    key: Optional[str] = None
    value: Optional[str] = None

class FieldMapping(BaseModel):
    key: str
    name: str
    value: Any

class ProcessResult(BaseModel):
    instanceId: str
    instanceName: str
    fieldMappings: Optional[List[FieldMapping]] = None
    nextActivities: Optional[List[Activity]] = None
    completedActivities: Optional[List[CompletedActivity]] = None
    processDefinitionId: str
    result: Optional[str] = None
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
            tenant_id=tenant_id,
            root_proc_inst_id=instance_id
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
            if activity.type == "event":
                process_instance.current_activity_ids = [activity.nextActivityId]
            else:
                next_activities = process_definition.find_next_activities(activity.nextActivityId, True)
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

def _process_sub_processes(process_instance: ProcessInstance, process_result: ProcessResult, 
                         process_result_json: dict, process_definition):
    """Process sub processes: spawn child instances for any detected subprocess nodes.
    Resolution order for child processDefinitionId:
    1) next_sub_process.properties JSON contains one of [calledElement, processDefinitionId, procDefId]
    2) Fallback to next_sub_process.id
    If the child process definition JSON cannot be fetched, we still create the child process instance
    (NEW) with the parent linkage. Additionally, when child definition is missing, first try to build a
    full child definition from the subprocess's embedded 'children' definition; if absent, synthesize a
    minimal start->task->end definition to avoid recursion.
    """
    for activity in process_result.nextActivities:
        # Detect subprocess either as the immediate next node, or as the next-through sequence
        next_sub_process = process_definition.find_next_sub_process(activity.nextActivityId)
        if not next_sub_process:
            next_sub_process = process_definition.find_sub_process_by_id(activity.nextActivityId)
        if not next_sub_process:
            continue

        # Resolve child processDefinitionId
        child_proc_def_id = None
        if getattr(next_sub_process, "properties", None):
            try:
                props = next_sub_process.properties
                if isinstance(props, str):
                    props_json = json.loads(props)
                elif isinstance(props, dict):
                    props_json = props
                else:
                    props_json = {}
                for key in ["calledElement", "processDefinitionId", "procDefId"]:
                    if props_json.get(key):
                        child_proc_def_id = props_json.get(key)
                        break
                # Fallback: embedded definition provided directly
                embedded_child_def = props_json.get("embeddedDefinition") or props_json.get("definition") or props_json.get("processDefinition")
            except Exception:
                child_proc_def_id = None
                embedded_child_def = None
        else:
            embedded_child_def = None
        if not child_proc_def_id:
            child_proc_def_id = next_sub_process.id

        print(f"[DEBUG] Next sub process detected: node={next_sub_process.id}, child_proc_def_id={child_proc_def_id}")

        # Load child process definition if available
        child_def = None
        if embedded_child_def:
            try:
                child_def = load_process_definition(embedded_child_def if isinstance(embedded_child_def, dict) else json.loads(embedded_child_def))
            except Exception as e:
                print(f"[WARN] Failed to load embedded child definition for '{child_proc_def_id}': {e}")
        # Try to construct from subprocess.children in the parent raw definition JSON
        if child_def is None:
            try:
                parent_def_json = fetch_process_definition(process_instance.get_def_id(), process_instance.tenant_id)
                if parent_def_json and isinstance(parent_def_json, dict):
                    sp_entry = next((sp for sp in parent_def_json.get('subProcesses', []) if sp.get('id') == next_sub_process.id), None)
                    if sp_entry and isinstance(sp_entry.get('children'), dict):
                        children = sp_entry['children']
                        child_def_dict = {
                            'processDefinitionName': next_sub_process.name or f"Subprocess {next_sub_process.id}",
                            'processDefinitionId': f"{process_instance.process_definition.processDefinitionId}.{next_sub_process.id}",
                            'description': parent_def_json.get('description'),
                            'data': children.get('data', []),
                            'roles': parent_def_json.get('roles', []),
                            'activities': children.get('activities', []),
                            'subProcesses': children.get('subProcesses', []),
                            'sequences': children.get('sequences', []),
                            'gateways': children.get('events', []),
                        }
                        try:
                            child_def = load_process_definition(child_def_dict)
                            child_proc_def_id = child_def.processDefinitionId
                        except Exception as e:
                            print(f"[WARN] Failed to load child definition from children for '{child_proc_def_id}': {e}")
            except Exception as e:
                print(f"[WARN] Failed to construct child from children: {e}")
        if child_def is None:
            try:
                child_def_json = fetch_process_definition(child_proc_def_id, process_instance.tenant_id)
                child_def = load_process_definition(child_def_json)
            except Exception as e:
                print(f"[WARN] Failed to fetch child process definition '{child_proc_def_id}': {e}")

        # If still missing, build minimal synthetic child definition from subprocess
        if child_def is None:
            print(f"[INFO] Building synthetic child definition from subprocess node={next_sub_process.id}")
            # Try to use the first inner activity directly connected from this subprocess
            # Heuristic: activities whose srcTrg == subprocess.id
            try:
                inner_activities = [a for a in (process_instance.process_definition.activities or []) if getattr(a, 'srcTrg', None) == next_sub_process.id]
            except Exception:
                inner_activities = []

            parent_roles = process_instance.process_definition.roles or []
            sub_role_name = getattr(next_sub_process, 'role', None)
            role_endpoint = None
            if sub_role_name:
                for r in parent_roles:
                    if getattr(r, 'name', None) == sub_role_name:
                        role_endpoint = getattr(r, 'endpoint', None)
                        break
            synthetic_role = [{
                'name': sub_role_name or 'subprocess_role',
                'endpoint': role_endpoint,
                'resolutionRule': None
            }]

            if inner_activities:
                first_inner = inner_activities[0]
                first_act_dict = {
                    'name': getattr(first_inner, 'name', first_inner.id),
                    'id': first_inner.id,
                    'type': getattr(first_inner, 'type', 'userTask'),
                    'description': getattr(first_inner, 'description', '') or (next_sub_process.name or 'Subprocess task'),
                    'attachedEvents': getattr(first_inner, 'attachedEvents', []) or [],
                    'role': getattr(first_inner, 'role', sub_role_name or 'subprocess_role'),
                    'inputData': getattr(first_inner, 'inputData', []) or [],
                    'outputData': getattr(first_inner, 'outputData', []) or [],
                    'checkpoints': getattr(first_inner, 'checkpoints', []) or [],
                    'pythonCode': getattr(first_inner, 'pythonCode', None),
                    'tool': getattr(first_inner, 'tool', None),
                    'properties': getattr(first_inner, 'properties', None),
                    'duration': getattr(first_inner, 'duration', None),
                    'srcTrg': None,
                    'agentMode': getattr(first_inner, 'agentMode', None),
                    'orchestration': getattr(first_inner, 'orchestration', None)
                }
                synthetic_activity_id = first_act_dict['id']
            else:
                # Fallback: single userTask if we cannot find an inner activity
                synthetic_activity_id = f"{next_sub_process.id}_activity"
                first_act_dict = {
                    'name': next_sub_process.name or synthetic_activity_id,
                    'id': synthetic_activity_id,
                    'type': 'userTask',
                    'description': next_sub_process.name or 'Subprocess task',
                    'attachedEvents': [],
                    'role': sub_role_name or 'subprocess_role',
                    'inputData': [],
                    'outputData': [],
                    'checkpoints': [],
                    'pythonCode': None,
                    'tool': None,
                    'properties': None,
                    'duration': getattr(next_sub_process, 'duration', None),
                    'srcTrg': None,
                    'agentMode': None,
                    'orchestration': None
                }

            synthetic_def_dict = {
                'processDefinitionName': next_sub_process.name or f"Subprocess {next_sub_process.id}",
                'processDefinitionId': f"{process_instance.process_definition.processDefinitionId}.{next_sub_process.id}",
                'description': f"Synthetic definition generated from subprocess {next_sub_process.id}",
                'data': [],
                'roles': synthetic_role,
                'activities': [first_act_dict],
                'subProcesses': [],
                'sequences': [
                    {'id': f'seq_start_{synthetic_activity_id}', 'source': 'start_event', 'target': synthetic_activity_id, 'condition': None, 'properties': None},
                    {'id': f'seq_{synthetic_activity_id}_end', 'source': synthetic_activity_id, 'target': 'end_event', 'condition': None, 'properties': None},
                ],
                'gateways': [
                    {'id': 'start_event', 'name': 'Start', 'role': None, 'type': 'startEvent', 'process': None, 'condition': {}, 'conditionData': None, 'properties': None, 'description': None, 'srcTrg': None, 'duration': None, 'agentMode': None, 'orchestration': None},
                    {'id': 'end_event', 'name': 'End', 'role': None, 'type': 'endEvent', 'process': None, 'condition': {}, 'conditionData': None, 'properties': None, 'description': None, 'srcTrg': None, 'duration': None, 'agentMode': None, 'orchestration': None},
                ]
            }
            try:
                child_def = load_process_definition(synthetic_def_dict)
                child_proc_def_id = child_def.processDefinitionId
            except Exception as e:
                print(f"[ERROR] Failed to build synthetic child definition: {e}")
                continue

        # Create child process instance id
        parent_def_id = process_instance.process_definition.processDefinitionId
        child_proc_def_id = parent_def_id
        child_proc_inst_id = f"{child_proc_def_id.lower()}.{str(uuid.uuid4())}"

        # Collect participants from parent's role_bindings
        participants = []
        role_bindings = process_instance.role_bindings or []
        for rb in role_bindings:
            endpoint = rb.get("endpoint")
            if isinstance(endpoint, list):
                participants.extend(endpoint)
            elif endpoint:
                participants.append(endpoint)

        # Insert child process instance with parent link
        try:
            process_instance_data = {
                "proc_inst_id": child_proc_inst_id,
                "proc_inst_name": child_def.processDefinitionName if child_def else child_proc_def_id,
                "proc_def_id": child_proc_def_id,
                "participants": participants,
                "status": "NEW",
                "role_bindings": role_bindings,
                "start_date": datetime.now().isoformat(),
                "tenant_id": process_instance.tenant_id,
                "parent_proc_inst_id": process_instance.proc_inst_id,
                "root_proc_inst_id": process_instance.root_proc_inst_id,
            }
            insert_process_instance(process_instance_data, process_instance.tenant_id)
            print(f"[INFO] Spawned child instance: {child_proc_inst_id} (parent={process_instance.proc_inst_id})")
        except Exception as e:
            print(f"[ERROR] Failed to insert child process instance '{child_proc_inst_id}': {e}")
            continue

        # Create initial workitem for child using resolved child_def
        try:
            # Create a startEvent workitem as the first item
            start_event = next((gw for gw in (child_def.gateways or []) if getattr(gw, 'type', None) == 'startEvent'), None)
            if start_event:
                start_date = datetime.now().isoformat()
                workitem_data = {
                    "id": str(uuid.uuid4()),
                    "user_id": endpoint,
                    "username": None,
                    "proc_inst_id": child_proc_inst_id,
                    "proc_def_id": child_proc_def_id,
                    "activity_id": start_event.id,
                    "activity_name": start_event.name or 'Start',
                    "start_date": start_date,
                    "due_date": None,
                    "status": "SUBMITTED",
                    "assignees": role_bindings,
                    "reference_ids": [],
                    "duration": None,
                    "tool": None,
                    "output": {},
                    "retry": 0,
                    "consumer": None,
                    "description": start_event.description or '',
                    "tenant_id": process_instance.tenant_id,
                    "root_proc_inst_id": process_instance.root_proc_inst_id,
                }
                upsert_workitem(workitem_data, process_instance.tenant_id)
                print(f"[INFO] Created startEvent workitem for child: {child_proc_inst_id} -> {start_event.id}")
            else:
                # Fallback: use first activity if no startEvent exists
                initial_act = child_def.find_initial_activity() if child_def else None
                if not initial_act:
                    print(f"[WARN] No initial activity found for child process '{child_proc_def_id}'")
                else:
                    start_date = datetime.now().isoformat()
                    due_date = None
                    if initial_act.duration:
                        try:
                            from datetime import timedelta
                            due_date = (datetime.now() + timedelta(days=initial_act.duration)).isoformat()
                        except Exception:
                            due_date = None

                    workitem_data = {
                        "id": str(uuid.uuid4()),
                        "user_id": endpoint,
                        "username": None,
                        "proc_inst_id": child_proc_inst_id,
                        "proc_def_id": child_proc_def_id,
                        "activity_id": initial_act.id,
                        "activity_name": initial_act.name,
                        "start_date": start_date,
                        "due_date": due_date,
                        "status": "SUBMITTED",
                        "assignees": role_bindings,
                        "reference_ids": [],
                        "duration": initial_act.duration,
                        "tool": initial_act.tool,
                        "output": {},
                        "retry": 0,
                        "consumer": None,
                        "description": initial_act.description,
                        "tenant_id": process_instance.tenant_id,
                        "root_proc_inst_id": process_instance.root_proc_inst_id,
                    }
                    upsert_workitem(workitem_data, process_instance.tenant_id)
                    print(f"[INFO] Created initial activity workitem for child: {child_proc_inst_id} -> {initial_act.id}")
        except Exception as e:
            print(f"[ERROR] Failed to create initial workitem for child '{child_proc_inst_id}': {e}")

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
                process_instance.current_activity_ids = [activity.id for activity in process_definition.find_next_activities(activity_obj.id)]
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

def _register_event(process_instance: ProcessInstance, process_result: ProcessResult, 
                   process_result_json: dict, process_definition):
    """Register intermediate events when process instance is in WAITING status"""
    try:
        print(f"[DEBUG] Starting event registration for process instance: {process_instance.proc_inst_id}")
        
        # Find intermediate events in current process state
        events = []
        
        # Check current activity IDs for intermediate events
        if process_result.nextActivities:
            for activity in process_result.nextActivities:
                # Check if activity is an intermediate event (gateway with event type)
                gateway = process_definition.find_gateway_by_id(activity.nextActivityId)
                if gateway:
                    events.append({
                        'event_id': gateway.id,
                        'event_name': gateway.name,
                        'event_type': gateway.type,
                        'condition': gateway.condition,
                        'expression': activity.expression,
                        'process_id': process_instance.proc_inst_id,
                        'properties': gateway.properties
                    })
                    print(f"[DEBUG] Found intermediate event: {gateway.id} of type {gateway.type}")
        
        # Register events if found
        if events:
            for event in events:
                _register_single_event(process_instance, event, process_result_json)
                print(f"[INFO] Registered intermediate event: {event['event_id']}")
        else:
            print(f"[DEBUG] No intermediate events found for process instance: {process_instance.proc_inst_id}")
            
    except Exception as e:
        print(f"[ERROR] Failed to register events for process instance {process_instance.proc_inst_id}: {str(e)}")
        # Don't raise exception to avoid breaking the main process flow
        import traceback
        print(traceback.format_exc())
def _is_intermediate_event(gateway) -> bool:
    """Check if gateway represents an intermediate event"""
    intermediate_event_types = [
        "intermediateThrowEvent",
        "intermediateCatchEvent", 
        "timerIntermediateEvent",
        "messageIntermediateEvent",
        "signalIntermediateEvent",
        "conditionalIntermediateEvent",
        "linkIntermediateEvent",
        "escalationIntermediateEvent",
        "errorIntermediateEvent",
        "cancelIntermediateEvent",
        "compensationIntermediateEvent"
    ]
    
    return gateway.type in intermediate_event_types
def _register_single_event(process_instance: ProcessInstance, event: dict, process_result_json: dict):
    """Register a single intermediate event - Implementation placeholder"""
    # TODO: Implement actual event registration logic here
    # This could involve:
    # - Creating event listeners for timer events
    # - Setting up message subscriptions for message events  
    # - Registering signal handlers for signal events
    # - Setting up conditional checks for conditional events
    # - Storing event metadata in database
    
    print(f"[PLACEHOLDER] Event registration logic for {event['event_type']} event {event['event_id']} goes here")
    
    # Example structure for what the implementation might look like:
    _register_timer_event(process_instance, event)
    # elif event['event_type'] == 'messageIntermediateEvent':
    #     _register_message_event(process_instance, event)
    # elif event['event_type'] == 'signalIntermediateEvent':
    #     _register_signal_event(process_instance, event)
    # else:
    #     _register_generic_event(process_instance, event)
    
def _register_timer_event(process_instance: ProcessInstance, event: dict):
    """Register a timer intermediate event"""
    print(f"[INFO] Registering timer intermediate event: {event['event_id']}")
    if event['expression']:
        job_name = f"{event['process_id']}_{event['event_id']}"
        cron_expr = event['expression']
        params = {
            "p_job_name": job_name,
            "p_cron_expr": cron_expr,
            "p_input": {
                "proc_inst_id": event['process_id'],
                "activity_id": event['event_id']
            }
        }
        result = execute_rpc("register_cron_intermidiated", params)
    return result
def _persist_process_data(process_instance: ProcessInstance, process_result: ProcessResult, 
                         process_result_json: dict, process_definition, tenant_id: Optional[str] = None):
    """Persist process data to database and vector store"""
    # Upsert workitems
    upsert_todo_workitems(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    completed_workitems = upsert_completed_workitem(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    upsert_cancelled_workitem(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    next_workitems = upsert_next_workitems(process_instance.model_dump(), process_result_json, process_definition, tenant_id)
    
    # Upsert process instance
    if process_instance.status == "NEW":
        process_instance.proc_inst_name = process_result.instanceName
    _, process_instance = upsert_process_instance(process_instance, tenant_id)
    
    appliedFeedback = False
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
                "contentType": "html" if form_html else "text",
                "activityId": completed_workitem.activity_id
            }
            upsert_chat_message(completed_workitem.proc_inst_id, message_data, tenant_id)
            if completed_workitem.temp_feedback and completed_workitem.temp_feedback not in [None, ""]:
                appliedFeedback = True

    description = {
        "referenceInfo": process_result_json.get("referenceInfo", []),
        "completedActivities": process_result_json.get("completedActivities", []),
        "nextActivities": process_result_json.get("nextActivities", []),
        "appliedFeedback": appliedFeedback
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
        
        # Process sub processes
        _process_sub_processes(process_instance, process_result, process_result_json, process_definition)
        
        # Execute script tasks
        _execute_script_tasks(process_instance, process_result, process_result_json, process_definition)
        
        # Persist data
        _persist_process_data(process_instance, process_result, process_result_json, process_definition, tenant_id)
        
        # Regester event
        _register_event(process_instance, process_result, process_result_json, process_definition)
        
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
    
async def run_prompt_and_parse(prompt_tmpl, chain_input, workitem, tenant_id, parser, log_prefix="[LLM]"):
    collected_text = ""
    num_of_chunk = 0

    async for chunk in model.astream(prompt_tmpl.format(**chain_input)):
        token = chunk.content
        collected_text += token

        # 실시간 로그 적재
        upsert_queue.put((
            {
                "id": workitem['id'],
                "log": f"{log_prefix} {collected_text}"
            },
            tenant_id
        ))
        num_of_chunk += 1
        if num_of_chunk % 10 == 0:
            upsert_workitem({"id": workitem['id'], "log": collected_text}, tenant_id)

    # 파싱 리트라이
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
                print(f"[ERROR] All JSON parsing attempts failed. Raw response: {collected_text[:500]}...")
                upsert_workitem({
                    "id": workitem['id'],
                    "status": "ERROR",
                    "log": f"JSON parsing failed after {max_retries} attempts: {str(parse_error)}"
                }, tenant_id)
                error_message = json.dumps({
                    "role": "system",
                    "content": f"JSON 파싱 오류가 발생했습니다: {str(parse_error)}"
                })
                upsert_chat_message(workitem['proc_inst_id'], error_message, tenant_id)
                raise parse_error

            await asyncio.sleep(0.5)

    if parsed_output is None:
        raise Exception("Failed to parse JSON response after all retry attempts")

    return parsed_output, collected_text


def get_sequence_condition_data(process_definition: Any, next_activities: List[str]):
    """
    워크아이템 실행에 필요한 시퀀스 조건 데이터 추출
    """
    try:
        sequence_condition_data = {}
        for sequence in process_definition.sequences:
            if sequence.target in next_activities:
                properties = sequence.properties
                if properties:
                    properties_json = json.loads(properties)
                    sequence_condition_data[sequence.id] = properties_json
        return sequence_condition_data
    except Exception as e:
        print(f"[ERROR] Failed to get sequence condition data: {str(e)}")
        return None

async def handle_workitem(workitem):
    is_first, is_last = get_workitem_position(workitem)

    if workitem.get('retry', 0) >= 3:
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
    if workitem.get('output') and isinstance(workitem['output'], str):
        try:
            output = json.loads(workitem['output'])
        except Exception:
            output = {}
    else:
        output = workitem.get('output') or {}

    form_id = ui_definition.id if ui_definition else None
    if form_id and isinstance(output, dict) and output.get(form_id):
        output = output.get(form_id)

    try:
        next_activities = []
        gateway_condition_data = None
        sequence_condition_data = None

        if process_definition:
            next_activities = [activity.id for activity in process_definition.find_next_activities(activity_id, True)]
            for act_id in next_activities:
                if process_definition.find_gateway_by_id(act_id):
                    try:
                        gateway_condition_data = get_gateway_condition_data(workitem, process_definition, act_id)
                    except Exception as e:
                        print(f"[ERROR] Failed to get gateway condition data for {workitem.get('id')}: {str(e)}")
                        gateway_condition_data = None

            sequence_condition_data = get_sequence_condition_data(process_definition, next_activities)

        workitem_input_data = None
        try:
            workitem_input_data = get_input_data(workitem, process_definition)
        except Exception as e:
            print(f"[ERROR] Failed to get selected info for {workitem.get('id')}: {str(e)}")

        attached_activities = []
        for next_activity in next_activities:
            activity = process_definition.find_activity_by_id(next_activity)
            if activity and getattr(activity, 'attachedEvents', None):
                attached_activities.append({
                    "activity_id": activity.id,
                    "attached_events": activity.attachedEvents
                })

        if not workitem['user_id'] or ',' not in workitem['user_id']:
            user_email_for_prompt = workitem['user_id']
        else:
            user_email_for_prompt = ','.join(workitem['user_id'].split(','))

        chain_input_completed = {
            "activities": process_definition.activities,
            "gateways": process_definition_json.get('gateways', []),
            "events": process_definition_json.get('events', []),
            "subProcesses": process_definition.subProcesses,
            "sequences": process_definition.sequences,
            "role_bindings": workitem.get('assignees', []),

            "instance_id": process_instance_id,
            "process_definition_id": process_definition_id,
            "activity_id": activity_id,
            "user_email": user_email_for_prompt,
            "output": output,

            "today": today,
            "previous_outputs": workitem_input_data,
            "gateway_condition_data": gateway_condition_data,
            "attached_activities": attached_activities,
            "sequence_conditions": sequence_condition_data
        }

        completed_json, completed_log = await run_prompt_and_parse(
            prompt_completed, chain_input_completed, workitem, tenant_id, parser, log_prefix="[COMPLETED]"
        )

        completed_activities_from_step = (
            completed_json.get("completedActivities")
            or completed_json.get("completedActivitiesDelta")
            or []
        )
        merged_outputs_from_step = completed_json.get("merged_outputs", None)
        merged_workitems_from_step = []
        if merged_outputs_from_step is not None:
            for merged_output in merged_outputs_from_step:
                merged_workitems = fetch_workitem_by_proc_inst_and_activity(process_instance_id, merged_output, tenant_id)
                merged_workitems_from_step.append(merged_workitems)

        chain_input_next = {
            "activities": process_definition.activities,
            "gateways": process_definition_json.get('gateways', []),
            "events": process_definition_json.get('events', []),
            "subProcesses": process_definition.subProcesses,
            "sequences": process_definition.sequences,
            "instance_id": process_instance_id,
            "process_definition_id": process_definition_id,

            "next_activities": next_activities,
            "role_bindings": workitem.get('assignees', []),
            "instance_name_pattern": process_definition_json.get("instanceNamePattern") or "",
            "today": today,
            
            "branch_merged_workitems": merged_workitems_from_step,

            "completedActivities": completed_activities_from_step,
            "attached_activities": attached_activities
        }

        next_json, next_log = await run_prompt_and_parse(
            prompt_next, chain_input_next, workitem, tenant_id, parser, log_prefix="[NEXT]"
        )

        result = execute_next_activity(next_json, tenant_id)
        result_json = json.loads(result)

    except Exception as e:
        print(f"[ERROR] Error in handle_workitem for workitem {workitem['id']}: {str(e)}")
        raise e

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