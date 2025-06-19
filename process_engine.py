from fastapi import Request, HTTPException
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from pydantic import BaseModel
from datetime import datetime, timedelta

from database import WorkItem, fetch_process_instance, fetch_process_definition, fetch_organization_chart, fetch_user_info, upsert_workitem, fetch_workitem_by_proc_inst_and_activity, insert_process_instance, fetch_agent_by_id, fetch_todolist_by_proc_inst_id, upsert_chat_message
from process_definition import ProcessDefinition
from a2a_agent_client import process_a2a_message

import uuid
import json
import pytz
import requests

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
parser = CustomJsonOutputParser()


async def handle_submit(request: Request):
    try:
        json_data = await request.json()
        input = json_data.get('input')

        return await submit_workitem(input)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
    

async def create_process_instance(process_definition, process_instance_id, user_email):
    try:
        process_definition_id = process_definition.processDefinitionId
        process_instance_data = {
            "proc_inst_id": process_instance_id,
            "proc_inst_name": process_definition.processDefinitionName,
            "proc_def_id": process_definition_id,
            "current_user_ids": [user_email],
            "status": "NEW"
        }
        insert_process_instance(process_instance_data)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
    

async def submit_workitem(input: dict):

    process_instance_id = input.get('process_instance_id')
    process_definition_id = input.get('process_definition_id')
    activity_id = input.get('activity_id')
    
    process_definition_data = fetch_process_definition(process_definition_id)
    process_definition = ProcessDefinition(**process_definition_data)

    if activity_id is None:
        activity_id = process_definition.find_initial_activity().id
    activity = process_definition.find_activity_by_id(activity_id)
    prev_activities = process_definition.find_prev_activities(activity.id, [])

    role_bindings = input.get('role_mappings')
    output = input.get('form_values')

    user_email = None
    
    if role_bindings:
        for role in role_bindings:
            endpoint = role.get('endpoint')
            if endpoint == 'external_customer':
                user_email = 'external_customer'
                break

    if not user_email:
        user_email = input.get('email')
        
    workitem = None
    if process_instance_id != "new":
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_id, activity_id)
    else:
        process_instance_id = f"{process_definition_id.lower()}.{str(uuid.uuid4())}"
        await create_process_instance(process_definition, process_instance_id, user_email)

    now = datetime.now(pytz.timezone('Asia/Seoul'))
    start_date = now.isoformat()
    due_date = now + timedelta(days=activity.duration) if activity.duration else None
    due_date = due_date.isoformat() if due_date else None
    
    if workitem:
        workitem_data = workitem.dict()
        workitem_data['status'] = 'SUBMITTED'
        workitem_data['output'] = output
        workitem_data['user_id'] = user_email
        workitem_data['start_date'] = workitem_data['start_date'].isoformat()
        workitem_data['due_date'] = workitem_data['due_date'].isoformat()
        workitem_data['retry'] = 0
        workitem_data['consumer'] = None
    else:
        workitem_data = {
            "id": str(uuid.uuid4()),
            "user_id": user_email,
            "proc_inst_id": process_instance_id,
            "proc_def_id": process_definition_id,
            "activity_id": activity_id,
            "activity_name": activity.name,
            "start_date": start_date,
            "due_date": due_date,
            "status": 'SUBMITTED',
            "assignees": role_bindings,
            "reference_ids": prev_activities,
            "duration": activity.duration,
            "tool": activity.tool,
            "output": output,
            "retry": 0,
            "consumer": None
        }
        
    upsert_workitem(workitem_data)
    message_data = {
        "description": f"{activity.name} 업무를 시작합니다.",
    }
    upsert_chat_message(process_instance_id, message_data, True, input.get('tenant_id'), False)
    return workitem_data


def process_output(workitem, tenant_id):
    try:
        if workitem["output"] is None or workitem["output"] == {}:
            return
        # url = f"http://localhost:8005/process/database"
        url = f"http://memento-service:8005/process/database"
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


############## start of handle workitem with agent #############
agent_request_prompt = PromptTemplate.from_template(
"""
Please create a request text for the agent using the information provided below. 

Previous Output: {previous_output}
Workitem: {workitem}

Generate a clear and concise request text that the agent can understand and process.
The text should include all relevant context from the previous output and workitem information.
"""
)

output_processing_prompt = PromptTemplate.from_template(
    """
Please convert the agent's response to the required output format.

Agent Response: {agent_response}

Convert the agent's response into the following JSON format:
{{
    "agent_result": {{
        "html": "<table>...</table> with <thead>, <tbody>, and clickable <a href> links for the 'link' column",
        "table_data": [
            {{
                "name": "...",
                "rating": ...,
                "reviews": ...,
                "link": "..."
            }},
            ...
        ]
    }}
}}

Requirements:
- The "html" field must contain a valid HTML table as a string. Use <thead> and <tbody> tags properly.
- In the HTML, render the "link" field as a clickable anchor tag (<a href="...">...</a>).
- The "table_data" array must use **snake_case keys only** (e.g., "name", "rating", "reviews", "link").
- Output must be a single JSON object with exactly one top-level key: "agent_result".
- Input data may not always be about accommodations, so apply formatting logic generically without assuming field semantics.

IMPORTANT: Return ONLY valid JSON without any comments, explanations, or additional text.
If a field value is not available from the agent response, use an empty string "" instead of adding comments.
"""
)

def check_agent_workitem(user_id: str, is_name: bool = False, process_definition: ProcessDefinition = None):
    try:
        id = None
        if is_name:
            roles = process_definition.roles
            for role in roles:
                if role.name == user_id:
                    id = role.endpoint
                    break
        else:
            id = user_id
        
        if isinstance(id, list):
            for agent_id in id:
                agent = fetch_agent_by_id(agent_id)
                if agent:
                    return agent
            return None
        else:
            agent = fetch_agent_by_id(id)
            return agent
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

preprocessing_chain = (
    agent_request_prompt | model
)

output_processing_chain = (
    output_processing_prompt | model | parser
)

async def generate_agent_request_text(prev_workitem, current_workitem, tenant_id):
    """Step 1: LLM에게 output과 workitem 정보를 주고 에이전트 요청 텍스트 생성"""
    try:
        worklist = fetch_todolist_by_proc_inst_id(prev_workitem["proc_inst_id"], tenant_id)
        previous_output = {}
        if worklist:
            for todo_item in worklist:
                if hasattr(todo_item, 'output') and todo_item.output is not None:
                    previous_output[todo_item.activity_id] = todo_item.output

        preprocessing_input = {
            "previous_output": previous_output,
            "workitem": current_workitem.dict() if current_workitem else {}
        }
        response = await preprocessing_chain.ainvoke(preprocessing_input)
        
        request_text = response.content if hasattr(response, 'content') else str(response)
        
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 전송할 메시지를 생성하였습니다..."
        }, tenant_id)
        
        return request_text
    except Exception as e:
        print(f"[ERROR] Failed to generate agent request text: {str(e)}")
        raise e

async def send_request_to_agent(request_text, agent_url, current_workitem, proc_inst_id):
    """Step 2: 생성된 텍스트를 A2A에 전송"""
    try:
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 메시지를 전송 중 입니다..."
        }, current_workitem.tenant_id)
        
        agent_response = await process_a2a_message(
            text=request_text, 
            agent_url=agent_url,
            task_id=current_workitem.id if current_workitem else None,
            context_id=proc_inst_id,
            stream=False
        )
        
        if hasattr(agent_response, 'content'):
            agent_response = agent_response.content
        elif not isinstance(agent_response, str):
            agent_response = str(agent_response)
        
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 응답을 받았습니다..."
        }, current_workitem.tenant_id)
        
        return agent_response
    except Exception as e:
        print(f"[ERROR] Failed to send request to agent: {str(e)}")
        raise e

async def process_agent_response(agent_response, current_workitem):
    """Step 3: A2A 응답을 LLM에게 전달하여 JSON 형식으로 반환"""
    try:
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 받은 응답을 기반으로 결과를 처리 중 입니다..."
        }, current_workitem.tenant_id)
        
        output_processing_input = {
            "agent_response": agent_response
        }
        final_output = await output_processing_chain.ainvoke(output_processing_input)
        
        if hasattr(final_output, 'content'):
            final_output = final_output.content
        elif not isinstance(final_output, (dict, str)):
            final_output = str(final_output)
        
        if isinstance(final_output, str):
            lines = final_output.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped_line = line.strip()
                if not stripped_line.startswith('//') and not stripped_line.startswith('#') and stripped_line:
                    cleaned_lines.append(line)
            final_output = '\n'.join(cleaned_lines)
            
            try:
                import json
                final_output = json.loads(final_output)
            except json.JSONDecodeError as e:
                print(f"[WARNING] JSON parsing failed, treating as string: {str(e)}")
                final_output = {}
        
        if isinstance(final_output, dict):
            if 'agent_result' in final_output:
                final_output = final_output['agent_result']
        
        upsert_workitem({
            "id": current_workitem.id,
            "status": "SUBMITTED",
            "consumer": None,
            "output": final_output,
            "log": f"Agent processing completed successfully"
        }, current_workitem.tenant_id)
        
        return final_output
    except Exception as e:
        print(f"[ERROR] Failed to process agent response: {str(e)}")
        raise e

async def handle_workitem_with_agent(prev_workitem, activity, agent):
    try:
        if agent:
            proc_inst_id = prev_workitem["proc_inst_id"]
            tenant_id = prev_workitem["tenant_id"]
            activity_id = activity.id
            agent_url = agent.get("url")
            
            current_workitem = fetch_workitem_by_proc_inst_and_activity(proc_inst_id, activity_id, tenant_id)
            if not current_workitem:
                print(f"[ERROR] Workitem not found for activity {activity_id}")
                return None
            
            # Step 1: 에이전트 요청 텍스트 생성
            request_text = None
            for attempt in range(3):
                try:
                    upsert_workitem({
                        "id": current_workitem.id,
                        "log": f"에이전트가 업무를 시작합니다..."
                    }, tenant_id)
                    request_text = await generate_agent_request_text(prev_workitem, current_workitem, tenant_id)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[ERROR] Failed to generate request text after 3 attempts: {str(e)}")
                        return None
                    print(f"[WARNING] Request text generation failed, retrying... (attempt {attempt + 1}/3)")
            
            # Step 2: A2A에 요청 전송
            agent_response = None
            for attempt in range(3):
                try:
                    agent_response = await send_request_to_agent(request_text, agent_url, current_workitem, proc_inst_id)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[ERROR] Failed to send request to agent after 3 attempts: {str(e)}")
                        return None
                    print(f"[WARNING] Agent request failed, retrying... (attempt {attempt + 1}/3)")
            
            # Step 3: 에이전트 응답 처리
            final_output = None
            for attempt in range(3):
                try:
                    final_output = await process_agent_response(agent_response, current_workitem)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[ERROR] Failed to process agent response after 3 attempts: {str(e)}")
                        return None
                    print(f"[WARNING] Agent response processing failed, retrying... (attempt {attempt + 1}/3)")
            
            message_data = {
                "name": f"[A2A 호출] {agent.get('name')} 검색 결과",
                "content": f"{agent.get('name')} 검색 결과입니다.",
                "jsonData": final_output.get("table_data"),
                "html": final_output.get("html")
            }
            upsert_chat_message(proc_inst_id, message_data, False, tenant_id, True)
            return final_output
            
    except Exception as e:
        if 'current_workitem' in locals() and current_workitem:
            upsert_workitem({
                "id": current_workitem.id,
                "status": "DONE",
                "consumer": None,
                "log": f"Agent processing failed for activity {activity.id}: {str(e)}"
            }, tenant_id)
            print(f"[ERROR] Agent processing failed for activity {activity.id}: {str(e)}")

        print(f"[ERROR] Agent processing failed for activity {activity.id}: {str(e)}")
        return None
############## end of handle workitem with agent #############

############# start of role binding #############
role_binding_prompt = PromptTemplate.from_template(
    """
Now, we will create a system that recommends role performers at each stage when our employees start the process. Please refer to the resolution rule of the role in the process definition provided and our organization chart to find and return the best person for each role. If there is no suitable person, select yourself.

- Roles in Process Definition: {roles}

- Organization Chart: {organizationChart}

- My Email: {myEmail}

If the agent is a role performer, enter the agent ID in userId.

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
        roles = input.get('roles')
        my_email = input.get('email')
        organizationChart = fetch_organization_chart()
        
        if not organizationChart:
            organizationChart = "There is no organization chart"
        
        chain_input = {
            "roles": roles,
            "organizationChart": organizationChart,
            "myEmail": my_email
        }
        
        return role_binding_chain.invoke(chain_input)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def add_routes_to_app(app) :
    app.add_api_route("/complete", handle_submit, methods=["POST"])
    app.add_api_route("/vision-complete", handle_submit, methods=["POST"])
    app.add_api_route("/role-binding", combine_input_with_role_binding, methods=["POST"])


"""
# try this: 

"""