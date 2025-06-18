import asyncio
import logging
import json
import os
import sys
from typing import Optional, List
from contextvars import ContextVar
from dotenv import load_dotenv

import psycopg2
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
# 같은 디렉토리의 파일을 임포트
from .start_multi_format import run_multi_format_generation
from .context_manager import context_manager

# 로거 설정
logger = logging.getLogger("todolist_poller")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ContextVar 로 설정 저장
db_config_var = ContextVar('db_config', default={})
supabase_client_var = ContextVar('supabase', default=None)


def setting_database():
    try:
        if os.getenv("ENV") != "production":
            load_dotenv()

        # Supabase 클라이언트 설정
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase: Client = create_client(supabase_url, supabase_key)
        supabase_client_var.set(supabase)

        # PostgreSQL 접속 정보 설정
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


# 초기 설정
setting_database()


async def fetch_pending_todolist(limit: int = 1) -> Optional[List[dict]]:
    """
    start_date 기준 최신 1개 todolist 항목을 row-level lock(FOR UPDATE SKIP LOCKED) 후 반환합니다.
    반환 값에는 raw row, connection, cursor 번들을 포함합니다.
    """
    db_config = db_config_var.get()
    connection = psycopg2.connect(**db_config)
    connection.autocommit = False
    cursor = connection.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT *
        FROM todolist
        WHERE agent_mode = 'DRAFT'
          AND draft IS NULL
          AND status = 'IN_PROGRESS'
        ORDER BY start_date ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """, (limit,))

    row = cursor.fetchone()
    if row:
        return [{ 'row': row, 'connection': connection, 'cursor': cursor }]
    else:
        cursor.close()
        connection.close()
        return None


async def handle_todolist_item(bundle: dict):
    """
    잠금된 todolist 항목을 처리합니다.
    - 먼저 같은 proc_inst_id에 대해 status='DONE'인 모든 row를 조회하여 컨텍스트에 저장
    - 이후 run_multi_format_generation 실행 및 draft 업데이트
    """
    row = bundle['row']
    conn = bundle['connection']
    cur = bundle['cursor']

    try:
        logger.info(f"Processing todolist item: {row['id']}")

        proc_inst_id = row.get('proc_inst_id')
        # 1) 이전에 완료된(DONE) 항목들을 컨텍스트에 저장
        done_cursor = conn.cursor(cursor_factory=RealDictCursor)
        done_cursor.execute(
            "SELECT * FROM todolist WHERE proc_inst_id = %s AND status = 'DONE'",
            (proc_inst_id,)
        )
        done_rows = done_cursor.fetchall()
        for done in done_rows:
            if done.get('activity_name'):
                print(f"Saving context for {done.get('activity_name')}")
                context_manager.save_context(
                    proc_inst_id=proc_inst_id,
                    activity_name=done.get('activity_name'),
                    content=done.get('output', {})
                )
        done_cursor.close()

        # 2) IN_PROGRESS 항목에 대한 MultiFormatFlow 실행
        tool_val = row.get('tool', '') or ''
        form_id = tool_val[12:] if tool_val.startswith('formHandler:') else tool_val

        # user_info 조회
        supabase = supabase_client_var.get()
        user_email = row.get('user_id')
        user_resp = supabase.table('users').select('username').eq('email', user_email).execute()
        user_name = user_resp.data[0]['username'] if user_resp.data else None
        user_info = {
            'email': user_email,
            'name': user_name,
            'department': '인사팀',
            'position': '사원'
        }

        # form_def 조회
        resp = supabase.table('form_def').select('fields_json').eq('id', form_id).execute()
        fields_json = resp.data[0].get('fields_json') if resp.data else None

        # 필드 타입 정규화
        form_types = []
        if fields_json:
            for f in fields_json:
                t = f.get('type', '').lower()
                norm = t if t in ['report', 'slide'] else 'text'
                form_types.append({
                    'id': f.get('key'),
                    'type': norm,
                    'key': f.get('key'),
                    'text': f.get('text', '')
                })
        if not form_types:
            form_types = [{'id': form_id, 'type': 'default'}]

        # MultiFormatFlow 실행
        result = await run_multi_format_generation(
            topic=row.get('activity_name', ''),
            form_types=form_types,
            user_info=user_info,
            todo_id=row.get('id'),
            proc_inst_id=proc_inst_id,
            form_id=form_id
        )

        # 3) draft 업데이트 및 COMMIT
        cur.execute(
            "UPDATE todolist SET draft = %s WHERE id = %s",
            (json.dumps(result), row['id'])
        )
        conn.commit()

    except Exception as e:
        logger.error(f"Error handling item {row['id']}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


async def todolist_polling_task():
    """
    주기적으로 fetch -> handle 을 수행하는 태스크
    """
    while True:
        try:
            items = await fetch_pending_todolist()
            if items:
                for bundle in items:
                    await handle_todolist_item(bundle)
        except Exception as e:
            logger.error(f"Polling error: {e}")
        await asyncio.sleep(15)
