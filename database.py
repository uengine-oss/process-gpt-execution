import os
from supabase import create_client, Client
from pydantic import BaseModel
from typing import Any, Dict, List

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

url = "http://127.0.0.1:54321"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
supabase: Client = create_client(url, key)


"""

drop table proc_def;

drop table proc_inst;

create table proc_def (
  id text primary key,
  name text,
  definition jsonb
);


create table proc_inst (
  id text primary key,
  name text,
  current_activity_ids text array,
  def_id text,
  data jsonb,
  role_bindings jsonb
);


"""

data, count = supabase.table('proc_inst').upsert(
    {'id': '1', 'name': 'testproc', 
     'data': {'application_field': 'sw dev'}, 
     'role_bindings': {'applicant':'jyjang@uengine.org'}, 
     'current_activity_ids':['registration'],
     'def_id': 'company-enterance'
    }
).execute()

supabase.table('proc_def').upsert(
    {'id': 'company-enterance', 'name': 'def', 'definition': 
"""

    {
        "processDefinitionName": "Company Application Process",
        "processDefinitionId": "company-enterance",
        "description": "예제 프로세스 설명",
        "data": [
            {
                "name": "application_field",
                "description": "application area",
                "type": "Text"
            }
        ],
        "roles": [
            {
                "name": "applicant",
                "resolutionRule": "initiator"
            }
        ],
        "activities": [
            {
                "name": "start",
                "id": "start",
                "type": "StartEvent",
                "description": "start event",
                "role": "applicant"
            },
            {
                "name": "registration",
                "id": "registration",
                "type": "UserActivity",
                "description": "activity description",
                "instruction": "activity instruction",
                "role": "applicant",
                "outputData": [
                    {
                        "application_field": {"mandatory": true}
                    }
                ],
        
                "checkpoints": [
                    "checkpoint 1"
                ]
                
            },
            {
                "name": "conguraturate",
                "id": "congurate",
                "type": "ScriptActivity",
                "description": "activity description",
                "instruction": "activity instruction",
                "role": "system",
                "inputData": [
                    {
                        "application_field": {"type": "data"}
                    }
                ],
                
                "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\nimport os\\n\\napplication_field = os.getenv('APPLICATION_FIELD')\\n\\nsmtp = smtplib.SMTP('smtp.gmail.com', 587)\\nsmtp.starttls()\\nsmtp.login('jinyoungj@gmail.com', 'raqw nmmn xuuc bsyi')\\n\\nmsg = MIMEMultipart()\\nmsg['Subject'] = 'Application Process Update'\\nmsg.attach(MIMEText(f'The application field is: {application_field}'))\\n\\nsmtp.sendmail('jinyoungj@gmail.com', 'jyjang@uengine.org', msg.as_string())\\nsmtp.quit()"
            },
            
            {
                "name": "another email",
                "id": "nextMail",
                "type": "ScriptActivity",
                "description": "activity description",
                "instruction": "activity instruction",
                "role": "system",
                "inputData": [
                    {
                        "application_field": {"type": "data"}
                    }
                ],
                
                "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\nimport os\\n\\napplication_field = os.getenv('APPLICATION_FIELD')\\n\\nsmtp = smtplib.SMTP('smtp.gmail.com', 587)\\nsmtp.starttls()\\nsmtp.login('jinyoungj@gmail.com', 'raqw nmmn xuuc bsyi')\\n\\nmsg = MIMEMultipart()\\nmsg['Subject'] = 'Final Notification'\\nmsg.attach(MIMEText(f'The application field is: {application_field}'))\\n\\nsmtp.sendmail('jinyoungj@gmail.com', 'jyjang@uengine.org', msg.as_string())\\nsmtp.quit()"
            }
        ],
        "sequences": [
            {
                "source": "start",
                "target": "registration"
            },
            {
                "source": "registration",
                "target": "congurate"
            },
            {
                "source": "congurate",
                "target": "nextMail"
            }
        ]
    }


"""
}
).execute()


# data, count = supabase.table('countries').upsert({'id': 1, 'name': 'Austrailia'}).execute()

response = supabase.table('proc_inst').select("*").execute()
print(response)

data, count = supabase.table('proc_inst').update(
    {'data': {'application_field': 'marketing'}}
).eq(
    'id', 1
).execute()

# following is not allowed:
# data, count = supabase.table('proc_inst').update( {'data["application_field"]: 'marketing'}).eq('id', 1).execute()


response = supabase.table('proc_inst').select("*").execute()
print(response)

def fetch_process_definition(def_id):
    """
    Fetches the process definition from the 'proc_def' table based on the given definition ID.
    
    Args:
        def_id (str): The ID of the process definition to fetch.
    
    Returns:
        dict: The process definition as a JSON object if found, else None.
    """
    response = supabase.table('proc_def').select('definition').eq('id', def_id).execute()
    
    # Check if the response contains data
    if response.data:
        # Assuming the first match is the desired one since ID should be unique
        process_definition = response.data[0].get('definition', None)
        return process_definition
    else:
        return None



class ProcessInstance(BaseModel):
    id: str
    def_id: str
    data: Dict[str, Any]
    role_bindings: Dict[str, str]
    current_activity_ids: List[str]  # Changed part

def fetch_process_instance(instance_id: int) -> ProcessInstance:
    """
    Fetches the process instance from the 'proc_inst' table based on the given instance ID.
    
    Args:
        instance_id (int): The ID of the process instance to fetch.
    
    Returns:
        dict: The process instance as a JSON object if found, else None.
    """
    response = supabase.table('proc_inst').select("*").eq('id', instance_id).execute()
    
    # Check if the response contains data
    if response.data:
        # Assuming the first match is the desired one since ID should be unique
        process_instance = ProcessInstance(**response.data[0])
        return process_instance
    else:
        return None

def upsert_process_instance(process_instance: ProcessInstance) -> bool:
    """
    Upserts the process instance in the 'proc_inst' table based on the given instance ID with the new process instance data.
    If the instance does not exist, it creates a new one; otherwise, it updates the existing instance.
    
    Args:
        instance_id (int): The ID of the process instance to upsert.
        process_instance (ProcessInstance): The new process instance data to upsert.
    
    Returns:
        bool: True if the upsert was successful, else False.
    """
    response = supabase.table('proc_inst').upsert({
        'id': process_instance.id,
        'def_id': process_instance.def_id,
        'data': process_instance.data,
        'role_bindings': process_instance.role_bindings,
        'current_activity_ids': process_instance.current_activity_ids
    }).execute()
    
    # Check if the upsert was successful and convert response.data to a ProcessInstance object
    if response.data:
        updated_process_instance = ProcessInstance(**response.data[0])
        return True, updated_process_instance
    else:
        return False, None
