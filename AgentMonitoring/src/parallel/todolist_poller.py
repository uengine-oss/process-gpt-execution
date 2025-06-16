import asyncio
import logging
from typing import Optional, List
import socket
import sys
import os

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from database import db_config_var, supabase_client_var

# 같은 디렉토리의 파일을 임포트
from .start_multi_format import run_multi_format_generation  # main_multi_format.py가 아닌 start_multi_format.py를 사용
import psycopg2
from psycopg2.extras import RealDictCursor

# 로거 설정
logger = logging.getLogger("todolist_poller")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

async def fetch_pending_todolist(limit: int = 5) -> Optional[List[dict]]:
    """
    draft가 null이고 status가 DONE이 아닌 todolist 항목들을 가져옵니다.
    동시성 제어를 위해 consumer 필드를 사용합니다.
    """
    try:
        pod_id = socket.gethostname()
        db_config = db_config_var.get()

        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        query = """
            WITH locked_rows AS (
                SELECT id FROM todolist
                WHERE draft IS NULL 
                AND status != 'DONE'
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
        print(f"[DEBUG] fetch_pending_todolist rows: {rows}")

        connection.commit()
        cursor.close()
        connection.close()

        return rows if rows else None

    except Exception as e:
        logger.error(f"DB fetch failed: {str(e)}")
        return None

async def handle_todolist_item(item: dict):
    """
    개별 todolist 항목을 처리합니다.
    tool 필드에서 formHandler: 접두어를 제거하고 form_def 테이블에서 fields_json을 가져와 처리에 사용합니다.
    """
    try:
        logger.info(f"Processing todolist item: {item['id']}")
        print(f"[DEBUG] handle_todolist_item item: {item}")

        # tool 필드에서 formHandler: 제거하여 form_def id 추출
        tool_value = item.get('tool', '') or ''
        form_id = tool_value[12:] if tool_value.startswith('formHandler:') else tool_value

        # Supabase 클라이언트 가져오기
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")

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
        print(f"[DEBUG] handle_todolist_item user_info: {user_info}")

        # form_def에서 fields_json 조회
        response = supabase.table('form_def').select('fields_json').eq('id', form_id).execute()
        fields_json = None
        if response.data and len(response.data) > 0:
            fields_json = response.data[0].get('fields_json')
        print(f"[DEBUG] handle_todolist_item fields_json: {fields_json}")

        # 새로운 코드
        form_types = []
        if fields_json:
            for field in fields_json:
                field_type = field.get('type', '').lower()
                if field_type in ['report', 'slide', 'text']:
                    form_types.append({
                        'id': field.get('key'),
                        'type': field_type,
                        'key': field.get('key'),
                        'text': field.get('text', '')
                    })

        # 만약 form_types가 비어있다면 기본값 추가
        if not form_types:
            form_types = [{'id': form_id, 'type': 'default'}]

        print(f"[DEBUG] handle_todolist_item form_types: {form_types}")

        # MultiFormatFlow 실행 (fields_json 및 user_info, todo_id, form_id 전달)
        result = await run_multi_format_generation(
            topic=item.get('activity_name', ''),
            form_types=form_types,
            user_info=user_info,
            todo_id=item.get('id'),
            proc_inst_id=item.get('proc_inst_id'),
            form_id=form_id  # "formHandler:" 접두어가 제거된 실제 form_def id
        )
        
        # 처리 완료 후 consumer 해제 및 draft 업데이트
        supabase.table('todolist').update({
            'consumer': None,
            'draft': result
        }).eq('id', item['id']).execute()

    except Exception as e:
        logger.error(f"Error handling todolist item {item['id']}: {str(e)}")
        # 에러 발생 시에도 consumer 해제
        try:
            supabase = supabase_client_var.get()
            if supabase:
                supabase.table('todolist').update({
                    'consumer': None
                }).eq('id', item['id']).execute()
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up consumer for item {item['id']}: {str(cleanup_error)}")

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