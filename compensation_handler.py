from langchain.prompts import PromptTemplate
from langchain.output_parsers.json import SimpleJsonOutputParser
from llm_factory import create_llm
from datetime import datetime, timedelta
import json

from database import fetch_events_by_proc_inst_id, fetch_events_by_proc_inst_id_until_activity, upsert_workitem, fetch_user_info_by_uid
from database import WorkItem

# ChatOpenAI 객체 생성
model = create_llm(model="gpt-4o", streaming=True)

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
parser = CustomJsonOutputParser()


compensation_prompt = PromptTemplate.from_template(
"""
You are a Reversal Request Generator Agent.
Your sole task is to generate an **undo (compensation) request** for a given event action log.

Inputs:
Original Request Event Logs:
{event_logs}
User Input Query:
{user_input_query}


Rules:
1. If the action is SQL (INSERT, UPDATE, DELETE):
   - Generate reverse SQL using before_state if available.
   - If before_state is not available, generate a natural language reversal based on the user input.
2. If the action is email, file, or agent response:
   - Generate a natural language reversal based on the user input.
3. If nothing to reverse, return "NO_REVERSE".


result should be in this JSON format:
{{
    "compensation_handling": "<reverse action query or NO_REVERSE>"
}}
""")

compensation_chain = (
    compensation_prompt | model | parser
)


async def handle_compensation(workitem, new_workitem):
    try:
        if workitem is None:
            raise Exception("Workitem is None")
        
        # 현재 액티비티까지의 워크아이템 이벤트만 가져옴
        events = fetch_events_by_proc_inst_id_until_activity(
            workitem.proc_def_id,
            workitem.proc_inst_id,
            workitem.activity_id,
            workitem.tenant_id
        )
        
        if len(events) == 0:
            return
        
        event_logs = []
        for event in events:
            crew_type = event.get('crew_type')
            if crew_type == 'action':
                event_data = event.get('data')
                if event_data and event_data != {} and 'query' in event_data:
                    tool_name = event_data.get('tool_name')
                    if tool_name != 'mem0' and tool_name != 'memento' and tool_name != 'human_asked':
                        event_logs.append({
                            "timestamp": event.get('timestamp'),
                            "log_data": event_data,
                        })
            elif crew_type == 'result':
                event_data = event.get('data')
                event_logs.append({
                    "timestamp": event.get('timestamp'),
                    "log_data": event_data,
                })
        
        if len(event_logs) == 0:
            return
        
        user_input_query = workitem.query
        if user_input_query is None:
            user_input_query = ''
        
        result = await compensation_chain.ainvoke({"event_logs": event_logs, "user_input_query": user_input_query})

        compensation_handling = result.get('compensation_handling')
        if compensation_handling is None:
            return

        if compensation_handling == 'NO_REVERSE':
            return
        
        query = workitem.query
        compensation_query = f"Compensation Handling 블럭은 존재할 경우 최초 1회만 실행합니다.\n이미 실행된 Compensation Handling 블럭은 다시 실행하지 않습니다.\nCompensation Handling 블럭이 완료된 후에는 기존 Description, Instruction을 정상적으로 적용합니다.\nCompensation Handling 블럭에서는 도구 mem0, memento, human_asked(type=confirm)를 사용하지 않습니다.\n\n[Compensation Handling Start]\n{compensation_handling}\n[Compensation Handling End]"

        if query is None:
            query = compensation_query
        else:
            if '[Compensation Handling End]' not in query:
                query = f"{compensation_query}\n\n\n{query}"
            else:
                query = compensation_query + query.split('[Compensation Handling End]')[1]
        
        user_id = None
        user_name = None
        if workitem.assignees and len(workitem.assignees) > 0:
            assignee_id = workitem.assignees[0].get('endpoint')
            if isinstance(assignee_id, list):
                user_list = []
                for id in assignee_id:
                    user_info = fetch_user_info_by_uid(id)
                    if user_info:
                        user_list.append(user_info)
                user_id = ','.join([user.get('id') for user in user_list])
                user_name = ','.join([user.get('username') for user in user_list])
        else:
            user_id = workitem.user_id
            user_name = workitem.username

        upsert_workitem({
            "id": new_workitem.get('id'),
            "status": "IN_PROGRESS",
            "query": query,
            "user_id": user_id,
            "username": user_name,
            "agent_orch": "crewai-action",
            "log": "Compensation Handling..."
        })

    except Exception as e:
        print(f"[ERROR] Failed to handle compensation: {str(e)}")
        raise Exception(f"Compensation handling failed: {str(e)}") from e
