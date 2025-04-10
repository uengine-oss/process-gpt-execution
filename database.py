import os
from supabase import create_client, Client
from pydantic import BaseModel, validator
from typing import Any, Dict, List, Optional
import uuid
from process_definition import ProcessDefinition, load_process_definition, UIDefinition
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Request, HTTPException
from decimal import Decimal
from datetime import datetime, timedelta
import pytz
from contextvars import ContextVar
import csv

app = FastAPI()

db_config_var = ContextVar('db_config', default={})
supabase_client_var = ContextVar('supabase', default=None)
subdomain_var = ContextVar('subdomain', default='localhost')

jwt_secret_var = ContextVar('jwt_secret', default='')
algorithm_var = ContextVar('algorithm', default='HS256')

# url = "http://127.0.0.1:54321"
# key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
# supabase: Client = create_client(url, key)

# db_config = {
#     'dbname': 'postgres',
#     'user': 'postgres',
#     'password': 'postgres',
#     'host': '127.0.0.1',
#     'port': '54322'
# }

def load_sql_from_file(file_path):
    """Load SQL commands from a text file."""
    with open(file_path, 'r', encoding='utf-8') as file:  # UTF-8 인코딩으로 파일을 열기
        return file.read()

def update_db():
    try:
        db_config = db_config_var.get()
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        # Load SQL from file
        sql_query = load_sql_from_file('update_db_sql.txt')
        
        cursor.execute(sql_query)
        connection.commit()
        
        return "Tables created successfully."
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if connection:
            connection.close()


async def update_db_settings(subdomain):
    try:
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        if not jwt_secret:
            jwt_secret = "super-secret-jwt-token-with-at-least-32-characters-long"
        jwt_secret_var.set(jwt_secret)
        
        url = os.getenv("SUPABASE_URL")
        if not url:
            url = "http://127.0.0.1:54321"
        key = os.getenv("SUPABASE_KEY")
        if not key:
            key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
        supabase: Client = create_client(url, key)
        supabase_client_var.set(supabase)
        
        subdomain_var.set(subdomain)    
        if subdomain and "localhost" not in subdomain:
            db_config = {
                'dbname': 'postgres',
                'user': 'postgres.gjdyydowgrinjjkfkwtl',
                'password': 'mhhaydZpSL7lVkfQ',
                'host': 'aws-0-ap-northeast-2.pooler.supabase.com',
                'port': '6543'
            }
            db_config_var.set(db_config)
            
        else:
            db_config = {
                'dbname': 'postgres',
                'user': 'postgres',
                'password': 'postgres',
                'host': '127.0.0.1',
                'port': '54322'
            }
            db_config_var.set(db_config)
       
    except Exception as e:
        print(f"An error occurred: {e}")

def db_client_signin(user_info: dict):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.auth.sign_in_with_password({ "email": user_info.get('email'), "password": user_info.get('password') })
        supabase.auth.set_session(response.session.access_token, response.session.refresh_token)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while signing in: {e}")

def execute_sql(sql_query):
    """
    Connects to a PostgreSQL database and executes the given SQL query.
    
    Args:
        sql_query (str): The SQL query to execute.
        
    Returns:
        list: A list of dictionaries representing the rows returned by the query.
    """
    
    try:
        db_config = db_config_var.get()
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

def fetch_all_process_definitions():
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('proc_def').select('*').eq('tenant_id', subdomain).execute()
        
        return response.data
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching process definitions: {e}")


def fetch_all_process_definition_ids():
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('proc_def').select('id').eq('tenant_id', subdomain).execute()
        
        return response.data
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching process definition ids: {e}")


def generate_create_statement_for_table(table_name):
    """
    Generates a CREATE TABLE statement for the given table name by fetching its current schema.
    
    Args:
        table_name (str): The name of the table for which to generate the CREATE statement.
        
    Returns:
        str: A CREATE TABLE statement as a string, or an error message if the operation fails.
    """
    
    try:
        db_config = db_config_var.get()
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

def fetch_process_definition(def_id):
    """
    Fetches the process definition from the 'proc_def' table based on the given definition ID.
    
    Args:
        def_id (str): The ID of the process definition to fetch.
    
    Returns:
        dict: The process definition as a JSON object if found, else None.
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
    
        subdomain = subdomain_var.get()
        response = supabase.table('proc_def').select('*').eq('id', def_id.lower()).eq('tenant_id', subdomain).execute()
        
        # Check if the response contains data
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            process_definition = response.data[0].get('definition', None)
            return process_definition
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition found with ID {def_id}: {e}")

def fetch_all_ui_definition():
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('form_def').select('*').eq('tenant_id', subdomain).execute()
        
        if response.data:
            return response.data
        else:
            return []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching UI definitions: {e}")

def fetch_ui_definition(def_id):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('form_def').select('*').eq('id', def_id.lower()).eq('tenant_id', subdomain).execute()
        
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            ui_definition = UIDefinition(**response.data[0])
            return ui_definition
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No UI definition found with ID {def_id}: {e}")

def fetch_ui_definition_by_activity_id(proc_def_id, activity_id):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('form_def').select('*').eq('proc_def_id', proc_def_id).eq('activity_id', activity_id).eq('tenant_id', subdomain).execute()
        
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            ui_definition = UIDefinition(**response.data[0])
            return ui_definition
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No UI definition found with ID {proc_def_id}: {e}")

class ProcessInstance(BaseModel):
    proc_inst_id: str
    proc_inst_name: str
    role_bindings: Optional[List[Dict[str, str]]] = []
    current_activity_ids: List[str] = []
    current_user_ids: List[str] = []
    variables_data: Optional[List[Dict[str, Any]]] = []
    process_definition: ProcessDefinition = None  # Add a reference to ProcessDefinition
    status: str = None
    tenant_id: str
    
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
    
class WorkItem(BaseModel):
    id: str
    user_id: Optional[str]
    proc_inst_id: Optional[str] = None
    proc_def_id: Optional[str] = None
    activity_id: str
    activity_name: str 
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    status: str
    description: Optional[str] = None
    tool: Optional[str] = None
    tenant_id: str
    
    @validator('start_date', 'end_date', pre=True)
    def parse_datetime(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        }

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
    try:
        if full_id == "new" or '.' not in full_id:
            return None

        if not full_id:
            raise HTTPException(status_code=404, detail="Instance Id should be provided")

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('bpm_proc_inst').select("*").eq('proc_inst_id', full_id).eq('tenant_id', subdomain).execute()
        
        if response.data:
            process_instance_data = response.data[0]

            if isinstance(process_instance_data.get('variables_data'), dict):
                process_instance_data['variables_data'] = [process_instance_data['variables_data']]
            
            process_instance = ProcessInstance(**process_instance_data)
            process_instance = fetch_and_apply_system_data_sources(process_instance)
            
            return process_instance
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def upsert_process_instance(process_instance: ProcessInstance) -> (bool, ProcessInstance):
    if 'END_PROCESS' in process_instance.current_activity_ids or 'endEvent' in process_instance.current_activity_ids or 'end_event' in process_instance.current_activity_ids or process_instance.status == 'COMPLETED':
        process_instance.current_activity_ids = []
        status = 'COMPLETED'
    else:
        status = 'RUNNING'
    process_instance_data = process_instance.dict(exclude={'process_definition'})  # Convert Pydantic model to dict
    process_instance_data = convert_decimal(process_instance_data)

    try:        
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('bpm_proc_inst').upsert({
            'proc_inst_id': process_instance.proc_inst_id,
            'proc_inst_name': process_instance.proc_inst_name,
            'current_activity_ids': process_instance.current_activity_ids,
            'current_user_ids': process_instance.current_user_ids,
            'role_bindings': process_instance.role_bindings,
            'variables_data': process_instance.variables_data,
            'status': status,
            'proc_def_id': process_instance.get_def_id(),
            'tenant_id': subdomain
        }).execute()
        success = bool(response.data)
        return success, process_instance
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_table_columns(table_name: str) -> List[str]:
    """
    Fetches the column names of a given table from the database.
    
    Args:
        table_name (str): The name of the table to fetch columns from.
    
    Returns:
        List[str]: A list of column names.
    """
    try:
        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'")
        columns = cursor.fetchall()
        return [column[0] for column in columns]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch columns for table {table_name}: {e}")
    finally:
        if connection:
            connection.close()

def convert_decimal(data):
    for key, value in data.items():
        if isinstance(value, Decimal):
            data[key] = float(value)

    return data

def fetch_organization_chart():
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table("configuration").select("*").eq('key', 'organization').eq('tenant_id', subdomain).execute()
        
        # Check if the response contains data
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            value = response.data[0].get('value', None)
            organization_chart = value.get('chart', None)
            return organization_chart
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to fetch organization chart: {e}")

def fetch_process_instance_list(user_id: str, process_definition_id: Optional[str] = None) -> Optional[List[ProcessInstance]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if process_definition_id:
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', subdomain).eq('proc_def_id', process_definition_id).filter('current_user_ids', 'cs', '{' + user_id + '}').execute()
        else:
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', subdomain).filter('current_user_ids', 'cs', '{' + user_id + '}').execute()
        
        if response.data:
            return [ProcessInstance(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_todolist_by_user_id(user_id: str) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        subdomain = subdomain_var.get()
        response = supabase.table('todolist').select("*").eq('user_id', user_id).eq('tenant_id', subdomain).execute()
        
        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_todolist_by_proc_inst_id(proc_inst_id: str) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('tenant_id', subdomain).execute()
        
        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_workitem_by_proc_inst_and_activity(proc_inst_id: str, activity_id: str) -> Optional[WorkItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('activity_id', activity_id).eq('tenant_id', subdomain).execute()
        
        if response.data:
            return WorkItem(**response.data[0])
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

# todolist 업데이트
def upsert_completed_workitem(prcess_instance_data, process_result_data, process_definition):
    try:
        if not process_result_data['completedActivities']:
            return
        
        for completed_activity in process_result_data['completedActivities']:
            workitem = fetch_workitem_by_proc_inst_and_activity(
                prcess_instance_data['proc_inst_id'], 
                completed_activity['completedActivityId']
            )
            
            if workitem:
                workitem.status = completed_activity['result']
                workitem.end_date = datetime.now(pytz.timezone('Asia/Seoul'))
                workitem.user_id = completed_activity['completedUserEmail']
            else:
                activity = process_definition.find_activity_by_id(completed_activity['completedActivityId'])
                start_date = datetime.now(pytz.timezone('Asia/Seoul'))
                due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
                subdomain = subdomain_var.get()
                workitem = WorkItem(
                    id=f"{str(uuid.uuid4())}",
                    proc_inst_id=prcess_instance_data['proc_inst_id'],
                    proc_def_id=process_result_data['processDefinitionId'].lower(),
                    activity_id=completed_activity['completedActivityId'],
                    activity_name=activity.name,
                    user_id=completed_activity['completedUserEmail'],
                    status=completed_activity['result'],
                    tool=activity.tool,
                    start_date=start_date,
                    end_date=datetime.now(pytz.timezone('Asia/Seoul')) if completed_activity['result'] == 'DONE' else None,
                    due_date=due_date,
                    tenant_id=subdomain
                )
            
            workitem_dict = workitem.dict()
            workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
            workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
            workitem_dict["due_date"] = workitem.due_date.isoformat() if workitem.due_date else None

            supabase = supabase_client_var.get()
            if supabase is None:
                raise Exception("Supabase client is not configured for this request")
            
            supabase.table('todolist').upsert(workitem_dict).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def upsert_next_workitems(process_instance_data, process_result_data, process_definition) -> List[WorkItem]:
    workitems = []
    for activity_data in process_result_data['nextActivities']:
        if activity_data['nextActivityId'] in ["END_PROCESS", "endEvent", "end_event"]:
            continue
        
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_data['proc_inst_id'], activity_data['nextActivityId'])
        
        if workitem:
            workitem.status = activity_data['result']
            workitem.end_date = datetime.now(pytz.timezone('Asia/Seoul')) if activity_data['result'] == 'DONE' else None
            workitem.user_id = activity_data['nextUserEmail']
        else:
            activity = process_definition.find_activity_by_id(activity_data['nextActivityId'])
            if activity:
                prev_activities = process_definition.find_prev_activities(activity.id, [])
                start_date = datetime.now(pytz.timezone('Asia/Seoul'))
                if prev_activities:
                    for prev_activity in prev_activities:
                        start_date = start_date + timedelta(days=prev_activity.duration)
                due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
                subdomain = subdomain_var.get()
                workitem = WorkItem(
                    id=str(uuid.uuid4()),
                    proc_inst_id=process_instance_data['proc_inst_id'],
                    proc_def_id=process_result_data['processDefinitionId'].lower(),
                    activity_id=activity.id,
                    activity_name=activity.name,
                    user_id=activity_data['nextUserEmail'],
                    status=activity_data['result'],
                    start_date=start_date,
                    due_date=due_date,
                    tool=activity.tool,
                    tenant_id=subdomain
                )
        
        try:
            if workitem:
                workitem_dict = workitem.dict()
                workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
                workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
                workitem_dict["due_date"] = workitem.due_date.isoformat() if workitem.due_date else None

                supabase = supabase_client_var.get()
                if supabase is None:
                    raise Exception("Supabase client is not configured for this request")
                
                supabase.table('todolist').upsert(workitem_dict).execute()
                workitems.append(workitem)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    return workitems

def upsert_todo_workitems(prcess_instance_data, process_result_data, process_definition):
    try:
        initial_activity = process_definition.find_initial_activity()
        next_activities = [activity for activity in process_definition.activities if activity.id != initial_activity.id]
        for activity in next_activities:
            prev_activities = process_definition.find_prev_activities(activity.id, [])
            start_date = datetime.now(pytz.timezone('Asia/Seoul'))
            if prev_activities:
                for prev_activity in prev_activities:
                    start_date = start_date + timedelta(days=prev_activity.duration)
            due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
            workitem = fetch_workitem_by_proc_inst_and_activity(prcess_instance_data['proc_inst_id'], activity.id)
            if not workitem:
                subdomain = subdomain_var.get()
                workitem = WorkItem(
                    id=f"{str(uuid.uuid4())}",
                    proc_inst_id=prcess_instance_data['proc_inst_id'],
                    proc_def_id=process_result_data['processDefinitionId'].lower(),
                    activity_id=activity.id,
                    activity_name=activity.name,
                    user_id="",
                    status="TODO",
                    tool=activity.tool,
                    start_date=start_date,
                    due_date=due_date,
                    tenant_id=subdomain
                )
                workitem_dict = workitem.dict()
                workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
                workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
                workitem_dict["due_date"] = workitem.due_date.isoformat() if workitem.due_date else None

                supabase = supabase_client_var.get()
                if supabase is None:
                    raise Exception("Supabase client is not configured for this request")
                supabase.table('todolist').upsert(workitem_dict).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

import json

class ChatMessage(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    image: Optional[str] = None
    content: Optional[str] = None
    timeStamp: Optional[datetime] = None

class ChatItem(BaseModel):
    id: str
    uuid: str
    messages: Optional[ChatMessage] = None
    tenant_id: str

def fetch_chat_history(chat_room_id: str) -> List[ChatItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        subdomain = subdomain_var.get()
        response = supabase.table("chats").select("*").eq('id', chat_room_id).eq('tenant_id', subdomain).execute()

        chatHistory = []
        for chat in response.data:
            chat.pop('jsonContent', None)
            chatHistory.append(ChatItem(**chat))
        return chatHistory
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def upsert_chat_message(chat_room_id: str, data: Any, is_system: bool) -> None:
    try:
        if is_system:
            json_data = json.loads(data)
            message = ChatMessage(
                name="system",
                role="system",
                email="system@uengine.org",
                image="",
                content=json_data["description"],
                timeStamp=datetime.now(pytz.timezone('Asia/Seoul'))
            )
        else:
            user_info = fetch_user_info(data["email"])
            message = ChatMessage(
                name=user_info["username"],
                role="user",
                email=data["email"],
                image="",
                content=data["command"],
                timeStamp=datetime.now(pytz.timezone('Asia/Seoul'))
            )

        message.timeStamp = message.timeStamp.isoformat() if message.timeStamp else None        
        subdomain = subdomain_var.get()
        chat_item = ChatItem(
            id=chat_room_id,
            uuid=str(uuid.uuid4()),
            messages=message,
            tenant_id=subdomain
        )
        chat_item_dict = chat_item.dict()

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        supabase.table("chats").upsert(chat_item_dict).execute();
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

def parse_token(request: Request) -> Dict[str, str]:
    if request.headers:
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
            try:
                jwt_secret = jwt_secret_var.get()
                algorithm = algorithm_var.get()
                payload = jwt.decode(token, jwt_secret, algorithms=[algorithm], audience='authenticated')
                
                subdomain = subdomain_var.get()
                if payload['app_metadata']['tenant_id'] != subdomain:
                    raise HTTPException(status_code=401, detail="Invalid tenant")
                
                return payload
            except ExpiredSignatureError:
                raise HTTPException(status_code=401, detail={"message": "Token expired", "status_code": 401})
            except InvalidTokenError as e:
                raise HTTPException(status_code=401, detail={"message": f"Invalid token {e}", "status_code": 401})
        else:
            raise HTTPException(status_code=401, detail={"message": "Authorization header missing", "status_code": 401})
    else:
        raise HTTPException(status_code=401, detail={"message": "Authorization header not provided", "status_code": 401})

def fetch_user_info(email: str) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        response = supabase.table("users").select("*").eq('email', email).filter('tenants', 'cs', '{' + subdomain + '}').execute()
        
        if response.data:
            return response.data[0]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore

def get_vector_store():
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured")
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", deployment="text-embedding-3-small")
    
    return SupabaseVectorStore(
        client=supabase,
        embedding=embeddings,
        table_name="documents",
        query_name="match_documents",
    )

def insert_from_csv(csv_file_path, insert_query, value_extractor):
    # Tenant ID 및 DB 설정
    tenant_id = subdomain_var.get()
    db_config = db_config_var.get()
    
    # DB 연결
    connection = psycopg2.connect(**db_config)
    cursor = connection.cursor(cursor_factory=RealDictCursor)

    # CSV 파일 읽기
    with open(csv_file_path, mode='r', encoding='utf-8') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            values = value_extractor(row, tenant_id)
            cursor.execute(insert_query, values)
    
    # 커밋 및 정리
    connection.commit()
    cursor.close()
    connection.close()

def insert_process_definition_from_csv():
    csv_file_path = './csv/proc_def.csv'
    insert_query = """
        INSERT INTO proc_def (id, name, definition, bpmn, tenant_id)
        VALUES (%s, %s, %s, %s, %s)
    """
    
    def extract_values(row, tenant_id):
        return (
            row['id'],
            row['name'],
            row['definition'],
            row['bpmn'],
            tenant_id
        )

    insert_from_csv(csv_file_path, insert_query, extract_values)

def insert_process_form_definition_from_csv():
    csv_file_path = './csv/form_def.csv'
    insert_query = """
        INSERT INTO form_def (id, html, fields_json, proc_def_id, activity_id, tenant_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    
    def extract_values(row, tenant_id):
        return (
            row['id'],
            row['html'],
            row['fields_json'],
            row['proc_def_id'],
            row['activity_id'],
            tenant_id
        )

    insert_from_csv(csv_file_path, insert_query, extract_values)


def insert_configuration_from_csv():
    csv_file_path = './csv/configuration.csv'
    insert_query = """
        INSERT INTO configuration (key, value, tenant_id)
        VALUES (%s, %s, %s)
    """
    
    def extract_values(row, tenant_id):
        return (
            row['key'],
            row['value'],
            tenant_id
        )

    insert_from_csv(csv_file_path, insert_query, extract_values)

def insert_sample_data():
    insert_configuration_from_csv()
    insert_process_definition_from_csv()
    insert_process_form_definition_from_csv()

def update_user(input):
    try:
        user_id = input.get('user_id')
        user_info = input.get('user_info')
        supabase = supabase_client_var.get()
        
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.auth.admin.update_user_by_id(user_id, user_info)
        return response

    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def create_user(user_info):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        response = supabase.auth.admin.create_user(user_info)
        return response
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
