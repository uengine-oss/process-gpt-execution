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

drop table if exists public.users CASCADE;
create table public.users (
    id uuid not null primary key,
    username text null,
    profile text null default '/src/assets/images/profile/defaultUser.png'::text,
    email text null,
    is_admin boolean not null default false,
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
  'vacation_request_process', '휴가 신청 프로세스', '{"data": [{"name": "휴가 신청 사유","type": "Text","description": "휴가 신청 사유 description"},{"name": "휴가 시작일","type": "Date","description": "휴가 시작일 description"},{"name": "휴가 복귀일","type": "Date","description": "휴가 복귀일 description"}],"roles": [{"name": "직원","process": "vacation_request_process","resolutionRule": "system"},{"name": "팀장","process": "vacation_request_process","resolutionRule": "system"},{"name": "인사팀","process": "vacation_request_process","resolutionRule": "system"}],"events": [{"id": "start_event","name": "Start Event","role": "직원","type": "startEvent","process": "vacation_request_process","properties": "{}","description": "start event"},{"id": "end_event","name": "End Event","role": "직원","type": "endEvent","process": "vacation_request_process","properties": "{}","description": "start event"}],"gateways": [],"sequences": [{"id": "SequenceFlow_start_event_request_vacation_activity","source": "start_event","target": "request_vacation_activity","condition": "","properties": "{\"condition\":\"\"}"},{"id": "SequenceFlow_request_vacation_activity_approve_vacation_by_team_lead","source": "request_vacation_activity","target": "approve_vacation_by_team_lead","condition": "","properties": "{\"condition\":\"\"}"},{"id": "SequenceFlow_approve_vacation_by_team_lead_notify_vacation_decision","source": "approve_vacation_by_team_lead","target": "notify_vacation_decision","condition": "","properties": "{\"condition\":\"\"}"},{"id": "SequenceFlow_notify_vacation_decision_end_event","source": "notify_vacation_decision","target": "end_event","condition": "","properties": "{\"condition\":\"\"}"}],"activities": [{"id": "request_vacation_activity","name": "휴가 신청","role": "직원","tool": "","type": "userTask","process": "vacation_request_process","inputData": ["휴가 신청 사유","휴가 시작일","휴가 복귀일"],"outputData": ["휴가 신청 사유","휴가 시작일","휴가 복귀일"],"properties": "{\"parameters\":[{\"argument\":{\"text\":\"휴가 신청 사유\"},\"variable\":{\"name\":\"휴가 신청 사유\"},\"direction\":\"OUT\"},{\"argument\":{\"text\":\"휴가 시작일\"},\"variable\":{\"name\":\"휴가 시작일\"},\"direction\":\"OUT\"},{\"argument\":{\"text\":\"휴가 복귀일\"},\"variable\":{\"name\":\"휴가 복귀일\"},\"direction\":\"OUT\"},{\"argument\":{\"text\":\"휴가 신청 사유\"},\"variable\":{\"name\":\"휴가 신청 사유\"},\"direction\":\"IN\"},{\"argument\":{\"text\":\"휴가 시작일\"},\"variable\":{\"name\":\"휴가 시작일\"},\"direction\":\"IN\"},{\"argument\":{\"text\":\"휴가 복귀일\"},\"variable\":{\"name\":\"휴가 복귀일\"},\"direction\":\"IN\"}]}","description": "휴가 신청 description","instruction": "휴가 신청서를 작성하여 제출하세요."},{"id": "approve_vacation_by_team_lead","name": "휴가 승인","role": "팀장","tool": "","type": "userTask","process": "vacation_request_process","inputData": [],"outputData": [],"properties": "{\"parameters\":[]}","description": "휴가 승인 description","instruction": "팀장님은 휴가 신청서를 확인 후 승인 해주세요."},{"id": "notify_vacation_decision","name": "휴가 허용 여부 통지","role": "인사팀","tool": "","type": "userTask","process": "vacation_request_process","inputData": [],"outputData": [],"properties": "{\"parameters\":[]}","description": "휴가 허용 여부 통지 description","instruction": "휴가 허용 여부를 통지 해주세요."}],"description": "process.description","participants": {"id": "Participant","name": "Participant","processRef": "vacation_request_process"},"processDefinitionId": "vacation_request_process","processDefinitionName": "휴가 신청"}', '<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:uengine="http://uengine" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" id="Definitions_vacation_request_process" targetNamespace="http://bpmn.io/schema/bpmn" exporter="Custom BPMN Modeler" exporterVersion="1.0">
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="Participant" name="Participant" processRef="vacation_request_process" />
  </bpmn:collaboration>
  <bpmn:process id="vacation_request_process" isExecutable="true">
    <bpmn:extensionElements>
      <uengine:properties>
        <uengine:json>{"instanceNamePattern":"&lt;%=roles.직원.endpoint%&gt;_휴가신청서"}</uengine:json>
        <uengine:variable name="휴가 신청 사유" type="Text" />
        <uengine:variable name="휴가 시작일" type="Date" />
        <uengine:variable name="휴가 복귀일" type="Date" />
      </uengine:properties>
    </bpmn:extensionElements>
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_0" name="직원">
        <bpmn:flowNodeRef>request_vacation_activity</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_1" name="팀장">
        <bpmn:flowNodeRef>approve_vacation_by_team_lead</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_2" name="인사팀">
        <bpmn:flowNodeRef>notify_vacation_decision</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:sequenceFlow id="SequenceFlow_start_event_request_vacation_activity" name="" sourceRef="start_event" targetRef="request_vacation_activity">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_request_vacation_activity_approve_vacation_by_team_lead" name="" sourceRef="request_vacation_activity" targetRef="approve_vacation_by_team_lead">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_approve_vacation_by_team_lead_notify_vacation_decision" name="" sourceRef="approve_vacation_by_team_lead" targetRef="notify_vacation_decision">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="SequenceFlow_notify_vacation_decision_end_event" name="" sourceRef="notify_vacation_decision" targetRef="end_event">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"condition":""}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
    </bpmn:sequenceFlow>
    <bpmn:startEvent id="start_event" name="Start Event" />
    <bpmn:endEvent id="end_event" name="End Event" />
    <bpmn:userTask id="request_vacation_activity" name="휴가 신청">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[{"argument":{"text":"휴가 신청 사유"},"variable":{"name":"휴가 신청 사유"},"direction":"OUT"},{"argument":{"text":"휴가 시작일"},"variable":{"name":"휴가 시작일"},"direction":"OUT"},{"argument":{"text":"휴가 복귀일"},"variable":{"name":"휴가 복귀일"},"direction":"OUT"},{"argument":{"text":"휴가 신청 사유"},"variable":{"name":"휴가 신청 사유"},"direction":"IN"},{"argument":{"text":"휴가 시작일"},"variable":{"name":"휴가 시작일"},"direction":"IN"},{"argument":{"text":"휴가 복귀일"},"variable":{"name":"휴가 복귀일"},"direction":"IN"}]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_start_event_request_vacation_activity</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_request_vacation_activity_approve_vacation_by_team_lead</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:userTask id="approve_vacation_by_team_lead" name="휴가 승인">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_request_vacation_activity_approve_vacation_by_team_lead</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_approve_vacation_by_team_lead_notify_vacation_decision</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:userTask id="notify_vacation_decision" name="휴가 허용 여부 통지">
      <bpmn:extensionElements>
        <uengine:properties>
          <uengine:json>{"parameters":[]}</uengine:json>
        </uengine:properties>
      </bpmn:extensionElements>
      <bpmn:incoming>SequenceFlow_approve_vacation_by_team_lead_notify_vacation_decision</bpmn:incoming>
      <bpmn:outgoing>SequenceFlow_notify_vacation_decision_end_event</bpmn:outgoing>
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
      <bpmndi:BPMNShape id="BPMNShape_request_vacation_activity" bpmnElement="request_vacation_activity">
        <dc:Bounds x="240" y="110" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_approve_vacation_by_team_lead" bpmnElement="approve_vacation_by_team_lead">
        <dc:Bounds x="400" y="210" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="BPMNShape_notify_vacation_decision" bpmnElement="notify_vacation_decision">
        <dc:Bounds x="560" y="310" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="BPMNEdge_start_event_request_vacation_activity" bpmnElement="SequenceFlow_start_event_request_vacation_activity">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="194" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="240" y="150" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_request_vacation_activity_approve_vacation_by_team_lead" bpmnElement="SequenceFlow_request_vacation_activity_approve_vacation_by_team_lead">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="340" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="365" y="150" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="365" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="400" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="400" y="250" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_approve_vacation_by_team_lead_notify_vacation_decision" bpmnElement="SequenceFlow_approve_vacation_by_team_lead_notify_vacation_decision">
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="500" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="525" y="250" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="525" y="350" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="560" y="350" />
        <di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="560" y="350" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="BPMNEdge_notify_vacation_decision_end_event" bpmnElement="SequenceFlow_notify_vacation_decision_end_event">
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

-- worklist view
create view public.worklist as
select
  t.*,
  p.name as proc_inst_name
from
  todolist t
  join public.proc_inst p on t.proc_inst_id = p.id;

-- notifications table & trigger
drop table if exists notifications CASCADE;
create table notifications (
  id text primary key,
  user_id text,
  title text,
  type text,
  description text,
  is_checked boolean null default false,
  time_stamp timestamp with time zone null default now(),
  url text
);

create or replace function handle_todolist_change()
returns trigger as $$
declare
    proc_inst_name text;
begin
    if (TG_OP = 'INSERT') then
        select name into proc_inst_name from proc_inst where id = NEW.proc_inst_id;
        
        insert into notifications (id, user_id, title, type, description, is_checked, time_stamp, url)
        values (
            gen_random_uuid(),
            NEW.user_id,
            NEW.activity_name,
            'workitem',
            coalesce(proc_inst_name, ''),
            case when NEW.status = 'DONE' then true else false end,
            now(),
            '/todolist/' || NEW.id
        )
        on conflict (id) do update
        set
            user_id = EXCLUDED.user_id,
            title = EXCLUDED.title,
            type = EXCLUDED.type,
            description = EXCLUDED.description,
            is_checked = EXCLUDED.is_checked,
            time_stamp = EXCLUDED.time_stamp,
            url = EXCLUDED.url;
    end if;
    return null;
end;
$$ language plpgsql;

create trigger todolist_change_trigger
after insert on todolist
for each row
execute function handle_todolist_change();

create or replace function handle_chat_insert()
returns trigger as $$
declare
    chat_room_participant jsonb;
    participant_email text;
    participant_record record;
    chat_room_name text;
begin
    -- Fetch the chat room name
    select name into chat_room_name from public.chat_rooms where id = NEW.id;

    for participant_record in
        select jsonb_array_elements(participants) as p
        from public.chat_rooms
        where id = NEW.id
    loop
        chat_room_participant := participant_record.p;
        
        if chat_room_participant->>'username' != 'System' and chat_room_participant->>'email' != NEW.messages->>'email' then
            participant_email := chat_room_participant->>'email';
            
            insert into notifications (id, user_id, title, type, description, is_checked, time_stamp, url)
            values (
                gen_random_uuid(),
                participant_email,
                NEW.messages->>'content',
                'chat',
                chat_room_name,  -- Use chat room name as description
                false,
                now(),
                '/chats?id=' || NEW.id
            )
            on conflict (id) do update
            set
                user_id = EXCLUDED.user_id,
                title = EXCLUDED.title,
                time_stamp = EXCLUDED.time_stamp,
                is_checked = EXCLUDED.is_checked,
                url = EXCLUDED.url;
        end if;
    end loop;

    return null;
end;
$$ language plpgsql;

create trigger chat_insert_trigger
after insert on public.chats
for each row
execute function handle_chat_insert();