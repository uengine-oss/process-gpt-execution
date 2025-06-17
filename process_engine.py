from fastapi import Request, HTTPException
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from pydantic import BaseModel
from datetime import datetime, timedelta

from database import WorkItem, fetch_process_instance, fetch_process_definition, fetch_organization_chart, fetch_user_info, upsert_workitem, fetch_workitem_by_proc_inst_and_activity, insert_process_instance
from process_definition import ProcessDefinition
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
    return workitem_data


def process_output(workitem, tenant_id):
    try:
        if workitem["output"] is None or workitem["output"] == {}:
            return
        url = f"http://localhost:8005/process/database"
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
############# end of role binding #############


def add_routes_to_app(app) :
    app.add_api_route("/complete", handle_submit, methods=["POST"])
    app.add_api_route("/vision-complete", handle_submit, methods=["POST"])
    app.add_api_route("/role-binding", combine_input_with_role_binding, methods=["POST"])


"""
# try this: 

"""