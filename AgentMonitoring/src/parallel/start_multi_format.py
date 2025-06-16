#!/usr/bin/env python
import os
import asyncio
import warnings
from AgentMonitoring.src.parallel.flows.multi_format_flow import MultiFormatFlow
from AgentMonitoring.src.parallel.event_logging.crew_event_logger import GlobalContextManager

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

async def run_multi_format_generation(topic: str, form_types: list = None, user_info: dict = None, todo_id: str = None, proc_inst_id: str = None, form_id: str = None):
    """
    간단한 멀티 포맷 컨텐츠 생성 실행
    """
    print(f"Processing topic: {topic}")
    
    # Global context 설정 for event logging
    form_id_context = form_id or (form_types[0].get('id') if form_types and isinstance(form_types, list) and form_types else None)
    GlobalContextManager.set_context(output_type='todolist', form_id=form_id_context, todo_id=todo_id, proc_inst_id=proc_inst_id)
    
    # 기본 form type 설정
    if not form_types:
        form_types = [{'type': 'default'}]
    
    # Flow 초기화
    flow = MultiFormatFlow(
        enable_supabase_logging=True,
        enable_file_logging=True
    )
    
    # 상태 설정
    flow.state.topic = topic
    flow.state.form_types = form_types
    flow.state.user_info = user_info or {}
    # todolist item 및 프로세스 인스턴스 ID를 상태에 저장
    flow.state.todo_id = todo_id
    flow.state.proc_inst_id = proc_inst_id
    flow.state.form_id = form_id  # form_id 추가
    
    # 실행
    result = await flow.kickoff_async()
    
    return result 