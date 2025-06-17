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

# 순서/대기 큐 관련 변수 및 함수 모두 제거

async def fetch_pending_todolist(limit: int = 1) -> Optional[List[dict]]:
    """
    start_date 기준 최신 1개 todolist 항목을 선점해서 반환합니다.
    """
    try:
        db_config = db_config_var.get()
        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        # 최신 1개만 선점 (draft = '{}')
        query = """
            UPDATE todolist
            SET draft = '{}'
            WHERE id = (
                SELECT id FROM todolist
                WHERE draft IS NULL
                ORDER BY start_date ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *;
        """
        cursor.execute(query)
        row = cursor.fetchone()
        connection.commit()
        cursor.close()
        connection.close()
        return [row] if row else None
    except Exception as e:
        logger.error(f"DB fetch failed: {str(e)}")
        return None

async def handle_todolist_item(item: dict):
    """
    개별 todolist 항목을 처리합니다.
    tool 필드에서 formHandler: 접두어를 제거하고 form_def 테이블에서 fields_json을 가져와 처리에 사용합니다.
    첫번째 시퀀스 액티비티면 context에 output 저장만 하고 draft만 빈 객체로.
    """
    try:
        logger.info(f"Processing todolist item: {item['id']}")
        print(f"[처리중] activity_name: {item.get('activity_name')}")

        # Supabase 클라이언트 가져오기
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")

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

        # proc_def에서 definition(시퀀스) 조회 및 첫번째 target(activity_id) 출력/비교
        proc_def_id = item.get('proc_def_id')
        is_first_activity = False
        if proc_def_id:
            proc_def_resp = supabase.table('proc_def').select('definition').eq('id', proc_def_id).execute()
            if proc_def_resp.data and len(proc_def_resp.data) > 0:
                definition_str = proc_def_resp.data[0].get('definition')
                try:
                    definition = json.loads(definition_str) if isinstance(definition_str, str) else definition_str
                    sequences = definition.get('sequences', [])
                    first_target = None
                    for seq in sequences:
                        if seq.get('source') == 'start_event':
                            first_target = seq.get('target')
                            break
                    print(f"[시퀀스 첫번째(실제 시작) target(activity_id)] {first_target}")
                    if first_target and first_target == item.get('activity_id'):
                        is_first_activity = True
                except Exception as e:
                    logger.error(f"Error parsing proc_def definition: {e}")

        if is_first_activity:
            # 첫 번째 액티비티면 output을 context에 저장하고 draft만 빈 객체로
            output_data = item.get('output', {})
            if item.get('proc_inst_id') and item.get('activity_name'):
                context_manager.save_context(
                    proc_inst_id=item.get('proc_inst_id'),
                    activity_name=item.get('activity_name'),
                    content=output_data
                )
            supabase.table('todolist').update({
                'draft': {}
            }).eq('id', item['id']).execute()
            print(f"[첫번째 액티비티] context 저장 및 draft 완료: {item.get('activity_name')}")
            return

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

    except Exception as e:
        logger.error(f"Error handling todolist item {item['id']}: {str(e)}")
        

async def todolist_polling_task():
    """
    todolist 테이블을 주기적으로 폴링하는 태스크
    """
    while True:
        try:
            items = await fetch_pending_todolist()
            if items:
                for item in items:
                    await handle_todolist_item(item)
            await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"Polling error: {str(e)}")
            await asyncio.sleep(15) 