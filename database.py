import os
from supabase import create_client, Client
from pydantic import BaseModel, validator
from typing import Any, Dict, List, Optional
import uuid
from process_definition import ProcessDefinition, load_process_definition
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Request, HTTPException
from decimal import Decimal
from datetime import datetime
from contextvars import ContextVar

app = FastAPI()

db_config_var = ContextVar('db_config', default={})
supabase_client_var = ContextVar('supabase', default=None)

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

def create_default_tables():
    try:
        db_config = db_config_var.get()
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        # Load SQL from file
        sql_query = load_sql_from_file('sql.txt')
        
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
        if subdomain and "localhost" not in subdomain:
            supabase: Client = create_client('https://qivmgbtrzgnjcpyynpam.supabase.co', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpdm1nYnRyemduamNweXlucGFtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTcxNTU4ODc3NSwiZXhwIjoyMDMxMTY0Nzc1fQ.z8LIo50hs1gWcerWxx1dhjri-DMoDw9z0luba_Ap4cI')
            response = supabase.table("tenant_def").select("*").eq('id', subdomain).execute()

            if response.data:
                data = response.data[0]
                supabase: Client = create_client(data['url'], data['secret'])
                supabase_client_var.set(supabase)
                db_config = {
                    'dbname': data['dbname'],
                    'user': data['user'],
                    'password': data['pw'],
                    'host': data['host'],
                    'port': data['port']
                }
                db_config_var.set(db_config)
        else:
            supabase: Client = create_client('http://127.0.0.1:54321', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0')
            supabase_client_var.set(supabase)
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
        db_config = db_config_var.get()
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        # Execute the SQL query to fetch all process definition
        cursor.execute("SELECT definition FROM proc_def")
        
        # Fetch all rows
        rows = cursor.fetchall()
        
        # Extract the definitions from the rows
        process_definitions = [row['definition'] for row in rows]
        
        return process_definitions
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching process definitions: {e}")
    
    finally:
        # Close the cursor and connection to clean up
        if connection:
            connection.close()

def fetch_all_process_definition_ids():
    try:
        db_config = db_config_var.get()
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
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table('proc_def').select('*').eq('id', def_id.lower()).execute()
    
    # Check if the response contains data
    if response.data:
        # Assuming the first match is the desired one since ID should be unique
        process_definition = response.data[0].get('definition', None)
        return process_definition
    else:
        raise ValueError(f"No process definition found with ID {def_id}")
        

class ProcessInstance(BaseModel):
    proc_inst_id: str
    proc_inst_name: str
    role_bindings: Optional[List[Dict[str, str]]] = []
    current_activity_ids: List[str] = []
    current_user_ids: List[str] = []
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

class InstanceItem(BaseModel):
    id: str
    name: Optional[str] = None
    status: Optional[str] = None
    variables_data: Optional[str] = None
    user_ids: Optional[List[str]] = None
    
class WorkItem(BaseModel):
    id: str
    user_id: Optional[str]
    proc_inst_id: Optional[str] = None
    proc_def_id: Optional[str] = None
    activity_id: str
    activity_name: str 
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: str
    description: Optional[str] = None
    tool: Optional[str] = None
    
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
    process_name = full_id.split('.')[0]  # Extract only the process definition name

    if not full_id:
        raise HTTPException(status_code=404, detail="Instance Id should be provided")

    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
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
    process_name = process_instance.proc_inst_id.split('.')[0]  # Extract the process definition name
    if 'END_PROCESS' in process_instance.current_activity_ids or 'endEvent' in process_instance.current_activity_ids:
        process_instance.current_activity_ids = []
        status = 'COMPLETED'
    else:
        status = 'RUNNING'
    process_instance_data = process_instance.dict(exclude={'process_definition'})  # Convert Pydantic model to dict
    process_instance_data = convert_decimal(process_instance_data)

    try:
        # Fetch existing columns from the table
        existing_columns = fetch_table_columns(process_name.lower())

        # Filter out non-existing columns
        filtered_data = {key.lower(): value for key, value in process_instance_data.items() if key.lower() in existing_columns}
        
        keys_to_exclude = {'proc_inst_id', 'proc_inst_name', 'role_bindings', 'current_activity_ids', 'current_user_ids'}
        variables_data = {key: value for key, value in filtered_data.items() if key not in keys_to_exclude}
        variables_data_json = json.dumps(variables_data, ensure_ascii=False)

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        supabase.table('proc_inst').upsert({
            'id': process_instance.proc_inst_id,
            'name': process_instance.proc_inst_name,
            'user_ids': process_instance.current_user_ids,
            'status': status,
            'variables_data': variables_data_json
        }).execute()
        # Upsert the filtered data into the table
        response = supabase.table(process_name.lower()).upsert(filtered_data).execute()
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
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table("configuration").select("*").eq('key', 'organization').execute()
    
    # Check if the response contains data
    if response.data:
        # Assuming the first match is the desired one since ID should be unique
        value = response.data[0].get('value', None)
        organization_chart = value.get('chart', None)
        return organization_chart
    else:
        return None

def fetch_process_instance_list(user_id: str) -> Optional[List[InstanceItem]]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table('proc_inst').select("*").filter('user_ids', 'cs', '{' + user_id + '}').execute()
    if response.data:
        return [InstanceItem(**item) for item in response.data]
    else:
        return None

def fetch_todolist_by_user_id(user_id: str) -> Optional[List[WorkItem]]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table('todolist').select("*").eq('user_id', user_id).execute()
    if response.data:
        return [WorkItem(**item) for item in response.data]
    else:
        return None

def fetch_todolist_by_proc_inst_id(proc_inst_id: str) -> Optional[List[WorkItem]]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).execute()
    if response.data:
        return [WorkItem(**item) for item in response.data]
    else:
        return None

def fetch_workitem_by_proc_inst_and_activity(proc_inst_id: str, activity_id: str) -> Optional[WorkItem]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    
    response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('activity_id', activity_id).execute()
    if response.data:
        return WorkItem(**response.data[0])
    else:
        return None

# todolist 업데이트
def upsert_completed_workitem(prcess_instance_data, process_result_data, process_definition):
    if not process_result_data['completedActivities']:
        return
    
    if process_result_data['instanceId'] != "new":
        workitem = fetch_workitem_by_proc_inst_and_activity(prcess_instance_data['proc_inst_id'], process_result_data['completedActivities'][0]['completedActivityId'])
        workitem.status = process_result_data['completedActivities'][0]['result']
        workitem.end_date = datetime.now()
    else:
        activity = process_definition.find_activity_by_id(process_result_data['completedActivities'][0]['completedActivityId'])
        workitem = WorkItem(
            id=f"{str(uuid.uuid4())}",
            proc_inst_id=prcess_instance_data['proc_inst_id'],
            proc_def_id=process_result_data['processDefinitionId'],
            activity_id=process_result_data['completedActivities'][0]['completedActivityId'],
            activity_name=activity.name,
            user_id=process_result_data['completedActivities'][0]['completedUserEmail'],
            status=process_result_data['completedActivities'][0]['result'],
            tool=activity.tool,
            start_date=datetime.now(),
            end_date=datetime.now()
        )

    try:
        workitem_dict = workitem.dict()
        workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
        workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        supabase.table('todolist').upsert(workitem_dict).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def upsert_next_workitems(process_instance_data, process_result_data, process_definition) -> List[WorkItem]:
    workitems = []
    for activity_data in process_result_data['nextActivities']:
        if activity_data['nextActivityId'] in ["END_PROCESS", "endEvent"]:
            continue
        
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_data['proc_inst_id'], activity_data['nextActivityId'])
        if workitem:
            workitem.status = activity_data['result']
            workitem.end_date = datetime.now()
        else:
            activity = process_definition.find_activity_by_id(activity_data['nextActivityId'])
            workitem = WorkItem(
                id=str(uuid.uuid4()),
                proc_inst_id=process_instance_data['proc_inst_id'],
                proc_def_id=process_result_data['processDefinitionId'].lower(),
                activity_id=activity.id,
                activity_name=activity.name,
                user_id=activity_data['nextUserEmail'],
                status=activity_data['result'],
                start_date=datetime.now(),
                tool=activity.tool
            )
        
        try:
            workitem_dict = workitem.dict()
            workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
            workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None

            supabase = supabase_client_var.get()
            if supabase is None:
                raise Exception("Supabase client is not configured for this request")
            
            supabase.table('todolist').upsert(workitem_dict).execute()
            workitems.append(workitem)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    return workitems


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

def fetch_chat_history(chat_room_id: str) -> List[ChatItem]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    response = supabase.table("chats").select("*").eq('id', chat_room_id).execute()
    chatHistory = []
    for chat in response.data:
        chat.pop('jsonContent', None)
        chatHistory.append(ChatItem(**chat))
    return chatHistory

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
                timeStamp=datetime.now()
            )
        else:
            user_info = fetch_user_info(data["email"])
            message = ChatMessage(
                name=user_info["username"],
                role="user",
                email=data["email"],
                image="",
                content=data["command"],
                timeStamp=datetime.now()
            )
        message.timeStamp = message.timeStamp.isoformat() if message.timeStamp else None        
        chat_item = ChatItem(
            id=chat_room_id,
            uuid=str(uuid.uuid4()),
            messages=message
        )
        chat_item_dict = chat_item.dict()
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        supabase.table("chats").upsert(chat_item_dict).execute();
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


import jwt

def parse_token(request: Request) -> Dict[str, str]:
    if request.headers:
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                return payload
            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=401, detail="Token expired")
            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
        else:
            return None
    else:
        return None

def fetch_user_info(email: str) -> Dict[str, str]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    response = supabase.table("users").select("*").eq('email', email).execute()
    return response.data[0]
