import os
from supabase import create_client, Client
from supabase.client import AsyncClient, create_async_client
from pydantic import BaseModel, validator
from typing import Any, Dict, List, Optional
import uuid
from process_definition import ProcessDefinition, load_process_definition, UIDefinition
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException
from decimal import Decimal
from datetime import datetime, timedelta
import pytz
from contextvars import ContextVar
import csv
from dotenv import load_dotenv
import socket
# Firebase 관련 import 제거 - FCM 서비스로 분리됨
# from firebase_admin import credentials, messaging
import logging
import asyncio
from collections import defaultdict

db_config_var = ContextVar('db_config', default={})
supabase_client_var = ContextVar('supabase', default=None)
async_supabase_client_var = ContextVar('async_supabase', default=None)
subdomain_var = ContextVar('subdomain', default='localhost')

jwt_secret_var = ContextVar('jwt_secret', default='')
algorithm_var = ContextVar('algorithm', default='HS256')

# Firebase 전역 변수 제거 - FCM 서비스로 분리됨
# firebase_app = None

# Realtime 로그 설정
realtime_logger = logging.getLogger("realtime_subscriber")
if not realtime_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    realtime_logger.addHandler(handler)
    realtime_logger.setLevel(logging.INFO)

def setting_database():
    try:
        if os.getenv("ENV") != "production":
            load_dotenv(override=True)

        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        jwt_secret_var.set(jwt_secret)
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase: Client = create_client(supabase_url, supabase_key)
        supabase_client_var.set(supabase)
        
        db_config = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST"),
            "port": os.getenv("DB_PORT")
        }
        db_config_var.set(db_config)
        
    except Exception as e:
        print(f"Database configuration error: {e}")

async def setting_async_database():
    """비동기 Supabase 클라이언트 설정"""
    try:
        if os.getenv("ENV") != "production":
            load_dotenv(override=True)
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        async_supabase: AsyncClient = await create_async_client(supabase_url, supabase_key)
        async_supabase_client_var.set(async_supabase)
        
        return async_supabase
        
    except Exception as e:
        realtime_logger.error(f"비동기 Supabase 클라이언트 설정 오류: {e}")
        return None

setting_database()

async def update_tenant_id(subdomain):
    try:
        if not subdomain:
            raise Exception("Unable to configure Tenant ID.")
        subdomain_var.set(subdomain)
    except Exception as e:
        print(f"An error occurred: {e}")




def load_sql_from_file(file_path):
    """Load SQL commands from a text file."""
    with open(file_path, 'r', encoding='utf-8') as file:  # UTF-8 인코딩으로 파일을 열기
        return file.read()


# def update_db():
#     try:
#         db_config = db_config_var.get()
#         # Establish a connection to the database
#         connection = psycopg2.connect(**db_config)
#         cursor = connection.cursor(cursor_factory=RealDictCursor)
      
#         # Load SQL from file
#         sql_query = load_sql_from_file('update_db_sql.txt')
      
#         cursor.execute(sql_query)
#         connection.commit()
      
#         return "Tables created successfully."
#     except Exception as e:
#         print(f"An error occurred: {e}")
#     finally:
#         if connection:
#             connection.close()

def get_available_credits(tenant_id: str):
    try:
        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        sql = """
        SELECT
                cp.id AS purchase_id,
                cp.created_at,
                cp.expires_at,
                c.name AS credit_name,
                c.credit AS total_credit,
                COALESCE(SUM(cu.used_credit), 0) AS used_credit,
                (c.credit - COALESCE(SUM(cu.used_credit), 0)) AS remaining_credit
            FROM credit_purchase cp
            JOIN credit c ON cp.credit_id = c.id
            LEFT JOIN credit_usage cu 
                ON cu.tenant_id = cp.tenant_id
                AND cu.created_at >= cp.created_at 
                AND (cp.expires_at IS NULL OR cu.created_at <= cp.expires_at)
            WHERE cp.tenant_id = %s
            AND (cp.expires_at IS NULL OR cp.expires_at > now())
            GROUP BY cp.id, cp.created_at, cp.expires_at, c.name, c.credit
            ORDER BY cp.created_at ASC;
        """

        cursor.execute(sql, (subdomain_var.get()))
        result = cursor.fetchone()
        connection.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching available credits: {e}")
    

def get_service(category: str, model: str):
    try:
        if not category:
            return []
        
        supabase = supabase_client_var.get()
        
        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        today_date = datetime.now(pytz.timezone('Asia/Seoul'))
        
        # supabase 테이블에서 서비스 목록을 가져오는 로직
        response = supabase.table('credit_purchase') \
                    .select('credit_id', 'created_at', 'expires_at') \
                    .eq('tenant_id', subdomain_var.get()) \
                    .lte('created_at', today_date.isoformat()) \
                    .gte('expires_at', today_date.isoformat()) \
                    .order('created_at', desc=False) \
                    .execute()
        
        if not response.data:
            return []

        # 가장 오래된 row의 credit_id를 가져옴
        oldest_credit_id = response.data[0]['credit_id']

        # credit 테이블에서 feature 정보를 가져옴
        credit_response = supabase.table('credit').select('feature').eq('id', oldest_credit_id).execute()

        if not credit_response.data:
            return []

        # feature 정보에서 included_services를 추출
        feature_info = credit_response.data[0].get('feature', {})
        master_service_ids = feature_info.get('included_services', [])
        if not master_service_ids:
            return []

        # SQL 쿼리를 사용하여 service_mater와 service 테이블을 조인하여 필요한 데이터를 가져옴
        sql_query = """    
            SELECT 
                sm.id AS master_id,
                sm.name AS master_name,
                sm.version,
                s.id AS service_id,
                s.name AS service_name,
                s.category,
                sr.credit_per_unit,
                sr.unit,
                sr.dimension
            FROM 
                service_master sm
            JOIN 
                service_master_item smi ON sm.id = smi.master_id
            JOIN 
                service s ON smi.service_id = s.id
            JOIN 
                service_rate sr ON smi.service_rate_id = sr.id
            WHERE 
                sm.id = ANY(%s::uuid[])
                AND s.category = %s
                AND s.tenant_id = %s
        """
        params = [master_service_ids, category, subdomain_var.get()]

        if model is not None:
            sql_query += " AND s.name = %s"
            params.append(model)
        
        sql_query += " ORDER BY s.name;"
                
        cursor.execute(sql_query, params)
        services = cursor.fetchall()
        connection.close()

        # master_id별로 그룹핑
        grouped = defaultdict(list)
        for row in services:
            grouped[row['master_id']].append(row)

        if grouped:
            # master_id가 하나만 있다고 가정, 첫 번째만 꺼냄
            master_id, rows = next(iter(grouped.items()))
            result = {
                "service_master_id": master_id,
                "data": rows
            }
        else:
            # 데이터가 없을 때
            result = {
                "service_master_id": "",
                "data": []
            }
            
        return result
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"서비스 목록을 가져오는 중 오류가 발생했습니다: {e}")
        
def insert_usage(usage_data: dict):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise HTTPException(status_code=500, detail="Supabase 클라이언트가 요청에 대해 구성되지 않았습니다.")
        
        if not usage_data:
            raise HTTPException(status_code=400, detail="사용량 데이터가 제공되지 않았습니다.")
        
        if not usage_data.get('quantity'):
            raise HTTPException(status_code=400, detail="수량이 제공되지 않았습니다.")
        
        if not usage_data.get('model'):
            raise HTTPException(status_code=400, detail="모델이 제공되지 않았습니다.")
            
        if not usage_data.get('tenant_id'):
            usage_data['tenant_id'] = subdomain_var.get()
        
        return supabase.table('usage').insert(usage_data).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용량 삽입 중 오류가 발생했습니다: {e}")
    


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


def fetch_process_definition(def_id, tenant_id: Optional[str] = None):
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
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def').select('*').eq('id', def_id.lower()).eq('tenant_id', tenant_id).execute()
        
        # Check if the response contains data
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            process_definition = response.data[0].get('definition', None)
            return process_definition
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition found with ID {def_id}: {e}")


def upsert_process_definition(definition: dict, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        if not tenant_id:
            tenant_id = subdomain_var.get()
        
        process_definition_id = definition.get('id')
        definition['tenant_id'] = tenant_id
        
        process_definition = supabase.table('proc_def').select('*').eq('id', process_definition_id).eq('tenant_id', tenant_id).execute()
        
        if process_definition.data:
            existing_data = process_definition.data[0]
            definition['uuid'] = existing_data.get('uuid')
            definition['bpmn'] = existing_data.get('bpmn')
            definition['isdeleted'] = existing_data.get('isdeleted', False)
            return supabase.table('proc_def').upsert(definition).execute()
        else:
            definition.pop('uuid', None)
            return supabase.table('proc_def').insert(definition).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error upserting process definition with ID {process_definition_id}: {e}")


def fetch_process_definition_versions(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('tenant_id', tenant_id).execute()
        
        return response.data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition version found with ID {def_id}: {e}")


def fetch_process_definition_version_by_arcv_id(def_id, arcv_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")  


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('arcv_id', arcv_id).eq('tenant_id', tenant_id).execute()
        
        return response.data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition version found with ID {def_id} and version {arcv_id}: {e}")


def fetch_process_definition_latest_version(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('tenant_id', tenant_id).order('version', desc=True).execute()
        
        if response.data:
            return response.data[0]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition latest version found with ID {def_id}: {e}")


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


def fetch_ui_definition_by_activity_id(proc_def_id, activity_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('form_def').select('*').eq('proc_def_id', proc_def_id).eq('activity_id', activity_id).eq('tenant_id', tenant_id).execute()
        
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
    proc_inst_name: Optional[str] = None
    role_bindings: Optional[List[Dict[str, Any]]] = []
    current_activity_ids: Optional[List[str]] = []
    participants: Optional[List[str]] = []
    variables_data: Optional[List[Dict[str, Any]]] = []
    process_definition: ProcessDefinition = None  # Add a reference to ProcessDefinition
    status: str = None
    tenant_id: str
    proc_def_version: Optional[str] = None


    class Config:
        extra = "allow"


    def __init__(self, **data):
        super().__init__(**data)
        def_id = self.get_def_id()
        tenant_id = self.tenant_id
        self.process_definition = load_process_definition(fetch_process_definition(def_id, tenant_id))  # Load ProcessDefinition


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
    reference_ids: Optional[List[str]] = []
    assignees: Optional[List[Dict[str, Any]]] = []
    duration: Optional[int] = None
    output: Optional[Dict[str, Any]] = {}
    retry: Optional[int] = 0
    consumer: Optional[str] = None
    log: Optional[str] = None
    agent_mode: Optional[str] = None
    agent_orch: Optional[str] = None
    feedback: Optional[List[Dict[str, Any]]] = []
    
    @validator('start_date', 'end_date', 'due_date', pre=True)
    def parse_datetime(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).replace(tzinfo=None)
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


def fetch_process_instance(full_id: str, tenant_id: Optional[str] = None) -> Optional[ProcessInstance]:
    try:
        if full_id == "new" or '.' not in full_id:
            return None

        if not full_id:
            raise HTTPException(status_code=404, detail="Instance Id should be provided")

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('bpm_proc_inst').select("*").eq('proc_inst_id', full_id).eq('tenant_id', tenant_id).execute()

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


def insert_process_instance(process_instance_data: dict, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        if not tenant_id:
            tenant_id = subdomain_var.get()
        process_instance_data['tenant_id'] = tenant_id

        return supabase.table('bpm_proc_inst').upsert(process_instance_data).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def upsert_process_instance(process_instance: ProcessInstance, tenant_id: Optional[str] = None) -> (bool, ProcessInstance):
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
        
        if not tenant_id:
            tenant_id = subdomain_var.get()
            
        process_definition_version = fetch_process_definition_latest_version(process_instance.get_def_id(), tenant_id)
        if process_definition_version:
            arcv_id = process_definition_version.get('arcv_id', None)
        else:
            arcv_id = None

        response = supabase.table('bpm_proc_inst').upsert({
            'proc_inst_id': process_instance.proc_inst_id,
            'proc_inst_name': process_instance.proc_inst_name,
            'current_activity_ids': process_instance.current_activity_ids,
            'participants': process_instance.participants,
            'role_bindings': process_instance.role_bindings,
            'variables_data': process_instance.variables_data,
            'status': status,
            'proc_def_id': process_instance.get_def_id(),
            'proc_def_version': arcv_id,
            'tenant_id': tenant_id
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


def fetch_organization_chart(tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table("configuration").select("*").eq('key', 'organization').eq('tenant_id', tenant_id).execute()
        
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
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', subdomain).eq('proc_def_id', process_definition_id).filter('participants', 'cs', '{' + user_id + '}').execute()
        else:
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', subdomain).filter('participants', 'cs', '{' + user_id + '}').execute()
        
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


def fetch_todolist_by_proc_inst_id(proc_inst_id: str, tenant_id: Optional[str] = None) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('tenant_id', tenant_id).execute()
        

        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def fetch_workitem_by_proc_inst_and_activity(proc_inst_id: str, activity_id: str, tenant_id: Optional[str] = None) -> Optional[WorkItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('activity_id', activity_id).eq('tenant_id', tenant_id).execute()
        
        if response.data:
            return WorkItem(**response.data[0])
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_workitem_by_id(workitem_id: str, tenant_id: Optional[str] = None) -> Optional[WorkItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
            
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain
            
        response = supabase.table('todolist').select("*").eq('id', workitem_id).eq('tenant_id', tenant_id).execute()
        
        if response.data and len(response.data) > 0:
            return WorkItem(**response.data[0])
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_workitem_with_submitted_status(limit=5) -> Optional[List[dict]]:
    try:
        pod_id = socket.gethostname()
        db_config = db_config_var.get()


        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)


        query = """
            WITH locked_rows AS (
                SELECT id FROM todolist
                WHERE status = 'SUBMITTED'
                    AND consumer IS NULL
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE todolist
            SET consumer = %s
            FROM locked_rows
            WHERE todolist.id = locked_rows.id
            RETURNING *;
        """

        cursor.execute(query, (limit, pod_id))
        rows = cursor.fetchall()

        connection.commit()
        cursor.close()
        connection.close()

        return rows if rows else None

    except Exception as e:
        print(f"[ERROR] DB fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"DB fetch failed: {str(e)}") from e
    

def fetch_workitem_with_agent(limit=5) -> Optional[List[dict]]:
    try:
        pod_id = socket.gethostname()
        db_config = db_config_var.get()

        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        query = """
            WITH locked_rows AS (
                SELECT id FROM todolist
                WHERE status = 'IN_PROGRESS'
                    AND consumer IS NULL
                    AND agent_mode = 'A2A'
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE todolist
            SET consumer = %s
            FROM locked_rows
            WHERE todolist.id = locked_rows.id
            RETURNING *;
        """

        cursor.execute(query, (limit, pod_id))
        rows = cursor.fetchall()

        connection.commit()
        cursor.close()
        connection.close()

        return rows if rows else None

    except Exception as e:
        print(f"[ERROR] DB fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"DB fetch failed: {str(e)}") from e



def fetch_prev_task_ids(process_definition, current_activity_id: str, proc_inst_id: str) -> List[str]:
    """
    현재 테스크의 시퀀스 정보를 이용해 바로 직전 테스크의 ID 목록을 반환합니다.
    
    Args:
        process_definition: 프로세스 정의 객체
        current_activity_id: 현재 테스크의 ID
        proc_inst_id: 프로세스 인스턴스 ID
    
    Returns:
        List[str]: 직전 테스크의 activity ID 목록
    """
    prev_task_ids = []
    prev_activities = process_definition.find_immediate_prev_activities(current_activity_id)
    
    if prev_activities:
        # 이전 액티비티들의 activity_id를 수집
        for prev_activity in prev_activities:
            prev_task_ids.append(prev_activity.id)
    
    return prev_task_ids


def upsert_todo_workitems(process_instance_data, process_result_data, process_definition, tenant_id: Optional[str] = None):
    try:
        if not tenant_id:
            tenant_id = subdomain_var.get()


        initial_activity = next((activity for activity in process_definition.activities if process_definition.is_starting_activity(activity.id)), None)
        if not initial_activity:
            initial_activity = process_definition.find_initial_activity()

        next_activities = [activity for activity in process_definition.activities if activity.id != initial_activity.id]
        for activity in next_activities:
            prev_activities = process_definition.find_prev_activities(activity.id, [])
            start_date = datetime.now(pytz.timezone('Asia/Seoul'))
        
            if prev_activities:
                # 동일한 srcTrg를 가진 액티비티들 중 duration이 가장 큰 것만 남기기
                srcTrg_groups = {}
                for prev_activity in prev_activities:
                    if prev_activity.srcTrg not in srcTrg_groups:
                        srcTrg_groups[prev_activity.srcTrg] = []
                    srcTrg_groups[prev_activity.srcTrg].append(prev_activity)
                # duration이 가장 큰 액티비티만 선택
                filtered_activities = []
                for activities in srcTrg_groups.values():
                    max_duration_activity = max(activities, key=lambda x: x.duration if x.duration is not None else 0)
                    filtered_activities.append(max_duration_activity)
                
                reference_ids = fetch_prev_task_ids(process_definition, activity.id, process_instance_data['proc_inst_id'])
                
                for prev_activity in filtered_activities:
                    start_date = start_date + timedelta(days=prev_activity.duration)
            
            due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
            workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_data['proc_inst_id'], activity.id, tenant_id)
            if not workitem:
                user_id = ""
                assignees = []
                if process_result_data['roleBindings']:
                    role_bindings = process_result_data['roleBindings']
                    for role_binding in role_bindings:
                        if role_binding['name'] == activity.role:
                            if isinstance(role_binding['endpoint'], list):
                                user_id = ','.join(role_binding['endpoint'])
                            else:
                                user_id = role_binding['endpoint']
                            assignees.append(role_binding)
                
                agent_mode = None
                if activity.agentMode is not None:
                    if activity.agentMode != "none" and activity.agentMode != "None":
                        agent_mode = activity.agentMode.upper()
                elif activity.agentMode is None and user_id:
                    assignee_info = fetch_assignee_info(user_id)
                    if assignee_info['type'] == "a2a":
                        agent_mode = "A2A"
                
                workitem = WorkItem(
                    id=f"{str(uuid.uuid4())}",
                    reference_ids=reference_ids if prev_activities else [],
                    proc_inst_id=process_instance_data['proc_inst_id'],
                    proc_def_id=process_result_data['processDefinitionId'].lower(),
                    activity_id=activity.id,
                    activity_name=activity.name,
                    user_id=user_id,
                    status="TODO",
                    tool=activity.tool,
                    start_date=start_date,
                    due_date=due_date,
                    tenant_id=tenant_id,
                    assignees=assignees if assignees else [],
                    duration=activity.duration,
                    agent_mode=agent_mode,
                    description=activity.description,
                    agent_orch=activity.orchestration
                )
                workitem_dict = workitem.model_dump()
                workitem_dict["start_date"] = workitem.start_date.isoformat() if workitem.start_date else None
                workitem_dict["end_date"] = workitem.end_date.isoformat() if workitem.end_date else None
                workitem_dict["due_date"] = workitem.due_date.isoformat() if workitem.due_date else None


                supabase = supabase_client_var.get()
                if supabase is None:
                    raise Exception("Supabase client is not configured for this request")
                supabase.table('todolist').upsert(workitem_dict).execute()
    except Exception as e:
        print(f"[ERROR] upsert_todo_workitems: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e)) from e


def upsert_workitem(workitem_data: dict, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        if "start_date" in workitem_data and workitem_data["start_date"]:
            if not isinstance(workitem_data["start_date"], str):
                workitem_data["start_date"] = workitem_data["start_date"].isoformat()
        if "end_date" in workitem_data and workitem_data["end_date"]:
            if not isinstance(workitem_data["end_date"], str):
                workitem_data["end_date"] = workitem_data["end_date"].isoformat()
        if "due_date" in workitem_data and workitem_data["due_date"]:
            if not isinstance(workitem_data["due_date"], str):
                workitem_data["due_date"] = workitem_data["due_date"].isoformat()
        
        if not tenant_id:
            tenant_id = subdomain_var.get()
        workitem_data["tenant_id"] = tenant_id

        return supabase.table('todolist').upsert(workitem_data).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def delete_workitem(workitem_id: str, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        if not tenant_id:
            tenant_id = subdomain_var.get()


        supabase.table('todolist').delete().eq('id', workitem_id).eq('tenant_id', tenant_id).execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


import json


class ChatMessage(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    image: Optional[str] = None
    content: Optional[str] = None
    timeStamp: Optional[int] = None
    jsonContent: Optional[Any] = None
    htmlContent: Optional[str] = None
    contentType: Optional[str] = None

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


def upsert_chat_message(chat_room_id: str, data: Any, is_system: bool, tenant_id: Optional[str] = None, is_agent: Optional[bool] = False) -> None:
    try:
        if is_agent:
            message = ChatMessage(
                name=data["name"],
                role="agent",
                content=data["content"],
                jsonContent=data["jsonData"] if "jsonData" in data else None,
                htmlContent=data["html"] if "html" in data else None,
                timeStamp=int(datetime.now(pytz.timezone('Asia/Seoul')).timestamp() * 1000),
            )
        else:
            if is_system:
                if isinstance(data, str):
                    json_data = json.loads(data)
                else:
                    json_data = data
                message = ChatMessage(
                    name="system",
                    role="system",
                    email="system@uengine.org",
                    image="",
                    content=json_data["description"],
                    contentType="html" if "html" in json_data else "text",
                    jsonContent=json_data["jsonData"] if "jsonData" in json_data else None,
                    htmlContent=json_data["html"] if "html" in json_data else None,
                    timeStamp=int(datetime.now(pytz.timezone('Asia/Seoul')).timestamp() * 1000)
                )
            else:
                if data["email"] == "external_customer":
                    name = "외부 고객"
                else:
                    user_info = fetch_user_info(data["email"])
                    name = user_info["username"]
                message = ChatMessage(
                    name=name,
                    role="user",
                    email=data["email"],
                    image="",
                    content=data["command"],
                    timeStamp=int(datetime.now(pytz.timezone('Asia/Seoul')).timestamp() * 1000)
                )

        if not tenant_id:
            tenant_id = subdomain_var.get()


        chat_item = ChatItem(
            id=chat_room_id,
            uuid=str(uuid.uuid4()),
            messages=message,
            tenant_id=tenant_id
        )
        chat_item_dict = chat_item.model_dump()


        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")


        supabase.table("chats").upsert(chat_item_dict).execute();
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_user_info(email: str) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("users").select("*").eq('email', email).execute()
        
        if response.data:
            return response.data[0]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def fetch_assignee_info(assignee_id: str) -> Dict[str, str]:
    """
    담당자 정보를 찾는 함수
    담당자가 유저인지 에이전트인지 판단하고 적절한 정보를 반환합니다.
    
    Args:
        assignee_id: 담당자 ID (이메일 또는 에이전트 ID)
    
    Returns:
        담당자 정보 딕셔너리
    """
    try:
        try:
            user_info = fetch_user_info(assignee_id)
            type = "user"
            if user_info.get("is_agent") == True:
                type = "agent"
                if user_info.get("url") is not None and user_info.get("url").strip() != "":
                    type = "a2a"
            return {
                "type": type,
                "id": assignee_id,
                "name": user_info.get("username", assignee_id),
                "email": assignee_id,
                "info": user_info
            }
        except HTTPException as user_error:
            if user_error.status_code == 500 or user_error.status_code == 404:
                return {
                    "type": "unknown",
                    "id": assignee_id,
                    "name": assignee_id,
                    "email": assignee_id,
                    "info": {}
                }
            else:
                raise user_error
    except Exception as e:
        return {
            "type": "error",
            "id": assignee_id,
            "name": assignee_id,
            "email": assignee_id,
            "info": {},
            "error": str(e)
        }


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
    tenant_id = subdomain_var.get()
    db_config = db_config_var.get()
    
    connection = psycopg2.connect(**db_config)
    cursor = connection.cursor(cursor_factory=RealDictCursor)


    with open(csv_file_path, mode='r', encoding='utf-8') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            values = value_extractor(row, tenant_id)
            cursor.execute(insert_query, values)


    connection.commit()
    cursor.close()
    connection.close()


def insert_process_definition_from_csv():
    csv_file_path = './csv/proc_def.csv'
    insert_query = """
        INSERT INTO proc_def (id, name, definition, bpmn, tenant_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id, tenant_id) DO UPDATE SET
            name = EXCLUDED.name,
            definition = EXCLUDED.definition,
            bpmn = EXCLUDED.bpmn
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
        ON CONFLICT (id, tenant_id) DO UPDATE SET
            html = EXCLUDED.html,
            fields_json = EXCLUDED.fields_json,
            proc_def_id = EXCLUDED.proc_def_id,
            activity_id = EXCLUDED.activity_id
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


def merge_proc_map_json(existing, incoming):
    def find_by_id(obj_list, target_id):
        return next((item for item in obj_list if item["id"] == target_id), None)


    for new_mega in incoming.get("mega_proc_list", []):
        existing_mega = find_by_id(existing.get("mega_proc_list", []), new_mega["id"])
        if not existing_mega:
            existing["mega_proc_list"].append(new_mega)
            continue


        for new_major in new_mega.get("major_proc_list", []):
            existing_major = find_by_id(existing_mega.get("major_proc_list", []), new_major["id"])
            if not existing_major:
                existing_mega["major_proc_list"].append(new_major)
                continue


            for new_sub in new_major.get("sub_proc_list", []):
                if not any(sub["id"] == new_sub["id"] for sub in existing_major.get("sub_proc_list", [])):
                    existing_major["sub_proc_list"].append(new_sub)


    return existing


def insert_configuration_from_csv():
    csv_file_path = './csv/configuration.csv'
    tenant_id = subdomain_var.get()
    db_config = db_config_var.get()
    
    connection = psycopg2.connect(**db_config)
    cursor = connection.cursor(cursor_factory=RealDictCursor)


    with open(csv_file_path, mode='r', encoding='utf-8') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            key = row['key']
            raw_value = row['value']


            if key == 'proc_map':
                incoming_value = json.loads(raw_value)


                # 기존 데이터 조회
                cursor.execute("SELECT value FROM configuration WHERE key = %s AND tenant_id = %s", (key, tenant_id))
                result = cursor.fetchone()


                if result:
                    existing_value = result['value']
                    merged_value = merge_proc_map_json(existing_value, incoming_value)


                    cursor.execute(
                        "UPDATE configuration SET value = %s WHERE key = %s AND tenant_id = %s",
                        (json.dumps(merged_value, ensure_ascii=False), key, tenant_id)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO configuration (key, value, tenant_id) VALUES (%s, %s, %s)",
                        (key, json.dumps(incoming_value, ensure_ascii=False), tenant_id)
                    )
            else:
                # 일반 키는 단순 upsert
                cursor.execute(
                    """
                    INSERT INTO configuration (key, value, tenant_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key, tenant_id) DO UPDATE SET
                        value = EXCLUDED.value
                    """,
                    (key, raw_value, tenant_id)
                )


    connection.commit()
    cursor.close()
    connection.close()


def insert_sample_data():
    insert_configuration_from_csv()
    insert_process_definition_from_csv()
    insert_process_form_definition_from_csv()




def update_user_admin(input):
    try:
        user_id = input.get('user_id')
        user_info = input.get('user_info')
        supabase = supabase_client_var.get()
        
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.auth.admin.update_user_by_id(user_id, user_info)
        return response


    except Exception as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e

def invite_user(input):
    try:
        supabase = supabase_client_var.get()
     
        email = input.get("email")
        is_admin = input.get("is_admin")

        tenant_id = input.get('tenant_id') if input.get('tenant_id') else subdomain_var.get()
        user_id = None
        response = None
        redirect_url = None

        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        try:
            is_user_exist = fetch_user_info(email)
        except HTTPException as e:
            is_user_exist = None
        
        if is_user_exist:
            user_id = is_user_exist['id']
        else:
            redirect_url = f"https://{tenant_id}.process-gpt.io/auth/initial-setting"
            response = supabase.auth.admin.invite_user_by_email(
                email,
                {
                    "redirect_to": redirect_url
                }
            )
            if response.user:
                user_id = response.user.id

        if user_id:
            supabase.table("users").insert({
                "id": user_id,
                "email": email,
                "username": email.split('@')[0],
                "role": 'user',
                "is_admin": is_admin,
                "tenant_id": tenant_id
            }).execute()
        
        return {
            "success": True,
            "message": f"Invitation sent to {email}",
            "redirect_url": redirect_url,
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"Error inviting user: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to invite user: {str(e)}") from e


def set_initial_info(input):
    try:
        supabase = supabase_client_var.get()
        
        user_id = input.get("user_id")
        user_name = input.get("user_name")
        password = input.get("password")
        tenant_id = subdomain_var.get()
        
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        
        # 관리자 권한으로 사용자 비밀번호 업데이트
        response = supabase.auth.admin.update_user_by_id(
            user_id,
            {
                "password": password
            }
        )
        
        print(f"Initial password set for user: {user_id}")
        print(f"Response: {response}")

        supabase.table("users").update({
            "username": user_name
        }).eq('id', user_id).eq('tenant_id', tenant_id).execute()
        
        return {
            "success": True,
            "message": "Initial setting has been completed successfully",
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"Error setting initial password: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set initial password: {str(e)}") from e

def create_user(input):
    try:
        
        supabase = supabase_client_var.get()
     
        username = input.get("username")
        email = input.get("email")
        role = input.get("role")
        tenant_id = subdomain_var.get()

        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        try:
            is_user_exist = fetch_user_info(email)
        except HTTPException as e:
            is_user_exist = None
        
        if is_user_exist:
            supabase.table("users").insert({
                "id": is_user_exist["id"],
                "email": email,
                "username": username,
                "role": role,
                "tenant_id": tenant_id
            }).execute()
        else:
            response = supabase.auth.admin.create_user({
                "email": email,
                "username": username,
                "password": "000000",
                "email_confirm": True,
                "app_metadata": {
                    "tenant_id": tenant_id
                }
            })
            
            if response.user:
                supabase.table("users").insert({
                    "id": response.user.id,
                    "email": email,
                    "username": username,
                    "role": role,
                    "tenant_id": tenant_id
                }).execute()
                return response
            else:
                raise HTTPException(status_code=404, detail="User creation failed")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def update_user(input):
    try:
        user_id = input.get('user_id')
        user_info = input.get('user_info')
        supabase = supabase_client_var.get()
        
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("users").update(user_info).eq('id', user_id).execute()
        return response
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def fetch_user_info_by_uid(uid: str) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("users").select("*").eq('id', uid).execute()
        if response.data:
            return response.data[0]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def check_tenant_owner(tenant_id: str, uid: str) -> bool:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("tenants").select("*").eq('id', tenant_id).eq('owner', uid).execute()
        if response.data:
            return True
        else:
            return False
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# fetch_device_token 함수 제거 - FCM 서비스로 분리됨
# 필요한 경우 fcm_client.get_device_token() 사용


# send_fcm_message 함수 제거 - FCM 서비스로 분리됨
# 필요한 경우 fcm_client.send_fcm_notification() 사용




def handle_new_notification(notification_record):
    """
    새로운 알림에 대해 FCM 푸시 알림을 전송하는 핸들러
    """
    try:
        from fcm_client import send_fcm_notification
        
        user_id = notification_record.get('user_id')
        if not user_id:
            realtime_logger.warning("user_id가 없습니다.")
            return
        
        # FCM 알림 데이터 구성
        tenant_id = notification_record.get('tenant_id', '')
        url = notification_record.get('url', '')
        if tenant_id and url:
            url = f"https://{tenant_id}.process-gpt.io{url}"
        else:
            url = notification_record.get('url', '')

        print(f"url: {url}")
        
        notification_data = {
            'title': notification_record.get('title', '새 알림'),
            'body': notification_record.get('description', '새로운 알림이 도착했습니다.'),
            'type': notification_record.get('type', 'general'),
            'url': url,
            'from_user_id': notification_record.get('from_user_id', ''),
            'data': {
                'notification_id': str(notification_record.get('id', '')),
                'url': notification_record.get('url', '')
            }
        }
        
        # FCM 서비스를 통해 메시지 전송
        result = send_fcm_notification(user_id, notification_data)
        realtime_logger.info(f"FCM 알림 전송 결과: {result}")
        
    except Exception as e:
        realtime_logger.error(f"알림 처리 중 오류 발생: {e}")


def fetch_unprocessed_notifications() -> Optional[List[dict]]:
    try:
        pod_id = socket.gethostname()
        db_config = db_config_var.get()

        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        query = """
            WITH locked_rows AS (
                SELECT id FROM notifications
                WHERE consumer IS NULL
                FOR UPDATE SKIP LOCKED
            )
            UPDATE notifications
            SET consumer = %s
            FROM locked_rows
            WHERE notifications.id = locked_rows.id
            RETURNING *;
        """

        cursor.execute(query, (pod_id,))
        affected_count = cursor.rowcount
        rows = cursor.fetchall()

        connection.commit()
        cursor.close()
        connection.close()

        return rows if affected_count > 0 else None

    except Exception as e:
        realtime_logger.error(f"미처리 알림 fetch 실패: {str(e)}")
        return None


# check_new_notifications와 notification_polling_task 함수 제거
# 이제 FCM 서비스에서 폴링 및 알림 처리를 담당합니다.


