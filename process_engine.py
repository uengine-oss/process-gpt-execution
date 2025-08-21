from fastapi import Request, HTTPException
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from datetime import datetime, timedelta

from database import fetch_process_definition, fetch_organization_chart, upsert_workitem, fetch_workitem_by_proc_inst_and_activity, insert_process_instance, fetch_workitem_by_id, upsert_process_definition, fetch_assignee_info
from process_definition import load_process_definition

import traceback
import uuid
import json
import pytz

# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-4o", streaming=True)

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
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
    

async def create_process_instance(process_definition, process_instance_id, is_initiate=False, role_bindings=[], project_id=None):
    try:
        participants = []
        if isinstance(role_bindings, list) and len(role_bindings) > 0:
            for role_binding in role_bindings:
                if isinstance(role_binding.get('endpoint'), list):
                    for endpoint in role_binding.get('endpoint'):
                        participants.append(endpoint)
                else:
                    participants.append(role_binding.get('endpoint'))
        
        
        process_definition_id = process_definition.processDefinitionId
        process_instance_data = {
            "proc_inst_id": process_instance_id,
            "proc_inst_name": process_definition.processDefinitionName,
            "proc_def_id": process_definition_id,
            "project_id": project_id,
            "participants": participants,
            "status": "RUNNING" if is_initiate else "NEW",
            "role_bindings": role_bindings,
            "start_date": datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
        }
        insert_process_instance(process_instance_data)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
    

async def submit_workitem(input: dict):
    process_instance_id = input.get('process_instance_id')
    process_definition_id = input.get('process_definition_id')
    activity_id = input.get('activity_id')
    project_id = input.get('project_id')
    
    process_definition_json = fetch_process_definition(process_definition_id)
    process_definition = load_process_definition(process_definition_json)

    if activity_id is None:
        activity_id = process_definition.find_initial_activity().id
    activity = process_definition.find_activity_by_id(activity_id)
    if activity is not None:
        prev_activities = process_definition.find_prev_activities(activity.id, [])
    else:
        prev_activities = []

    role_bindings = input.get('role_mappings')
    output = input.get('form_values')

    user_email = None
    
    if role_bindings:
        roles = process_definition_json.get('roles')
        for role_binding in role_bindings:
            endpoint = role_binding.get('endpoint')
            if roles and isinstance(roles, list) and len(roles) > 0:
                for role in roles:
                    if role.get('name') == role_binding.get('name') and (role.get('default') is None or role.get('default') == ''):
                        role['default'] = endpoint

            if endpoint == 'external_customer':
                user_email = 'external_customer'
                break

        process_definition_json['roles'] = roles
        definition_data = {
            'id': process_definition_id,
            'definition': process_definition_json
        }
        upsert_process_definition(definition_data)

    if not user_email:
        user_email = input.get('email')
        
    workitem = None
    if process_instance_id != "new":
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_id, activity_id)
    else:
        process_instance_id = f"{process_definition_id.lower()}.{str(uuid.uuid4())}"
        await create_process_instance(process_definition, process_instance_id, False, role_bindings, project_id)

    now = datetime.now(pytz.timezone('Asia/Seoul'))
    start_date = now.isoformat()
    due_date = now + timedelta(days=activity.duration) if activity.duration else None
    due_date = due_date.isoformat() if due_date else None
    
    user_info = None
    if user_email:
        user_info = fetch_assignee_info(user_email)
    
    if workitem:
        workitem_data = workitem.model_dump()
        workitem_data['status'] = 'SUBMITTED'
        workitem_data['output'] = output
        workitem_data['user_id'] = user_info.get('id')
        workitem_data['username'] = user_info.get('name')
        workitem_data['start_date'] = workitem_data['start_date'].isoformat()
        workitem_data['due_date'] = workitem_data['due_date'].isoformat()
        workitem_data['retry'] = 0
        workitem_data['consumer'] = None
    else:
        workitem_data = {
            "id": str(uuid.uuid4()),
            "user_id": user_info.get('id'),
            "username": user_info.get('name'),
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
            "consumer": None,
            "description": activity.description,
            "project_id": project_id
        }
        
    upsert_workitem(workitem_data)
    return workitem_data

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

async def handle_role_binding(request: Request):
    try:
        result = None
        role_bindings = []
        
        json_data = await request.json()
        input = json_data.get('input')
        role_mappings = input.get('roles')
        my_email = input.get('email')
        
        process_definition_id = input.get('proc_def_id')
        
        if process_definition_id:
            process_definition = fetch_process_definition(process_definition_id)
            roles = process_definition.get('roles')
            if roles and isinstance(roles, list) and len(roles) > 0:
                for role in roles:
                    if role.get('default') is not None and role.get('default') != '':
                        role_binding = {
                            "roleName": role.get('name'),
                            "userId": role.get('default')
                        }
                        role_bindings.append(role_binding)
                if len(role_bindings) > 0:
                    result = json.dumps(role_bindings)
    
        if result is None:
            organizationChart = fetch_organization_chart()
                
            if not organizationChart:
                organizationChart = "There is no organization chart"
            
            chain_input = {
                "roles": role_mappings,
                "organizationChart": organizationChart,
                "myEmail": my_email
            }

            result = role_binding_chain.invoke(chain_input)

        if process_definition_id and process_definition and len(role_bindings) == 0:
            role_bindings = json.loads(result).get('roleBindings')
            roles = process_definition.get('roles')
            if roles and isinstance(roles, list) and len(roles) > 0:
                for role in roles:
                    for role_binding in role_bindings:
                        if role.get('name') == role_binding.get('roleName'):
                            role['default'] = role_binding.get('userId')
                            break
            process_definition['roles'] = roles
            definition_data = {
                'id': process_definition_id,
                'definition': process_definition
            }
            upsert_process_definition(definition_data)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
############# end of role binding #############


############# start of initiate #############
async def initiate_workitem(input: dict):
    process_definition_id = input.get('process_definition_id')
    process_definition_json = fetch_process_definition(process_definition_id)
    process_definition = load_process_definition(process_definition_json)
    project_id = input.get('project_id')
    
    activity = process_definition.find_initial_activity()
    if activity is not None:
        activity_id = activity.id
        prev_activities = process_definition.find_prev_activities(activity_id, [])
    else:
        raise HTTPException(status_code=400, detail="No initial activity found")

    user_email = input.get('email')
    if user_email is None:
        roles = process_definition_json.get('roles')
        if roles and isinstance(roles, list) and len(roles) > 0:
            for role in roles:
                if role.get('name') == activity.role:
                    user_email = role.get('default')
                    if user_email is None:
                        user_email = role.get('endpoint')
                    break
        if user_email is None:
            raise HTTPException(status_code=400, detail="No default user email found")
        
    process_instance_id = f"{process_definition_id.lower()}.{str(uuid.uuid4())}"
    await create_process_instance(process_definition, process_instance_id, True, [{"name": activity.role, "endpoint": user_email}])

    now = datetime.now(pytz.timezone('Asia/Seoul'))
    start_date = now.isoformat()
    due_date = now + timedelta(days=activity.duration) if activity.duration else None
    due_date = due_date.isoformat() if due_date else None
    
    tenant_id = input.get('tenant_id')
    
    workitem_data = {
        "id": str(uuid.uuid4()),
        "user_id": user_email,
        "proc_inst_id": process_instance_id,
        "proc_def_id": process_definition_id,
        "activity_id": activity_id,
        "activity_name": activity.name,
        "start_date": start_date,
        "due_date": due_date,
        "status": 'TODO',
        "assignees": None,
        "reference_ids": prev_activities,
        "duration": activity.duration,
        "tool": activity.tool,
        "output": None,
        "retry": 0,
        "consumer": None,
        "description": activity.description,
        "project_id": project_id
    }

    upsert_workitem(workitem_data)
    return workitem_data

async def handle_initiate(request: Request):
    try:
        json_data = await request.json()
        input = json_data.get('input')

        return await initiate_workitem(input)

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
    
############# end of initiate #############

############# start of feedback #############
feedback_prompt = PromptTemplate.from_template("""
You are a helpful assistant that can provide feedback on a process.
The user needs feedback because the process execution result is not satisfactory. Please analyze the activity task result and provide feedback on areas that need improvement.

Process Definition: {process_definition}
Need to get feedback for the following activity: {activity_id}

Executed Activity Task's Result: {activity_result}

Please write the feedback in Korean.

result should be in this JSON format:
{{
    "feedback": [
        "feedback1",
        "feedback2",
        "feedback3"
    ]
}}
"""
)

feedback_chain = (
    feedback_prompt | model | parser
)

async def handle_get_feedback(request: Request):
    try:
        body = await request.json()
        
        process_definition_id = body.get('processDefinitionId')
        process_definition_json = fetch_process_definition(process_definition_id)
        process_definition = load_process_definition(process_definition_json)
        
        activity_id = body.get('activityId')
        task_id = body.get('taskId')
        workitem = fetch_workitem_by_id(task_id)
        
        chain_input = {
            "process_definition": process_definition,
            "activity_id": activity_id,
            "activity_result": workitem
        }
        result = feedback_chain.invoke(chain_input)
        feedback = result.get('feedback')
        return feedback

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e

diff_prompt = PromptTemplate.from_template("""
Please analyze the activity and feedback to provide a detailed comparison of the modifiable properties.

Activities: {activities}
Gateways: {gateways}
Feedback: {feedback}
Feedback Result: {feedback_result}

Based on the feedback, provide the before and after values for the following modifiable properties:
- inputData: Data fields that the activity receives as input
- checkpoints: Verification points that need to be completed
- description: Description of what the activity does
- instruction: Instructions for completing the activity

Output format (must be wrapped in ```json and ``` markers. Do not include any other text):
{{
    "modifications": {{
        "inputData": {{
            "before": [
                {{
                    "key": "input data field key",
                    "name": "input data field name (Korean)"
                }}
            ],
            "after": [
                {{
                    "key": "input data field key",
                    "name": "input data field name (Korean)"
                }}
            ],
            "changed": true/false
        }},
        "checkpoints": {{
            "before": ["original checkpoints"],
            "after": ["modified checkpoints"],
            "changed": true/false
        }},
        "description": {{
            "before": "original description",
            "after": "modified description",
            "changed": true/false
        }},
        "instruction": {{
            "before": "original instruction",
            "after": "modified instruction",
            "changed": true/false
        }}
    }},
    "summary": "Brief summary of the key changes made based on feedback"
}}
"""
)

diff_chain = (
    diff_prompt | model | parser
)


async def handle_get_feedback_diff(request: Request):
    try:
        body = await request.json()
        
        task_id = body.get('taskId')
        workitem = fetch_workitem_by_id(task_id)
        process_definition_id = workitem.proc_def_id
        process_definition_json = fetch_process_definition(process_definition_id)
        process_definition = load_process_definition(process_definition_json)
        
        activity_id = workitem.activity_id
        activity = process_definition.find_activity_by_id(activity_id)
        if activity is None:
            raise HTTPException(status_code=400, detail="No activity found")
        
        activities = [ activity.model_dump() ]
        gateways = []
        next_item = process_definition.find_next_item(activity_id)
        if 'task' not in next_item.type:
            gateways.append(next_item.model_dump())
        else:
            activities.append(next_item.model_dump())

        chain_input = {
            "activities": activities,
            "gateways": gateways,
            "feedback": workitem.temp_feedback,
            "feedback_result": workitem.log
        }
        result = diff_chain.invoke(chain_input)
        return result

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e)) from e
############# end of feedback ##############


def add_routes_to_app(app) :
    app.add_api_route("/complete", handle_submit, methods=["POST"])
    app.add_api_route("/vision-complete", handle_submit, methods=["POST"])
    app.add_api_route("/role-binding", handle_role_binding, methods=["POST"])
    app.add_api_route("/initiate", handle_initiate, methods=["POST"])
    app.add_api_route("/get-feedback", handle_get_feedback, methods=["POST"])
    app.add_api_route("/get-feedback-diff", handle_get_feedback_diff, methods=["POST"])

"""
# try this: 

"""