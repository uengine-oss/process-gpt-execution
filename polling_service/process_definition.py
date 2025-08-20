import json
from pathlib import Path
from typing import Any, Dict, List, Union, Optional
from pydantic import BaseModel, Field, root_validator

class DataSource(BaseModel):
    type: str
    sql: Optional[str] = None

class Variable(BaseModel):
    name: str
    description: str
    type: str
    dataSource: Optional[DataSource] = None

class ProcessData(BaseModel):
    name: str
    type: str
    table: Optional[str] = None
    description: Optional[str] = None
    dataSource: Optional[DataSource] = None

class ProcessRole(BaseModel):
    name: str
    endpoint: Optional[Any] = None
    resolutionRule: Optional[str] = None
    
class ProcessActivity(BaseModel):
    name: str
    id: str
    type: str
    description: str
    instruction: Optional[str] = None
    attachedEvents: Optional[List[str]] = Field(default_factory=list)
    role: str
    inputData: Optional[List[str]] = Field(default_factory=list)
    outputData: Optional[List[str]] = Field(default_factory=list)
    checkpoints: Optional[List[str]] = Field(default_factory=list)
    pythonCode: Optional[str] = None
    tool: Optional[str] = None
    properties: Optional[str] = None
    duration: Optional[int] = None
    srcTrg: Optional[str] = None
    agentMode: Optional[str] = None
    orchestration: Optional[str] = None
    
    def __hash__(self):
        return hash(self.id)  # 또는 다른 고유한 속성을 사용

    def __eq__(self, other):
        if isinstance(other, ProcessActivity):
            return self.id == other.id  # 또는 다른 비교 로직을 사용
        return False

class SubProcess(BaseModel):
    name: str
    id: str
    type: str
    role: str
    attachedEvents: Optional[List[str]] = Field(default_factory=list)
    properties: Optional[str] = None
    duration: Optional[int] = None
    srcTrg: Optional[str] = None
    children: Optional["ProcessDefinition"] = None

class ProcessSequence(BaseModel):
    id: str
    source: str
    target: str
    condition: Optional[str] = None
    properties: Optional[str] = None

class ProcessGateway(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    process: Optional[str] = None
    condition: Optional[Dict[str, Any]] = Field(default_factory=dict)
    conditionData: Optional[List[str]] = None
    properties: Optional[str] = None
    description: Optional[str] = None
    srcTrg: Optional[str] = None
    duration: Optional[int] = None
    agentMode: Optional[str] = None
    orchestration: Optional[str] = None
    @root_validator(pre=True)
    def check_condition(cls, values):
        if values.get('condition') == "":
            values['condition'] = {}
        return values

class ProcessDefinition(BaseModel):
    processDefinitionName: str
    processDefinitionId: str
    description: Optional[str] = None
    data: Optional[List[ProcessData]] = []
    roles: Optional[List[ProcessRole]] = []
    activities: Optional[List[ProcessActivity]] = []
    subProcesses: Optional[List[SubProcess]] = []
    sequences: Optional[List[ProcessSequence]] = []
    gateways: Optional[List[ProcessGateway]] = []

    def is_starting_activity(self, activity_id: str) -> bool:
        """
        Check if the given activity is the starting activity by verifying there's no previous activity.

        Args:
            activity_id (str): The ID of the activity to check.

        Returns:
            bool: True if it's the starting activity, False otherwise.
        """
        start_event = next((event for event in self.gateways if event.type == "startEvent"), None)
        if not start_event:
            return False

        for sequence in self.sequences:
            if sequence.source == start_event.id and sequence.target == activity_id:
                return True
        return False

    def find_initial_activity(self) -> Optional[ProcessActivity]:
        """
        Finds and returns the initial activity of the process, which is the one with no incoming sequences.

        Returns:
            Optional[Activity]: The initial activity if found, None otherwise.
        """
        start_event = next((event for event in self.gateways if event.type == "startEvent"), None)
        # Find the sequence with "start_event" as the source
        start_sequence = next((seq for seq in self.sequences if start_event.id in seq.source), None)
        
        if start_sequence:
            # Find the activity that matches the target of the start sequence
            return next((activity for activity in self.activities if activity.id == start_sequence.target), None)
        
        return None
    
    def find_prev_activity(self, current_activity_id: str) -> Optional[ProcessActivity]:
        for sequence in self.sequences:
            if sequence.target == current_activity_id:
                activity = self.find_activity_by_id(sequence.source)
                if activity:
                    return activity
                else:
                    gateway = self.find_gateway_by_id(sequence.source)
                    if gateway:
                        for sequence in self.sequences:
                            if sequence.target == gateway.id:
                                return self.find_prev_activity(sequence.source)
        return None
    
    def find_prev_activities(self, activity_id, prev_activities=None, visited=None):
        if prev_activities is None:
            prev_activities = []
        if visited is None:
            visited = set()

        if activity_id in visited:
            return prev_activities

        visited.add(activity_id)

        # 현재 액티비티 또는 게이트웨이 찾기
        current = self.find_activity_by_id(activity_id)
        if current is None:
            current = self.find_gateway_by_id(activity_id)
            if current is None:
                return prev_activities

        # 현재 노드로 들어오는 모든 시퀀스 찾기
        incoming_sequences = [seq for seq in self.sequences if seq.target == activity_id]
        
        for sequence in incoming_sequences:
            source_id = sequence.source
            
            # 소스가 액티비티인 경우
            source_activity = self.find_activity_by_id(source_id)
            if source_activity and source_id not in visited:
                if source_activity not in prev_activities:
                    prev_activities.append(source_activity)
                self.find_prev_activities(source_id, prev_activities, visited)
                continue
            
            # 소스가 게이트웨이인 경우
            source_gateway = self.find_gateway_by_id(source_id)
            if source_gateway and source_id not in visited:
                self.find_prev_activities(source_id, prev_activities, visited)

        return prev_activities
    
    
    # ---------- helpers: subprocess 판별/조회 ----------
    def is_subprocess(self, node) -> bool:
        return getattr(node, "type", None) in ("subProcess", "subprocess", "SubProcess")

    def find_sub_process_by_id(self, node_id: str):
        # activities 컬렉션 안에서만 SubProcess를 찾는다고 가정
        for a in self.activities:
            if getattr(a, "id", None) == node_id and self.is_subprocess(a):
                return a
        return None


    # ---------- 기존 함수 전면 교체(덮어쓰기) ----------

    def find_attached_activity(self, event_id: str) -> Optional[ProcessActivity]:
        for activity in self.activities:
            if getattr(activity, "attachedEvents", None):
                for attached_event in activity.attachedEvents:
                    if attached_event == event_id:
                        return activity
        return None

    def process_attached_events(self, activity, next_items, include_events=False, visited=None):
        """
        boundary(attached) 이벤트 처리:
        - SubProcess: 내부 진입 없이 '노드만' next_items에 추가
        - Activity: 노드만 next_items에 추가 (필요 시 그 액티비티의 attachedEvents는 재귀 처리)
        - Gateway는 존재할 수 없으므로 무시 (방어적 체크만)
        """
        if not hasattr(activity, "attachedEvents") or not activity.attachedEvents:
            return

        for attach_id in activity.attachedEvents:
            if visited is not None and attach_id in visited:
                continue

            # SubProcess boundary
            attach_sub = self.find_sub_process_by_id(attach_id)
            if attach_sub:
                if attach_sub not in next_items:
                    next_items.append(attach_sub)
                # 내부 진입 금지
                continue

            # Activity boundary
            attach_act = self.find_activity_by_id(attach_id)
            if attach_act:
                if attach_act not in next_items:
                    next_items.append(attach_act)
                # 그 액티비티에 또 boundary가 있으면 재귀 허용(내부 진입 아님)
                if hasattr(attach_act, "attachedEvents") and attach_act.attachedEvents:
                    self.process_attached_events(attach_act, next_items, include_events, visited)
                continue

            # 방어: 게이트웨이는 attachedEvent로 올 수 없음 → 무시
            # gw = self.find_gateway_by_id(attach_id)
            # if gw:
            #     # print(f"[WARN] Ignored gateway '{attach_id}' in attachedEvents.")
            #     continue

    def find_next_through_gateway(self, node_id: str, next_items: List, include_events: bool, visited: set):
        """
        그래프를 확장해 '모든 다음 작업 노드(액티비티/서브프로세스/이벤트)'를 수집한다.

        정책:
        - Gateway: 결과에 추가하지 않고 확장만 수행
        * eventBasedGateway: 직접 연결된 '이벤트'만 결과에 추가하고 거기서 중단
        * 그 외 게이트웨이: 모든 분기 계속 확장
        - Activity: 결과에 추가 후 boundary 처리, 그리고 뒤로 계속 확장
        - SubProcess: 결과에 추가(내부 미진입) + boundary 처리, 그리고 부모 레벨에서 뒤로 계속 확장
        """
        if node_id in visited:
            return
        visited.add(node_id)

        outgoing_sequences = [seq for seq in self.sequences if seq.source == node_id]

        for sequence in outgoing_sequences:
            target_id = sequence.target

            target_sub = self.find_sub_process_by_id(target_id)
            if target_sub:
                if target_sub not in next_items:
                    next_items.append(target_sub)
                self.process_attached_events(target_sub, next_items, include_events, visited)
                self.find_next_through_gateway(target_sub.id, next_items, include_events, visited)
                continue

            target_activity = self.find_activity_by_id(target_id)
            if target_activity:
                if target_activity not in next_items:
                    next_items.append(target_activity)
                self.process_attached_events(target_activity, next_items, include_events, visited)
                self.find_next_through_gateway(target_activity.id, next_items, include_events, visited)
                continue

            target_gateway = self.find_gateway_by_id(target_id)
            if target_gateway:
                for seq2 in self.sequences:
                    if seq2.source == target_gateway.id:
                        ev = self.find_event_by_id(seq2.target)
                        if ev and include_events and ev not in next_items:
                            next_items.append(ev)
                if not any(self.find_event_by_id(seq2.target) for seq2 in self.sequences if seq2.source == target_gateway.id):
                    self.find_next_through_gateway(target_gateway.id, next_items, include_events, visited)
                continue


    def find_next_item(self, current_item_id: str) -> Union[ProcessActivity, ProcessGateway]:
        for sequence in self.sequences:
            if sequence.source == current_item_id:
                source_id = sequence.target

                source_sub = self.find_sub_process_by_id(source_id)
                if source_sub:
                    return source_sub

                source_activity = self.find_activity_by_id(source_id)
                if source_activity:
                    return source_activity

                source_gateway = self.find_gateway_by_id(source_id)
                if source_gateway:
                    return source_gateway
        return None

    def find_next_activities(self, current_activity_id: str, include_events: bool = True):
        """
        현재 액티비티에서 도달 가능한 '다음 작업 후보'를 반환.

        정책:
        - Gateway는 결과에 절대 포함하지 않음(확장 전용).
        * eventBasedGateway: find_event_by_id로 잡히는 이벤트만 결과에 포함
        * 그 외 게이트웨이: 모든 분기 확장
        - Activity/SubProcess는 결과에 포함.
        - attachedEvents는 동일 레벨로만 추가(게이트웨이 불가).
        """
        results: List = []
        visited: set = set()

        stack: List[str] = []
        for seq in self.sequences:
            if seq.source == current_activity_id:
                stack.append(seq.target)

        while stack:
            node_id = stack.pop()

            sub = self.find_sub_process_by_id(node_id)
            if sub:
                if sub not in results:
                    results.append(sub)
                self.process_attached_events(sub, results, include_events, visited)
                self.find_next_through_gateway(sub.id, results, include_events, visited)
                continue

            act = self.find_activity_by_id(node_id)
            if act:
                if act not in results:
                    results.append(act)
                self.process_attached_events(act, results, include_events, visited)
                self.find_next_through_gateway(act.id, results, include_events, visited)
                continue

            gw = self.find_gateway_by_id(node_id)
            if gw:
                has_event = False
                for seq2 in self.sequences:
                    if seq2.source == gw.id:
                        ev = self.find_event_by_id(seq2.target)
                        if ev and include_events and ev not in results:
                            results.append(ev)
                            has_event = True
                if not has_event:
                    for seq2 in self.sequences:
                        if seq2.source == gw.id:
                            stack.append(seq2.target)
                continue
        return results



    def find_next_sub_process(self, current_activity_id: str) -> Optional[SubProcess]:
        for sequence in self.sequences:
            if sequence.source == current_activity_id:
                source_id = sequence.target
                source_sub_process = self.find_sub_process_by_id(source_id)
                if source_sub_process:
                    return source_sub_process
        return None
    
    def find_end_activity(self) -> Optional[ProcessActivity]:
        """
        Finds and returns the end activity of the process, which is the one with no outgoing sequences.

        Returns:
            Optional[Activity]: The initial activity if found, None otherwise.
        """
        # Find the sequence with "end_event" as the source
        end_sequence = next((seq for seq in self.sequences if "end_event" in seq.target.lower()), None)
        
        if end_sequence:
            # Find the activity that matches the target of the start sequence
            return next((activity for activity in self.activities if activity.id == end_sequence.source), None)
        
        return None

    def find_activity_by_id(self, activity_id: str) -> Optional[ProcessActivity]:
        for activity in self.activities:
            if activity.id == activity_id:
                return activity
        return None
    
    def find_sub_process_by_id(self, sub_process_id: str) -> Optional[SubProcess]:
        for sub_process in self.subProcesses:
            if sub_process.id == sub_process_id:
                return sub_process
        return None
    
    def find_gateway_by_id(self, gateway_id: str) -> Optional[ProcessGateway]:
        for gateway in self.gateways:
            if gateway.id == gateway_id:
                return gateway
        return None
    
    def find_event_by_id(self, event_id: str) -> Optional[ProcessGateway]:
        for gateway in self.gateways:
            if gateway.id == event_id and "event" in gateway.type:
                return gateway
        return None


    def find_immediate_prev_activities(self, activity_id: str) -> List[ProcessActivity]:
        """
        현재 액티비티의 바로 이전 액티비티들을 찾습니다.
        게이트웨이를 통과하는 경우 게이트웨이 이전의 액티비티를 찾습니다.

        Args:
            activity_id (str): 현재 액티비티의 ID

        Returns:
            List[ProcessActivity]: 바로 이전 액티비티들의 목록
        """
        prev_activities = []
        visited = set()  # 순환 참조 방지를 위한 방문 체크
        
        def find_prev_through_gateway(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            
            # 현재 노드로 들어오는 시퀀스 찾기
            incoming = [seq for seq in self.sequences if seq.target == node_id]
            
            for seq in incoming:
                source_id = seq.source
                
                # 시작 이벤트는 건너뛰기
                if "start_event" in source_id.lower():
                    continue
                
                # 소스가 액티비티인 경우
                source_activity = self.find_activity_by_id(source_id)
                if source_activity:
                    if source_activity not in prev_activities:
                        prev_activities.append(source_activity)
                    continue
                
                # 소스가 게이트웨이인 경우
                source_gateway = self.find_gateway_by_id(source_id)
                if source_gateway:
                    # 게이트웨이로 들어오는 시퀀스 찾기
                    gateway_incoming = [seq for seq in self.sequences if seq.target == source_gateway.id]
                    for gw_seq in gateway_incoming:
                        gw_source = self.find_activity_by_id(gw_seq.source)
                        if gw_source and gw_source not in prev_activities:
                            prev_activities.append(gw_source)
        
        # 현재 액티비티로 들어오는 시퀀스 찾기
        current_incoming = [seq for seq in self.sequences if seq.target == activity_id]
        
        for sequence in current_incoming:
            source_id = sequence.source
            
            # 소스가 액티비티인 경우
            source_activity = self.find_activity_by_id(source_id)
            if source_activity:
                if source_activity not in prev_activities:
                    prev_activities.append(source_activity)
                continue
            
            # 소스가 게이트웨이인 경우
            source_gateway = self.find_gateway_by_id(source_id)
            if source_gateway:
                # 게이트웨이로 들어오는 시퀀스 찾기
                gateway_incoming = [seq for seq in self.sequences if seq.target == source_gateway.id]
                for gw_seq in gateway_incoming:
                    gw_source = self.find_activity_by_id(gw_seq.source)
                    if gw_source and gw_source not in prev_activities:
                        prev_activities.append(gw_source)
        
        return prev_activities

def load_process_definition(definition_json: dict) -> ProcessDefinition:
    # Events를 게이트웨이 리스트에 추가
    if 'events' in definition_json:
        if 'gateways' not in definition_json:
            definition_json['gateways'] = []
        for event in definition_json['events']:
            gateway = {
                'id': event['id'],
                'name': event.get('name', ''),
                'role': event.get('role', ''),
                'type': event['type'],
                'process': event.get('process', ''),
                'condition': event.get('condition', {}),
                'properties': event.get('properties', '{}'),
                'description': event.get('description', ''),
                'srcTrg': None
            }
            definition_json['gateways'].append(gateway)

    process_def = ProcessDefinition(**definition_json)
    
    # srcTrg 설정
    for sequence in process_def.sequences:
        # 타겟 액티비티 찾기
        target_activity = next((activity for activity in process_def.activities if activity.id == sequence.target), None)
        if target_activity:
            target_activity.srcTrg = sequence.source
            continue
            
        # 타겟 게이트웨이 찾기
        target_gateway = next((gateway for gateway in process_def.gateways if gateway.id == sequence.target), None)
        if target_gateway:
            target_gateway.srcTrg = sequence.source
            
    return process_def

# Example usage
if __name__ == "__main__":
    json_str = '{"processDefinitionName": "Example Process", "processDefinitionId": "example_process", "description": "제 프로세스 설명", "data": [{"name": "example data", "description": "example data description", "type": "Text"}], "roles": [{"name": "example role", "resolutionRule": "example rule"}], "activities": [{"name": "example activity", "id": "example_activity", "type": "ScriptActivity", "description": "activity description", "instruction": "activity instruction", "role": "example role", "inputData": [{"name": "example input data"}], "outputData": [{"name": "example output data"}], "checkpoints":["checkpoint 1"], "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\n\\nsmtp = smtplib.SMTP(\'smtp.gmail.com\', 587)\\nsmtp.starttls()\\nsmtp.login(\'jinyoungj@gmail.com\', \'raqw nmmn xuuc bsyi\')\\n\\nmsg = MIMEMultipart()\\nmsg[\'Subject\'] = \'Test mail\'\\nmsg.attach(MIMEText(\'This is a test mail.\'))\\n\\nsmtp.sendmail(\'jinyoungj@gmail.com\', \'ohsy818@gmail.com\', msg.as_string())\\nsmtp.quit()"}], "sequences": [{"source": "activity_id_1", "target": "activity_id_2"}]}'
    process_definition = load_process_definition(json_str)
    print(process_definition.processDefinitionName)

    current_dir = Path(__file__).parent

    from code_executor import execute_python_code

    for activity in process_definition.activities:
        if activity.type == "ScriptActivity":
            print(activity)
            execute_python_code(activity.pythonCode, current_dir)
            output = execute_python_code(activity.pythonCode, current_dir)
            print(output)
    # End Generation Here

class UIDefinition(BaseModel):
    id: str
    html: str
    proc_def_id: Optional[str] = None
    activity_id: Optional[str] = None
    fields_json: Optional[List[Dict[str, Any]]] = None