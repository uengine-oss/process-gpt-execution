from supabase import create_client, Client
from pydantic import BaseModel, validator
from typing import Any, Dict, List, Optional, Set
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from process_definition import ProcessDefinition, load_process_definition, UIDefinition
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException
from decimal import Decimal
from datetime import datetime, timedelta
from contextvars import ContextVar
from dotenv import load_dotenv

import pytz
import psycopg2
import socket
import os
import uuid
import json


db_config_var = ContextVar('db_config', default={})
supabase_client_var = ContextVar('supabase', default=None)
subdomain_var = ContextVar('subdomain', default='localhost')


def setting_database():
    try:
        if os.getenv("ENV") != "production":
            load_dotenv()
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase: Client = create_client(supabase_url, supabase_key)
        supabase_client_var.set(supabase)
        
        env = os.getenv("ENV", "development")
        if env == "production":
            ssl_mode = "require"
        else:
            ssl_mode = "prefer"
        
        db_config = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST"),
            "port": os.getenv("DB_PORT"),
            "sslmode": ssl_mode,
            "connect_timeout": 10,
            "application_name": "polling_service"
        }
        
        print(f"[INFO] Database SSL mode: {ssl_mode} (ENV: {env})")
        db_config_var.set(db_config)
        
    except Exception as e:
        print(f"Database configuration error: {e}")


def get_db_connection_with_retry(max_retries=3, retry_delay=1):
    """
    재시도 로직이 포함된 데이터베이스 연결 함수
    """
    db_config = db_config_var.get()
    
    for attempt in range(max_retries):
        try:
            connection = psycopg2.connect(**db_config)
            # 연결 상태 확인
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return connection
        except psycopg2.OperationalError as e:
            error_msg = str(e)
            if "SSL connection has been closed unexpectedly" in error_msg:
                print(f"[WARNING] SSL connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay)
                    continue
            elif "server does not support SSL" in error_msg:
                print(f"[WARNING] Server does not support SSL, trying without SSL...")
                # SSL을 비활성화하고 재시도
                db_config_without_ssl = db_config.copy()
                db_config_without_ssl["sslmode"] = "disable"
                try:
                    connection = psycopg2.connect(**db_config_without_ssl)
                    cursor = connection.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                    print("[INFO] Successfully connected without SSL")
                    return connection
                except Exception as ssl_error:
                    print(f"[ERROR] Failed to connect even without SSL: {ssl_error}")
            raise e
        except Exception as e:
            print(f"[ERROR] Database connection failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
                continue
            raise e
    
    raise Exception(f"Failed to connect to database after {max_retries} attempts")


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


def fetch_process_definition_latest_version(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('tenant_id', tenant_id).order('version', desc=True).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No process definition latest version found with ID {def_id}: {e}")


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
    current_user_ids: Optional[List[str]] = []
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
    process_definition = process_instance.process_definition
    if process_definition is None:
        process_definition = load_process_definition(fetch_process_definition(process_instance.get_def_id(), tenant_id))
        process_instance.process_definition = process_definition

    end_activity = process_definition.find_end_activity()
    if end_activity:
        end_workitem = fetch_workitem_by_proc_inst_and_activity(process_instance.proc_inst_id, end_activity.id, tenant_id)
        if end_workitem:
            if end_workitem.status == 'DONE':
                status = 'COMPLETED'
            else:
                status = 'RUNNING'
        else:
            status = 'RUNNING'
    else:
        if process_instance.current_activity_ids and len(process_instance.current_activity_ids) != 0:
            if end_activity and end_activity.id in process_instance.current_activity_ids:
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
        
        current_user_ids = process_instance.current_user_ids
        
        # 빈 값들 필터링 및 유효성 검증
        if current_user_ids:
            valid_user_ids = []
            for user_id in current_user_ids:
                if user_id is not None and user_id != '' and user_id != 'undefined' and user_id.strip() != '':
                    # 'external_customer'는 특별 케이스로 허용
                    if user_id == 'external_customer':
                        valid_user_ids.append(user_id)
                    else:
                        # fetch_assignee_info로 담당자 정보 확인
                        assignee_info = fetch_assignee_info(user_id)
                        # 'unknown'이나 'error' 타입이 아니면 유효한 담당자
                        if assignee_info['type'] not in ['unknown', 'error']:
                            valid_user_ids.append(user_id)
            current_user_ids = valid_user_ids

        response = supabase.table('bpm_proc_inst').upsert({
            'proc_inst_id': process_instance.proc_inst_id,
            'proc_inst_name': process_instance.proc_inst_name,
            'current_activity_ids': process_instance.current_activity_ids,
            'current_user_ids': current_user_ids,
            'role_bindings': process_instance.role_bindings,
            'variables_data': process_instance.variables_data,
            'status': status if status else process_instance.status,
            'proc_def_id': process_instance.get_def_id(),
            'proc_def_version': arcv_id,
            'tenant_id': tenant_id
        }).execute()

        success = bool(response.data)

        return success, process_instance

    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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


def fetch_workitem_with_submitted_status(limit=5) -> Optional[List[dict]]:
    connection = None
    try:
        pod_id = socket.gethostname()
        
        # 재시도 로직이 포함된 연결 사용
        connection = get_db_connection_with_retry()
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
        if connection:
            try:
                connection.rollback()
                connection.close()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"DB fetch failed: {str(e)}") from e


def fetch_workitem_with_agent(limit=5) -> Optional[List[dict]]:
    connection = None
    try:
        pod_id = socket.gethostname()
        
        # 재시도 로직이 포함된 연결 사용
        connection = get_db_connection_with_retry()
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
        if connection:
            try:
                connection.rollback()
                connection.close()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"DB fetch failed: {str(e)}") from e


def cleanup_stale_consumers():
    """
    오래된 consumer를 정리하는 함수
    30분 이상 업데이트되지 않은 IN_PROGRESS 상태의 워크아이템의 consumer를 해제
    """
    connection = None
    try:
        # 재시도 로직이 포함된 연결 사용
        connection = get_db_connection_with_retry()
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        query = """
            UPDATE todolist
            SET consumer = NULL
            WHERE status = 'IN_PROGRESS'
                AND consumer IS NOT NULL
                AND start_date < NOW() - INTERVAL '30 minutes';
        """

        cursor.execute(query)
        updated_count = cursor.rowcount

        connection.commit()
        cursor.close()
        connection.close()

        if updated_count > 0:
            print(f"[INFO] Cleaned up {updated_count} stale consumers")

    except Exception as e:
        print(f"[ERROR] Failed to cleanup stale consumers: {str(e)}")
        if connection:
            try:
                connection.rollback()
                connection.close()
            except:
                pass


def upsert_completed_workitem(process_instance_data, process_result_data, process_definition, tenant_id: Optional[str] = None):
    try:
        if not tenant_id:
            tenant_id = subdomain_var.get()


        if not process_result_data['completedActivities']:
            return
        
        for completed_activity in process_result_data['completedActivities']:
            workitem = fetch_workitem_by_proc_inst_and_activity(
                process_instance_data['proc_inst_id'],
                completed_activity['completedActivityId'],
                tenant_id
            )
            
            if workitem:
                workitem.status = completed_activity['result']
                workitem.end_date = datetime.now(pytz.timezone('Asia/Seoul'))
                workitem.user_id = completed_activity['completedUserEmail']
                if workitem.assignees and len(workitem.assignees) > 0:
                    for assignee in workitem.assignees:
                        if assignee.get('endpoint') and assignee.get('endpoint') == workitem.user_id:
                            assignee = {
                                'roleName': assignee.get('name'),
                                'userId': assignee.get('endpoint')
                            }
                            break
            else:
                activity = process_definition.find_activity_by_id(completed_activity['completedActivityId'])
                start_date = datetime.now(pytz.timezone('Asia/Seoul'))
                due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
                assignees = []
                if process_instance_data['role_bindings']:
                    role_bindings = process_instance_data['role_bindings']
                    for role_binding in role_bindings:
                        if role_binding['name'] == activity.role:
                            user_id = ','.join(role_binding['endpoint']) if isinstance(role_binding['endpoint'], list) else role_binding['endpoint']
                            assignees.append(role_binding)
                            
                workitem = WorkItem(
                    id=f"{str(uuid.uuid4())}",
                    proc_inst_id=process_instance_data['proc_inst_id'],
                    proc_def_id=process_result_data['processDefinitionId'].lower(),
                    activity_id=completed_activity['completedActivityId'],
                    activity_name=activity.name,
                    user_id=completed_activity['completedUserEmail'],
                    status=completed_activity['result'],
                    tool=activity.tool,
                    start_date=start_date,
                    end_date=datetime.now(pytz.timezone('Asia/Seoul')) if completed_activity['result'] == 'DONE' else None,
                    due_date=due_date,
                    tenant_id=tenant_id,
                    assignees=assignees,
                    duration=activity.duration
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
        print(f"[ERROR] upsert_completed_workitem: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e)) from e


def upsert_next_workitems(process_instance_data, process_result_data, process_definition, tenant_id: Optional[str] = None) -> List[WorkItem]:
    workitems = []
    if not tenant_id:
        tenant_id = subdomain_var.get()


    for activity_data in process_result_data['nextActivities']:
        if activity_data['nextActivityId'] in ["END_PROCESS", "endEvent", "end_event"]:
            continue
        
        workitem = fetch_workitem_by_proc_inst_and_activity(process_instance_data['proc_inst_id'], activity_data['nextActivityId'], tenant_id)
        
        if workitem:
            workitem.status = activity_data['result']
            workitem.end_date = datetime.now(pytz.timezone('Asia/Seoul')) if activity_data['result'] == 'DONE' else None
            workitem.user_id = activity_data['nextUserEmail']
            if workitem.user_id and workitem.agent_mode != "A2A":
                assignee_info = fetch_assignee_info(workitem.user_id)
                if assignee_info['type'] == "a2a":
                    workitem.agent_mode = "A2A"
        else:
            activity = process_definition.find_activity_by_id(activity_data['nextActivityId'])
            if activity:
                prev_activities = process_definition.find_prev_activities(activity.id, [])
                start_date = datetime.now(pytz.timezone('Asia/Seoul'))
                if prev_activities:
                    for prev_activity in prev_activities:
                        start_date = start_date + timedelta(days=prev_activity.duration)
                due_date = start_date + timedelta(days=activity.duration) if activity.duration else None
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
                    tenant_id=tenant_id
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
            print(f"[ERROR] upsert_next_workitems: {str(e)}")
            raise HTTPException(status_code=404, detail=str(e)) from e


    return workitems


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
                            user_id = ','.join(role_binding['endpoint']) if isinstance(role_binding['endpoint'], list) else role_binding['endpoint']
                            assignees.append(role_binding)
                
                agent_mode = ""
                if activity.agentMode is not None:
                    agent_mode = activity.agentMode

                if user_id:
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
                    agent_mode=agent_mode
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


def upsert_chat_message(chat_room_id: str, data: Any, tenant_id: Optional[str] = None) -> None:
    """
    채팅 메시지를 upsert하는 함수
    
    Args:
        chat_room_id: 채팅방 ID
        data: 메시지 데이터 (dict 또는 str) - role 필드 포함
        tenant_id: 테넌트 ID
    """
    try:
        current_timestamp = int(datetime.now(pytz.timezone('Asia/Seoul')).timestamp() * 1000)
        
        # data가 문자열인 경우 JSON으로 파싱
        if isinstance(data, str):
            message_data = json.loads(data)
        else:
            message_data = data
        
        # role이 없으면 기본값 설정
        if "role" not in message_data:
            message_data["role"] = "system"
        
        # timestamp가 없으면 추가
        if "timeStamp" not in message_data:
            message_data["timeStamp"] = current_timestamp

        if not tenant_id:
            tenant_id = subdomain_var.get()

        # 채팅 아이템 데이터 구성
        chat_item_data = {
            "id": chat_room_id,
            "uuid": str(uuid.uuid4()),
            "messages": message_data,
            "tenant_id": tenant_id
        }

        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")

        supabase.table("chats").upsert(chat_item_data).execute()
        
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

def fetch_user_info(email: str) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("users").select("*").eq('email', email).execute()
        
        if response.data and len(response.data) > 0:
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
        # 먼저 유저 정보를 찾아봅니다
        try:
            user_info = fetch_user_info(assignee_id)
            return {
                "type": "user",
                "id": assignee_id,
                "name": user_info.get("name", assignee_id),
                "email": assignee_id,
                "info": user_info
            }
        except HTTPException as user_error:
            if user_error.status_code == 500 or user_error.status_code == 404:
                # 유저를 찾을 수 없으면 에이전트 정보를 찾아봅니다
                try:
                    agent_info = fetch_agent_by_id(assignee_id)
                    url = agent_info.get("url")
                    is_a2a = url is not None and url.strip() != ""
                    return {
                        "type": "a2a" if is_a2a else "agent",
                        "id": assignee_id,
                        "name": agent_info.get("name", assignee_id),
                        "email": assignee_id,
                        "info": agent_info
                    }
                except HTTPException as agent_error:
                    # 에이전트도 찾을 수 없으면 기본 정보를 반환
                    return {
                        "type": "unknown",
                        "id": assignee_id,
                        "name": assignee_id,
                        "email": assignee_id,
                        "info": {}
                    }
            else:
                # 유저 조회 중 다른 오류가 발생한 경우
                raise user_error
    except Exception as e:
        # 예상치 못한 오류가 발생한 경우 기본 정보를 반환
        return {
            "type": "error",
            "id": assignee_id,
            "name": assignee_id,
            "email": assignee_id,
            "info": {},
            "error": str(e)
        }



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


def fetch_agent_by_id(agent_id: str) -> Optional[dict]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.table("agents").select("*").eq('id', agent_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            return None
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
