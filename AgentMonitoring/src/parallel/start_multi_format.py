#!/usr/bin/env python
import os
import asyncio
import warnings
from .flows.multi_format_flow import MultiFormatFlow
from .event_logging.crew_event_logger import GlobalContextManager
from .context_manager import context_manager

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
    flow_result = await flow.kickoff_async()
    
    # 두 개의 반환값 받기
    if isinstance(flow_result, tuple) and len(flow_result) == 2:
        legacy_format, new_format = flow_result
        print(f"✅ [start_multi_format] 두 가지 형식으로 결과 받음")
        print(f"   기존 형식: {type(legacy_format)}")
        print(f"   새 형식: {type(new_format)} - {len(new_format.get('reports', {}))}개 리포트, {len(new_format.get('forms', {}))}개 폼")
    else:
        # 호환성을 위한 fallback
        legacy_format = flow_result
        new_format = {}
        print(f"⚠️ [start_multi_format] 단일 형식 결과 - 호환성 모드")
    
    # 컨텍스트에 새 형식 결과 저장 (proc_inst_id와 activity_name으로 구분)
    if proc_inst_id and topic:
        print(f"🎯 [start_multi_format] 작업 완료, 컨텍스트 저장 시작")
        print(f"   proc_inst_id: {proc_inst_id}")
        print(f"   topic: {topic}")
        print(f"   저장할 데이터: 새 형식 ({len(new_format.get('reports', {}))}개 리포트, {len(new_format.get('forms', {}))}개 폼)")
        context_manager.save_context(proc_inst_id, topic, new_format)
        print(f"🎯 [start_multi_format] 컨텍스트 저장 완료")
    else:
        print(f"⚠️ [start_multi_format] 컨텍스트 저장 생략: proc_inst_id={proc_inst_id}, topic={topic}")
    
    # 기존 형식 반환 (todolist_poller에서 기대하는 형식)
    return legacy_format 