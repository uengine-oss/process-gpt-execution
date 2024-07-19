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

async def add_table_columns(request: Request):
    try:
        obj = await request.json()  # Request 객체를 통해 JSON 데이터 받아오기
        table_name = obj['tableName']
        columns = obj['tableColumns']

        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        for column_name, column_type in columns.items():
            sql_query = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name='{table_name}' 
        AND column_name='{column_name}'
    ) THEN
        ALTER TABLE {table_name}
        ADD COLUMN {column_name} {column_type} null;
    END IF;
END $$;
"""
            cursor.execute(sql_query)
        
        connection.commit()
        return "Columns added"
    except Exception as e:
        print(f"An error occurred: {e}")

def create_default_tables():
    try:
        db_config = db_config_var.get()
        # Establish a connection to the database
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        
        sql_query = """
drop table if exists configuration CASCADE;
create table configuration (
  key text primary key,
  value jsonb
);
insert into configuration (key, value) values ('proc_map', '{"mega_proc_list":[{"id":1,"name":"휴가","major_proc_list":[{"id":0,"name":"휴가관리","sub_proc_list":[{"id":"vacation_request_process","name":"휴가 신청 프로세스"}]}]}]}');
insert into configuration (key, value) values ('organization', '{}');

drop table if exists public.proc_map_history CASCADE;
create table public.proc_map_history (
    value jsonb not null,
    created_at timestamp with time zone not null default now(),
    constraint proc_map_history_pkey primary key (created_at)
) tablespace pg_default;

create or replace function public.save_previous_proc_map()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.key = 'proc_map' THEN
        INSERT INTO public.proc_map_history(value, created_at)
        VALUES (OLD.value, now());
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

create or replace trigger trigger_save_previous_proc_map
BEFORE UPDATE ON configuration
FOR EACH ROW
WHEN (OLD.key = 'proc_map' AND NEW.value IS DISTINCT FROM OLD.value)
EXECUTE PROCEDURE public.save_previous_proc_map();

drop table if exists todolist CASCADE;
create table todolist (
    id uuid primary key,
    user_id text,
    proc_inst_id text,
    proc_def_id text,
    activity_id text,
    activity_name text,
    start_date timestamp,
    end_date timestamp,
    status text,
    description text,
    tool text
);

create view public.worklist as
select
  t.*,
  p.name as proc_inst_name
from
  todolist t
  join public.proc_inst p on t.proc_inst_id = p.id;

drop table if exists public.users CASCADE;
create table public.users (
    id uuid not null primary key,
    username text null,
    profile text null default '/src/assets/images/profile/defaultUser.png'::text,
    email text null,
    is_admin boolean not null default false,
    notifications jsonb null,
    role text null
);

create or replace function public.handle_new_user() 
returns trigger as $$
begin
    insert into public.users (id, email)
    values (new.id, new.email);
      return new;
end;
$$ language plpgsql security definer;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

create or replace function public.handle_delete_user() 
returns trigger as $$
begin
    delete from auth.users where id = old.id;
    return old;
end;
$$ language plpgsql security definer;

create or replace trigger on_public_user_deleted
    after delete on public.users
    for each row execute procedure public.handle_delete_user();

drop table if exists proc_def CASCADE;
create table proc_def (
  id text primary key,
  name text,
  definition jsonb,
  bpmn text
);

insert into proc_def (id, name, definition, bpmn)
values (
  'vacation_request_process', '휴가 신청 프로세스', '{"data":[{"name":"Name","type":"Text","description":"Namedescription"},{"name":"LeaveReason","type":"Text","description":"LeaveReasondescription"},{"name":"StartDate","type":"Date","description":"StartDatedescription"},{"name":"EndDate","type":"Date","description":"EndDatedescription"},{"name":"ManagerApproval","type":"Boolean","description":"ManagerApprovaldescription"},{"name":"HRNotification","type":"Boolean","description":"HRNotificationdescription"}],"roles":[{"name":"Employee","resolutionRule":"system"},{"name":"Manager","resolutionRule":"system"},{"name":"HR","resolutionRule":"system"}],"events":[{"id":"start_event","name":"start_event","role":"Employee","type":"StartEvent","description":"startevent"},{"id":"end_event","name":"end_event","role":"HR","type":"EndEvent","description":"endevent"}],"gateways":[],"sequences":[{"source":"start_event","target":"leave_request_activity","condition":""},{"source":"leave_request_activity","target":"manager_approval_activity","condition":""},{"source":"manager_approval_activity","target":"hr_notification_activity","condition":"ManagerApproval==true"},{"source":"hr_notification_activity","target":"end_event","condition":""}],"activities":[{"id":"leave_request_activity","name":"휴가신청서제출","role":"Employee","tool":"","type":"UserActivity","inputData":[{"argument":{"text":"이름"},"variable":{"name":"Name"},"direction":"IN"},{"argument":{"text":"휴가사유"},"variable":{"name":"LeaveReason"},"direction":"IN"},{"argument":{"text":"휴가시작일"},"variable":{"name":"StartDate"},"direction":"IN"},{"argument":{"text":"휴가복귀일"},"variable":{"name":"EndDate"},"direction":"IN"}],"outputData":[],"description":"휴가신청서제출description","instruction":"휴가신청서제출instruction"},{"id":"manager_approval_activity","name":"팀장승인","role":"Manager","tool":"","type":"UserActivity","inputData":[{"argument":{"text":"휴가승인여부"},"variable":{"name":"ManagerApproval"},"direction":"IN"}],"outputData":[],"description":"팀장승인description","instruction":"팀장승인instruction"},{"id":"hr_notification_activity","name":"인사팀통지","role":"HR","tool":"","type":"UserActivity","inputData":[{"argument":{"text":"휴가통지여부"},"variable":{"name":"HRNotification"},"direction":"IN"}],"outputData":[],"description":"인사팀통지description","instruction":"인사팀통지instruction"}],"description":"process.description","processDefinitionId":"vacation_request_process","processDefinitionName":"휴가신청프로세스"}', '<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:uengine="http://uengine" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" id="Definitions_vacation_request_process" targetNamespace="http://bpmn.io/schema/bpmn" exporter="Custom BPMN Modeler" exporterVersion="1.0">
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="Participant" name="Participant" processRef="vacation_request_process" />
  </bpmn:collaboration>
  <bpmn:process id="vacation_request_process" isExecutable="true">
    <bpmn:extensionElements>
      <uengine:properties>
        <uengine:variable name="Name" type="Text" />
        <uengine:variable name="LeaveReason" type="Text" />
        <uengine:variable name="StartDate" type="Date" />
        <uengine:variable name="EndDate" type="Date" />
        <uengine:variable name="ManagerApproval" type="Boolean" />
        <uengine:variable name="HRNotification" type="Boolean" />
      </uengine:properties>
    </bpmn:extensionElements>
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_0" name="Employee">
        <bpmn:flowNodeRef>leave_request_activity</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_1" name="Manager">
        <bpmn:flowNodeRef>manager_approval_activity</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_2" name="HR">
        <bpmn:flowNodeRef>hr_notification_activity</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:sequenceFlow id="SequenceFlow_start_event_leave_request_activity" name="" sourceRef="start_event" targetRef="leave_request_activity">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_leave_request_activity_manager_approval_activity" name="" sourceRef="leave_request_activity" targetRef="manager_approval_activity">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_manager_approval_activity_hr_notification_activity" name="" sourceRef="manager_approval_activity" targetRef="hr_notification_activity">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":"ManagerApproval == true"}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_hr_notification_activity_end_event" name="" sourceRef="hr_notification_activity" targetRef="end_event">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:startEvent id="start_event" name="Start Event" />
    <bpmn:endEvent id="end_event" name="End Event" />
    <bpmn:userTask id="leave_request_activity" name="휴가 신청서 제출" $type="bpmn:UserTask">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[{"argument":{"text":"이름"},"variable":{"name":"Name"},"direction":"IN"},{"argument":{"text":"휴가 사유"},"variable":{"name":"LeaveReason"},"direction":"IN"},{"argument":{"text":"휴가 시작일"},"variable":{"name":"StartDate"},"direction":"IN"},{"argument":{"text":"휴가 복귀일"},"variable":{"name":"EndDate"},"direction":"IN"}]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_start_event_leave_request_activity</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_leave_request_activity_manager_approval_activity</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:userTask id="manager_approval_activity" name="팀장 승인" $type="bpmn:UserTask">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[{"argument":{"text":"휴가 승인 여부"},"variable":{"name":"ManagerApproval"},"direction":"IN"}]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_leave_request_activity_manager_approval_activity</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_manager_approval_activity_hr_notification_activity</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:userTask id="hr_notification_activity" name="인사팀 통지" $type="bpmn:UserTask">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[{"argument":{"text":"휴가 통지 여부"},"variable":{"name":"HRNotification"},"direction":"IN"}]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_manager_approval_activity_hr_notification_activity</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_hr_notification_activity_end_event</bpmn:outgoing>
    </bpmn:userTask>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Collaboration_1">
      <bpmndi:BPMNShape id="Participant_1" bpmnElement="Participant">
        <dc:Bounds x="70" y="100" width="780" height="300" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_2" bpmnElement="Lane_2" isHorizontal="true">
        <dc:Bounds x="100" y="300" width="750" height="100" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_1" bpmnElement="Lane_1" isHorizontal="true">
        <dc:Bounds x="100" y="200" width="750" height="100" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_0" bpmnElement="Lane_0" isHorizontal="true">
        <dc:Bounds x="100" y="100" width="750" height="100" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_start_event" bpmnElement="start_event">
        <dc:Bounds x="160" y="133" width="34" height="34" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="145" y="173" width="64" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_end_event" bpmnElement="end_event">
        <dc:Bounds x="750" y="333" width="34" height="34" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="735" y="373" width="64" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_leave_request_activity" bpmnElement="leave_request_activity">
        <dc:Bounds x="240" y="110" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_manager_approval_activity" bpmnElement="manager_approval_activity">
        <dc:Bounds x="400" y="210" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_hr_notification_activity" bpmnElement="hr_notification_activity">
        <dc:Bounds x="560" y="310" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="BPMNEdge_start_event_leave_request_activity" bpmnElement="SequenceFlow_start_event_leave_request_activity">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="194" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="240" y="150" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_leave_request_activity_manager_approval_activity" bpmnElement="SequenceFlow_leave_request_activity_manager_approval_activity">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="340" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="365" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="365" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="400" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="400" y="250" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_manager_approval_activity_hr_notification_activity" bpmnElement="SequenceFlow_manager_approval_activity_hr_notification_activity">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="500" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="525" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="525" y="350" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="560" y="350" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="560" y="350" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_hr_notification_activity_end_event" bpmnElement="SequenceFlow_hr_notification_activity_end_event">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="660" y="350" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="750" y="350" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
');

ALTER TABLE proc_def ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable insert for authenticated users only" ON "public"."proc_def"
AS PERMISSIVE FOR INSERT
TO authenticated
WITH CHECK ((EXISTS ( SELECT 1 FROM users WHERE ((users.id = auth.uid()) AND (users.is_admin = true)))));

CREATE POLICY "Enable read access for all users" ON "public"."proc_def"
AS PERMISSIVE FOR SELECT
TO public
USING (true);

drop table if exists proc_inst CASCADE;
create table
  public.proc_inst (
    id text not null,
    name text null,
    user_ids text[] null,
    agent_messages jsonb null,
    status text null,
    variables_data text null,
    constraint proc_inst_pkey primary key (id)
  ) tablespace pg_default;

drop table if exists public.chats CASCADE;
create table public.chats (
    uuid text not null,
    id text not null,
    messages jsonb null,
    constraint chats_pkey primary key (uuid)
) tablespace pg_default;

drop table if exists public.calendar CASCADE;
create table public.calendar (
  uid text not null,
  data jsonb null,
  constraint calendar_pkey primary key (uid)
) tablespace pg_default;

drop table if exists public.chat_rooms CASCADE;
create table public.chat_rooms (
  id text not null,
  participants jsonb not null,
  message jsonb null,
  name text null,
  constraint chat_rooms_pkey primary key (id)
) tablespace pg_default;

create view
  public.chat_room_chats as
select
  cr.id,
  cr.name,
  cr.participants,
  c.uuid,
  c.messages
from
  chat_rooms cr
  join chats c on cr.id = c.id;

drop table if exists public.proc_def_arcv CASCADE;
create table
  public.proc_def_arcv (
    arcv_id text not null,
    proc_def_id text not null,
    version text not null,
    snapshot text null,
    "timeStamp" timestamp without time zone null default current_timestamp,
    diff text null,
    message text null,
    constraint proc_def_arcv_pkey primary key (arcv_id)
  ) tablespace pg_default;

drop table if exists public.lock CASCADE;
create table
  public.lock (
    id text not null,
    user_id text null,
    constraint lock_pkey primary key (id)
  ) tablespace pg_default;

drop table if exists form_def CASCADE;
create table form_def (
  id text primary key,
  html text not null
) tablespace pg_default;
"""

        cursor.execute(sql_query)
        connection.commit()
        
        return "Table Created"
    except Exception as e:
        print(f"An error occurred: {e}")

async def update_db_settings(subdomain):
    try:
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
    name: str
    role: str
    email: Optional[str]
    image: Optional[str]
    content: Optional[str]
    timeStamp: Optional[datetime]

class ChatItem(BaseModel):
    id: str
    uuid: str
    messages: Optional[ChatMessage]

def fetch_chat_history(chat_room_id: str) -> List[ChatItem]:
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured for this request")
    response = supabase.table("chats").select("*").eq('id', chat_room_id).execute()
    chatHistory = []
    for chat in response.data:
        chatHistory.append(ChatItem(**chat))
    return chatHistory

def upsert_chat_message(chat_room_id: str, data: Dict[str, str]) -> None:
    try:
        output = data.get("output", None)
        if output:
            json_output = json.loads(output)
            message = ChatMessage(
                name="system",
                role="system",
                email="system@uengine.org",
                image="",
                content=json_output["description"],
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
