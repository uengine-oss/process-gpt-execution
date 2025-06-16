import asyncio
import logging
from typing import Optional, List
import socket
import sys
import os
import json

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from database import db_config_var, supabase_client_var

# 같은 디렉토리의 파일을 임포트
from .start_multi_format import run_multi_format_generation  # main_multi_format.py가 아닌 start_multi_format.py를 사용
from .context_manager import context_manager
import psycopg2
from psycopg2.extras import RealDictCursor

# 로거 설정
logger = logging.getLogger("todolist_poller")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# 🎯 순서 관리 시스템
order_system = {}  # {proc_inst_id: {액티비티_id: 번호, 현재_순서번호: 0}}
waiting_queue = {}  # {proc_inst_id: [대기중인 todolist 항목들]}

def update_order_system(rows: List[dict], proc_def_rows: List[dict]):
    """
    순서 시스템을 업데이트합니다.
    proc_def_id로 순서 정보만 가져와서 바로 proc_inst_id를 키로 저장
    """
    global order_system
    
    # proc_def_id별로 definition 매핑
    proc_def_map = {row['id']: row['definition'] for row in proc_def_rows}
    
    # 새로운 proc_inst_id들에 대해 순서 시스템 초기화
    for row in rows:
        proc_inst_id = row.get('proc_inst_id')
        proc_def_id = row.get('proc_def_id')
        
        if proc_inst_id not in order_system:
            # proc_def_id로 순서 정보 가져와서 바로 proc_inst_id에 저장
            if proc_def_id in proc_def_map:
                try:
                    definition_str = proc_def_map[proc_def_id]
                    definition = json.loads(definition_str) if isinstance(definition_str, str) else definition_str
                    sequences = definition.get('sequences', [])
                    
                    # 🔍 sequences 전체 내용 확인
                    print(f"[sequences] {[s.get('target') for s in sequences]}")
                    
                    # sequences에서 target 순서 추출 (게이트웨이 제외 + 중복 제거)
                    order_info = {'현재_순서번호': 0}
                    order_index = 0
                    seen_activities = set()
                    
                    for i, seq in enumerate(sequences):
                        target = seq.get('target')
                        if target and not target.startswith('gateway_'):  # 게이트웨이 제외
                            if target not in seen_activities:  # 🎯 중복 제거
                                order_info[target] = order_index
                                seen_activities.add(target)
                                print(f"[filtered] {i} -> {target} (순서: {order_index})")
                                order_index += 1
                            else:
                                print(f"[duplicate] {i} -> {target} (이미 존재, 건너뜀)")
                        elif target:
                            print(f"[gateway] {i} -> {target} (건너뜀)")
                    
                    order_system[proc_inst_id] = order_info
                    
                    # 🎯 총 순서도 출력
                    activity_order_log = [f"{activity_id}:{order_num}" for activity_id, order_num in order_info.items() if activity_id != '현재_순서번호']
                    print(f"[순서도] {', '.join(activity_order_log)}")
                    
                except (json.JSONDecodeError, KeyError) as e:
                    order_system[proc_inst_id] = {'현재_순서번호': 0}
            else:
                order_system[proc_inst_id] = {'현재_순서번호': 0}
                
            # 대기 큐도 초기화
            if proc_inst_id not in waiting_queue:
                waiting_queue[proc_inst_id] = []

def can_process_now(item: dict) -> bool:
    """
    현재 항목이 처리 가능한지 확인합니다.
    """
    proc_inst_id = item.get('proc_inst_id')
    activity_id = item.get('activity_id')
    
    if proc_inst_id not in order_system:
        return False
    
    current_order = order_system[proc_inst_id].get('현재_순서번호', 0)
    activity_order = order_system[proc_inst_id].get(activity_id, 999)
    
    return current_order == activity_order

def is_last_order(proc_inst_id: str) -> bool:
    """
    현재 순서가 마지막 순서인지 확인합니다.
    """
    if proc_inst_id not in order_system:
        return False
    
    current_order = order_system[proc_inst_id].get('현재_순서번호', 0)
    
    # 모든 액티비티의 순서번호 중 최대값 찾기
    max_order = -1
    for key, value in order_system[proc_inst_id].items():
        if key != '현재_순서번호' and isinstance(value, int):
            max_order = max(max_order, value)
    
    return current_order == max_order

def advance_order(proc_inst_id: str):
    """
    해당 프로세스 인스턴스의 순서를 다음으로 진행합니다.
    """
    if proc_inst_id in order_system:
        # 🎯 advance 하기 전에 현재가 마지막인지 체크
        current_order = order_system[proc_inst_id]['현재_순서번호']
        is_last = is_last_order(proc_inst_id)
        
        if is_last:
            # 🎯 메모리 정리: 완료된 프로세스 인스턴스 제거
            if proc_inst_id in order_system:
                del order_system[proc_inst_id]
            
            if proc_inst_id in waiting_queue:
                del waiting_queue[proc_inst_id]
                
        else:
            # 순서 진행
            order_system[proc_inst_id]['현재_순서번호'] += 1

def add_to_waiting_queue(item: dict):
    """
    대기 큐에 항목을 추가합니다.
    """
    proc_inst_id = item.get('proc_inst_id')
    if proc_inst_id not in waiting_queue:
        waiting_queue[proc_inst_id] = []
    
    # 중복 방지
    if not any(existing['id'] == item['id'] for existing in waiting_queue[proc_inst_id]):
        waiting_queue[proc_inst_id].append(item)

def check_waiting_queue() -> List[dict]:
    """
    대기 큐에서 처리 가능한 항목들을 찾아 반환합니다.
    """
    ready_items = []
    
    for proc_inst_id, items in waiting_queue.items():
        items_to_remove = []
        
        for item in items:
            if can_process_now(item):
                ready_items.append(item)
                items_to_remove.append(item)
        
        # 처리 가능한 항목들을 대기 큐에서 제거
        for item in items_to_remove:
            waiting_queue[proc_inst_id].remove(item)
    
    return ready_items

async def fetch_pending_todolist(limit: int = 10) -> Optional[List[dict]]:
    """
    🎯 핵심: 순서 관리 시스템을 통한 체계적인 처리
    """
    try:
        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        # 🎯 간단한 방식: draft = {} 설정으로 선점
        query = """
            UPDATE todolist 
            SET draft = '{}'
            WHERE id IN (
                SELECT id FROM todolist 
                WHERE draft IS NULL 
                LIMIT %s
            )
            RETURNING *;
        """
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        connection.commit()
        
        if not rows:
            cursor.close()
            connection.close() 
            # 대기 큐만 확인
            ready_from_queue = check_waiting_queue()
            return ready_from_queue if ready_from_queue else None

        # 2단계: proc_def 정보 가져오기
        proc_def_ids = list(set([row.get('proc_def_id') for row in rows if row.get('proc_def_id')]))
        
        proc_def_query = """
            SELECT id, definition FROM proc_def
            WHERE id = ANY(%s)
        """
        cursor.execute(proc_def_query, (proc_def_ids,))
        proc_def_rows = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # 3단계: 순서 시스템 업데이트
        update_order_system(rows, proc_def_rows)
        
        # 4단계: 처리 가능한 항목과 대기 항목 분류
        ready_items = []
        
        for item in rows:
            if can_process_now(item):
                ready_items.append(item)
            else:
                add_to_waiting_queue(item)
        
        # 5단계: 대기 큐에서도 처리 가능한 항목 확인
        ready_from_queue = check_waiting_queue()
        ready_items.extend(ready_from_queue)
        

        
        return ready_items[:limit] if ready_items else None

    except Exception as e:
        logger.error(f"DB fetch failed: {str(e)}")
        return None

async def handle_todolist_item(item: dict, is_first_item: bool = False):
    """
    개별 todolist 항목을 처리합니다.
    tool 필드에서 formHandler: 접두어를 제거하고 form_def 테이블에서 fields_json을 가져와 처리에 사용합니다.
    """
    try:
        logger.info(f"Processing todolist item: {item['id']} (first_item: {is_first_item})")

        # Supabase 클라이언트 가져오기
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")

        # 정렬된 첫번째 항목(순서 0)만 output 필드 직접 저장
        if is_first_item:
            output_data = item.get('output', {})
            
            # context_manager에 저장
            if item.get('proc_inst_id') and item.get('activity_name'):
                context_manager.save_context(
                    proc_inst_id=item.get('proc_inst_id'),
                    activity_name=item.get('activity_name'),
                    content=output_data
                )
            
            # todolist 완료 처리 (draft에는 빈 JSON 객체 저장)
            supabase.table('todolist').update({
                'draft': {}  # 첫 번째 항목은 빈 JSON 객체
            }).eq('id', item['id']).execute()
            
            # 🎯 순서 진행
            advance_order(item.get('proc_inst_id'))
            return

        # 1번째 이후 순서는 기존 AI 처리 로직 수행
        # tool 필드에서 formHandler: 제거하여 form_def id 추출
        tool_value = item.get('tool', '') or ''
        form_id = tool_value[12:] if tool_value.startswith('formHandler:') else tool_value

        # user_info 조회: email로 username 검색
        user_email = item.get('user_id')
        user_resp = supabase.table('users').select('username').eq('email', user_email).execute()
        user_name = user_resp.data[0]['username'] if user_resp.data and len(user_resp.data) > 0 else None
        user_info = {
            'email': user_email,
            'name': user_name,
            'department': '인사팀',  # 하드코딩
            'position': '사원'      # 하드코딩
        }

        # form_def에서 fields_json 조회
        response = supabase.table('form_def').select('fields_json').eq('id', form_id).execute()
        fields_json = None
        if response.data and len(response.data) > 0:
            fields_json = response.data[0].get('fields_json')

        # 새로운 코드
        form_types = []
        if fields_json:
            for field in fields_json:
                field_type = field.get('type', '').lower()
                # textarea도 text로 간주
                if field_type in ['report', 'slide', 'text', 'textarea']:
                    normalized_type = 'text' if field_type == 'textarea' else field_type
                    form_types.append({
                        'id': field.get('key'),
                        'type': normalized_type,
                        'key': field.get('key'),
                        'text': field.get('text', '')
                    })

        # 만약 form_types가 비어있다면 기본값 추가
        if not form_types:
            form_types = [{'id': form_id, 'type': 'default'}]


        # MultiFormatFlow 실행 (fields_json 및 user_info, todo_id, form_id 전달)
        result = await run_multi_format_generation(
            topic=item.get('activity_name', ''),
            form_types=form_types,
            user_info=user_info,
            todo_id=item.get('id'),
            proc_inst_id=item.get('proc_inst_id'),
            form_id=form_id  # "formHandler:" 접두어가 제거된 실제 form_def id
        )
        
        # 처리 완료 후 draft 업데이트
        supabase.table('todolist').update({
            'draft': result
        }).eq('id', item['id']).execute()
        
        # 🎯 순서 진행
        advance_order(item.get('proc_inst_id'))

    except Exception as e:
        logger.error(f"Error handling todolist item {item['id']}: {str(e)}")
        # 🎯 에러 발생 시 draft를 NULL로 되돌려서 재처리 가능하게 함
        try:
            supabase = supabase_client_var.get()
            if supabase:
                supabase.table('todolist').update({
                    'draft': None
                }).eq('id', item['id']).execute()
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up draft for item {item['id']}: {str(cleanup_error)}")

async def todolist_polling_task():
    """
    todolist 테이블을 주기적으로 폴링하는 태스크
    """
    while True:
        try:
            items = await fetch_pending_todolist()
            if items:
                for item in items:
                    # 현재 순서 확인
                    proc_inst_id = item.get('proc_inst_id')
                    current_order = order_system.get(proc_inst_id, {}).get('현재_순서번호', 0)
                    is_first_item = current_order == 0
                    
                    # 🎯 현재번호와 액티비티이름 출력
                    print(f"[처리] 현재번호: {current_order}, 액티비티: {item.get('activity_name')}")
                    
                    await handle_todolist_item(item, is_first_item)
            
            await asyncio.sleep(15)
            
        except Exception as e:
            logger.error(f"Polling error: {str(e)}")
            await asyncio.sleep(15) 