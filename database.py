import os
from supabase import create_client, Client
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uuid
from process_definition import ProcessDefinition, load_process_definition
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

url = "http://127.0.0.1:54321"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
supabase: Client = create_client(url, key)




# Database connection parameters - replace these with your actual database parameters
db_config = {
    'dbname': 'postgres',
    'user': 'postgres',
    'password': 'postgres',
    'host': '127.0.0.1',
    'port': '54322'
}


def execute_sql(sql_query):
    """
    Connects to a PostgreSQL database and executes the given SQL query.
    
    Args:
        sql_query (str): The SQL query to execute.
        
    Returns:
        list: A list of dictionaries representing the rows returned by the query.
    """
    
    try:
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        # Execute the SQL query
        cursor.execute(sql_query)
        
        # If the query was a SELECT statement, fetch the results
        if sql_query.strip().upper().startswith("SELECT"):
            result = cursor.fetchall()
        else:
            # Commit the transaction if the query modified the database
            connection.commit()
            result = "Table Created"
        
        return result
    
    except Exception as e:
        return(f"An error occurred while executing the SQL query: {e}")
    
    finally:
        # Close the cursor and connection to clean up

        if connection:
            connection.close()



def fetch_all_process_definition_ids():
    try:
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        # Execute the SQL query to fetch all process definition ids
        cursor.execute("SELECT id FROM proc_def")
        
        # Fetch all rows
        rows = cursor.fetchall()
        
        # Extract the ids from the rows
        process_definition_ids = [row['id'] for row in rows]
        
        return process_definition_ids
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching process definition ids: {e}")
    
    finally:
        # Close the cursor and connection to clean up
        if connection:
            connection.close()

def generate_create_statement_for_table(table_name):
    """
    Generates a CREATE TABLE statement for the given table name by fetching its current schema.
    
    Args:
        table_name (str): The name of the table for which to generate the CREATE statement.
        
    Returns:
        str: A CREATE TABLE statement as a string, or an error message if the operation fails.
    """
    
    try:
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor()
        
        # Fetch the table schema
        cursor.execute(f"SELECT column_name, data_type, character_maximum_length FROM information_schema.columns WHERE table_name = '{table_name}'")
        columns = cursor.fetchall()
        
        if not columns:
            return f"No existing table"
        
        # Generate the CREATE TABLE statement
        create_statement = f"CREATE TABLE {table_name} (\n"
        for column in columns:
            column_name, data_type, max_length = column
            column_def = f"{column_name} {data_type}"
            if max_length:
                column_def += f"({max_length})"
            create_statement += f"    {column_def},\n"
        
        # Remove the last comma and add the closing parenthesis
        create_statement = create_statement.rstrip(',\n') + "\n);"
        
        return create_statement
    
    except Exception as e:
        return(f"An error occurred while generating CREATE statement for table {table_name}: {e}")
    
    finally:
        # Close the cursor and connection to clean up
        if connection:
            connection.close()



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
==>
create table vacation_request(
  proc_inst_id text primary key,
  proc_inst_name text,
  current_activity_ids text array,
  role_bindings jsonb
  
  -- 해당 프로세스 정의의 프로세스 변수 선언들을 필드로
  reason text, -- 휴가 신청사유
  start_date date, -- 휴가 시작일
  return_date date -- 휴가 복귀일

)

"""


supabase.table('proc_def').upsert(
    {'id': 'company_entrance', 'name': 'def', 'definition': 
"""

    {
        "processDefinitionName": "Company Application Process",
        "processDefinitionId": "company_entrance",
        "description": "예제 프로세스 설명",
        "data": [
            {
                "name": "application_field",
                "description": "application area",
                "type": "Text"
            },
            {
                "name": "applicant_name",
                "description": "name of the applicant",
                "type": "Text"
            },
            {
                "name": "applicant_birthyear",
                "description": "birth year of the applicant",
                "type": "Number"
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
                    "지원서가 꼭 첨부되어야 하고 첨부된 사진이 실사이미지가 아니면 탈락입니다."
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
                "target": "congurate",
                "condition": "지원서의 지원자의 사진이 실사 이미지가 아니면 탈락"
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

supabase.table('proc_def').upsert(
    {'id': 'vacation_request', 'name': 'Vacation Process', 'definition': 
"""
    {
        "processDefinitionName": "Vacation Request Process",
        "processDefinitionId": "vacation_request",
        "description": "Vacation processing process",
        "data": [
            {
                "name": "total_vacation_days",
                "description": "Total vacation days requested",
                "type": "Number"
            },
            {
                "name": "total_vacation_days_remains",
                "description": "Total remaining vacation days",
                "type": "Number",
                "dataSource": {
                    "type": "database",
                    "sql": "SELECT SUM(additional_vacation_days) - SUM(total_vacation_days) AS result FROM (SELECT COALESCE(SUM(additional_vacation_days), 0) AS additional_vacation_days, 0 AS total_vacation_days FROM vacation_addition UNION ALL SELECT 0 AS additional_vacation_days, COALESCE(SUM(total_vacation_days), 0) AS total_vacation_days FROM vacation_request) AS vacation_summary;"
                }
            },
            {
                "name": "vacation_start_date",
                "description": "Vacation start date",
                "type": "Date"
            },
            {
                "name": "vacation_return_date",
                "description": "Vacation return date",
                "type": "Date"
            },
            {
                "name": "vacation_reason",
                "description": "Reason for vacation",
                "type": "Text"
            },
            {
                "name": "manager_approval",
                "description": "Manager approval status",
                "type": "Boolean"
            }
        ],
        "roles": [
            {
                "name": "applicant",
                "resolutionRule": "initiator"
            },
            {
                "name": "manager",
                "resolutionRule": "specific"
            }
        ],
        "activities": [
            {
                "name": "vacation_application",
                "id": "vacation_application",
                "type": "UserActivity",
                "description": "Vacation application",
                "role": "applicant",
                "outputData": [
                    {
                        "total_vacation_days": {"mandatory": true},
                        "vacation_start_date": {"mandatory": true},
                        "vacation_return_date": {"mandatory": true},
                        "vacation_reason": {"mandatory": true}
                    }
                ]
            },
            {
                "name": "manager_approval",
                "id": "manager_approval",
                "type": "UserActivity",
                "description": "Manager approval",
                "role": "manager",
                "outputData": [
                     {   "manager_approval": {"mandatory": true}
                    }
                ]
            },
            {
                "name": "vacation_approval_email",
                "id": "vacation_approval_email",
                "type": "ScriptActivity",
                "description": "Vacation approval email dispatch",
                "role": "system",
                "inputData": [
                    {
                        "manager_approval": {"mandatory": true}
                    }
                ],
                "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\n\\nmsg = MIMEMultipart()\\nmsg['Subject'] = 'Vacation Approval'\\nmsg.attach(MIMEText('Your vacation request has been approved.'))\\n\\n# Add your SMTP settings here"
            },
            {
                "name": "vacation_rejection_email",
                "id": "vacation_rejection_email",
                "type": "ScriptActivity",
                "description": "Vacation rejection email dispatch",
                "role": "system",
                "inputData": [
                    {
                        "manager_approval": {"mandatory": true}
                    }
                ],
                "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\n\\nmsg = MIMEMultipart()\\nmsg['Subject'] = 'Vacation Rejection'\\nmsg.attach(MIMEText('Your vacation request has been rejected.'))\\n\\n# Add your SMTP settings here"
            }
        ],
        "sequences": [
            {
                "source": "vacation_application",
                "target": "manager_approval",
                "condition": "total_vacation_days_remains > total_vacation_days"
            },
            {
                "source": "manager_approval",
                "target": "vacation_approval_email",
                "condition": "manager_approval == true"
            },
            {
                "source": "manager_approval",
                "target": "vacation_rejection_email",
                "condition": "manager_approval == false"
            }
        ]
    }
"""
}
).execute()

supabase.table('proc_def').upsert(
    {'id': 'vacation_addition', 'name': 'Vacation Addition Process', 'definition': 
"""
    {
        "processDefinitionName": "Vacation Addition Process",
        "processDefinitionId": "vacation_addition",
        "description": "Process for adding additional vacation days",
        "data": [
            {
                "name": "additional_vacation_days",
                "description": "Number of additional vacation days",
                "type": "Number"
            },
            {
                "name": "approval_status",
                "description": "Approval status of the vacation addition request",
                "type": "Boolean"
            }
        ],
        "roles": [
            {
                "name": "employee",
                "resolutionRule": "initiator"
            },
            {
                "name": "manager",
                "resolutionRule": "specific"
            }
        ],
        "activities": [
            {
                "name": "register_additional_days",
                "id": "register_additional_days",
                "type": "UserActivity",
                "description": "Register additional vacation days",
                "role": "employee",
                "outputData": [
                    {
                        "additional_vacation_days": {"mandatory": true}
                    }
                ]
            },
            {
                "name": "approval",
                "id": "approval",
                "type": "UserActivity",
                "description": "Approval of additional vacation days",
                "role": "manager",
                "outputData": [
                    {
                        "approval_status": {"mandatory": true}
                    }
                ]
            }
        ],
        "sequences": [
            {
                "source": "register_additional_days",
                "target": "approval"
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
    proc_inst_id: str
    proc_inst_name: str
    role_bindings: Dict[str, str] = {}
    current_activity_ids: List[str] = []
    process_definition: ProcessDefinition = None  # Add a reference to ProcessDefinition

    class Config:
        extra = "allow"

    def __init__(self, **data):
        super().__init__(**data)
        def_id = self.get_def_id()
        self.process_definition = load_process_definition(fetch_process_definition(def_id))  # Load ProcessDefinition

    def get_def_id(self):
        # inst_id 예시: "company_entrance.123e4567-e89b-12d3-a456-426614174000"
        # 여기서 "company_entrance"가 프로세스 정의 ID입니다.
        return self.proc_inst_id.split(".")[0]

    def get_data(self):
        # Return all process variable values as a map
        variable_map = {}
        for variable in self.process_definition.data:
            variable_name = variable.name
            variable_map[variable_name] = getattr(self, variable_name, None)
        return variable_map
    
def fetch_and_apply_system_data_sources(process_instance: ProcessInstance) -> None:
    # 프로세스 정의에서 데이터스가 'system'인 변수를 처리
    for variable in process_instance.process_definition.data:
        if variable.dataSource and variable.dataSource.type == 'database':
            sql_query = variable.dataSource.sql
            if sql_query:
                # SQL리 실행
                result = execute_sql(sql_query)
                if result:
                    #리 결과를 프로세스 인스턴스 데이터에 추가
                    setattr(process_instance, variable.name, result[0]['result'])

    return process_instance

def fetch_process_instance(full_id: str) -> Optional[ProcessInstance]:
    process_name = full_id.split('.')[0]  # Extract only the process definition name

    if not full_id:
        raise HTTPException(status_code=404, detail="Instance Id should be provided")

    response = supabase.table(process_name).select("*").eq('proc_inst_id', full_id).execute()
    
    if response.data:
        process_instance_data = response.data[0]
        # Apply system data sources
        process_instance = ProcessInstance(**process_instance_data)
        process_instance = fetch_and_apply_system_data_sources(process_instance)
        # Convert the dictionary to a ProcessInstance object
        return process_instance
    else:
        return None

def upsert_process_instance(process_instance: ProcessInstance) -> (bool, ProcessInstance):
    process_name = process_instance.proc_inst_id.split('.')[0]  # 프로세스 정의명만 추출
    process_instance_data = process_instance.dict(exclude={'process_definition'})  # Pydantic 모을 dict로 변환
    response = supabase.table(process_name).upsert(process_instance_data).execute()

    success = bool(response.data)
    return success, process_instance
