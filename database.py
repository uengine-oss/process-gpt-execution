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

app = FastAPI()

# supabase: Client = None
# db_config = {}

url = "http://127.0.0.1:54321"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
supabase: Client = create_client(url, key)

db_config = {
    'dbname': 'postgres',
    'user': 'postgres',
    'password': 'postgres',
    'host': '127.0.0.1',
    'port': '54322'
}

async def update_db_settings(request: Request):
    global supabase, db_config
    data = await request.json()
    data = data['data']
    
    url = data['url']
    secret = data['secret']
    supabase = create_client(url, secret)
    
    db_config = data['dbConfig']
    
    return {"message": "Settings updated successfully"}

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

def fetch_all_process_definitions():
    try:
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
drop table configuration;

create table configuration (
  key text primary key,
  value jsonb
);

insert into configuration (key, value)
values ('proc_map', null)

drop table todolist;

create table todolist (
    id uuid primary key,
    user_id text,
    proc_inst_id text,
    proc_def_id text,
    activity_id text,
    start_date timestamp,
    end_date timestamp,
    status text,
    description text
);

drop table public.users;

create table public.users (
    id uuid not null primary key,
    username text null,
    profile text null,
    email text null
);
-- inserts a row into public.users
create or replace function public.handle_new_user() 
returns trigger as $$
begin
    insert into public.users (id, email)
    values (new.id, new.email);
      return new;
end;
$$ language plpgsql security definer;

-- trigger the function every time a user is created
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();


drop table organization;

create table organization (
  id bigint generated by default as identity,
  messages jsonb,
  organization_chart text
);


drop table proc_def;

create table proc_def (
  id text primary key,
  name text,
  definition jsonb,
  bpmn text
);

drop table proc_inst;


create table proc_inst (
    id text primary key,
    user_ids text[],
    messages jsonb
);
==>
create table vacation_request(
  proc_inst_id text primary key,
  proc_inst_name text,
  current_activity_ids text array,
  current_user_ids text array,
  role_bindings jsonb
  
  -- 해당 프로세스 정의의 프로세스 변수 선언들을 필드로
  reason text, -- 휴가 신청사유
  start_date date, -- 휴가 시작일
  return_date date -- 휴가 복귀일

)

create table
  public.chats (
    uuid text not null,
    id text not null,
    messages jsonb null,
    constraint chats_pkey primary key (uuid)
  ) tablespace pg_default;

create table
  public.calendar (
    uid text not null,
    data jsonb null,
    constraint calendar_pkey primary key (uid)
  ) tablespace pg_default;

create table
  public.chat_rooms (
    id text not null,
    participants jsonb not null,
    message jsonb null,
    name text null,
    constraint chat_rooms_pkey primary key (id)
  ) tablespace pg_default;
  
"""


def fetch_process_definition(def_id):
    """
    Fetches the process definition from the 'proc_def' table based on the given definition ID.
    
    Args:
        def_id (str): The ID of the process definition to fetch.
    
    Returns:
        dict: The process definition as a JSON object if found, else None.
    """
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
    role_bindings: Dict[str, str] = {}
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
        status = 'done'
    else:
        status = 'running'
    process_instance_data = process_instance.dict(exclude={'process_definition'})  # Convert Pydantic model to dict
    process_instance_data = convert_decimal(process_instance_data)

    try:
        # Fetch existing columns from the table
        existing_columns = fetch_table_columns(process_name.lower())

        # Filter out non-existing columns
        filtered_data = {key: value for key, value in process_instance_data.items() if key in existing_columns}

        # Upsert the filtered data into the table
        supabase.table('proc_inst').upsert({
            'id': process_instance.proc_inst_id,
            'name': process_instance.proc_inst_name,
            'user_ids': process_instance.current_user_ids,
            'status': status
        }).execute()

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
    response = supabase.table("configuration").select("*").eq('key', 'organization').execute()
    
    # Check if the response contains data
    if response.data:
        # Assuming the first match is the desired one since ID should be unique
        value = response.data[0].get('value', None)
        organization_chart = value.get('chart', None)
        return organization_chart
    else:
        return None

def fetch_workitem_by_proc_inst_and_activity(proc_inst_id: str, activity_id: str) -> Optional[WorkItem]:
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
        activity = process_definition.find_activity_by_id(process_result_data['nextActivities'][0]['nextActivityId'])


        workitem = WorkItem(
            id=f"{str(uuid.uuid4())}",
            proc_inst_id=prcess_instance_data['proc_inst_id'],
            proc_def_id=process_result_data['processDefinitionId'],
            activity_id=process_result_data['completedActivities'][0]['completedActivityId'],
            activity_name=activity.name,
            user_id=process_result_data['completedActivities'][0]['completedUserEmail'],
            status=process_result_data['completedActivities'][0]['result'],
            start_date=datetime.now(),
            end_date=datetime.now()
        )

    try:
        workitem_dict = workitem.dict()
        workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
        workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
        supabase.table('todolist').upsert(workitem_dict).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

        
def upsert_next_workitem(prcess_instance_data, process_result_data, process_definition)->WorkItem: 
    if not process_result_data['nextActivities']:
        return None
    if process_result_data['nextActivities'][0]['nextActivityId'] == "END_PROCESS" or process_result_data['nextActivities'][0]['nextActivityId'] == "endEvent":
        return None
    
    workitem = fetch_workitem_by_proc_inst_and_activity(prcess_instance_data['proc_inst_id'], process_result_data['nextActivities'][0]['nextActivityId'])
    if workitem:
        workitem.status = process_result_data['nextActivities'][0]['result']
        workitem.end_date = datetime.now()
    else:
        #process_definition = load_process_definition(fetch_process_definition(process_result_data['processDefinitionId'])) #TODO caching 필요.
        activity = process_definition.find_activity_by_id(process_result_data['nextActivities'][0]['nextActivityId'])

        workitem = WorkItem(
            id=f"{str(uuid.uuid4())}",
            proc_inst_id=prcess_instance_data['proc_inst_id'],
            proc_def_id=process_result_data['processDefinitionId'].lower(),
            activity_id=activity.id, #process_result_data['nextActivities'][0]['nextActivityId'],
            activity_name=activity.name,  #TODO name과 id 둘다 있어야 함. 
            user_id=process_result_data['nextActivities'][0]['nextUserEmail'],
            status=process_result_data['nextActivities'][0]['result'],
            start_date=datetime.now(),
            tool = activity.tool
        )
    try:
        workitem_dict = workitem.dict()
        workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
        workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
        supabase.table('todolist').upsert(workitem_dict).execute()

        return workitem
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
        