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
# diff 유틸리티 임포트
from .diff_util import compare_report_changes, extract_changes

# 로거 설정
logger = logging.getLogger("completed_poller")
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


async def fetch_oldest_completed_todolist(limit: int = 1) -> Optional[List[dict]]:
    """
    가장 오래된 Completed 항목 1건을 row-level lock(FOR UPDATE SKIP LOCKED) 후 반환합니다.
    반환 값에는 raw row, connection, cursor 번들을 포함합니다.
    """
    db_config = db_config_var.get()
    connection = psycopg2.connect(**db_config)
    connection.autocommit = False
    cursor = connection.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT *
        FROM todolist
        WHERE status = 'DONE'
        AND output IS NOT NULL
        AND draft IS NOT NULL
        AND feedback IS NULL
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


async def handle_completed_item(bundle: dict):
    """
    잠금된 completed todolist 항목을 처리합니다.
    """
    row = bundle['row']
    conn = bundle['connection']
    cur = bundle['cursor']

    try:
        logger.info(f"Processing completed todolist item: {row['id']}")
        
        # draft 필드값과 output 필드값 추출
        draft_value = row.get('draft')
        output_value = row.get('output')
        
        # Draft와 Output의 report 내용 비교 (unified diff)
        if draft_value and output_value:
            try:
                diff_result = compare_report_changes(
                    json.dumps(draft_value) if isinstance(draft_value, dict) else str(draft_value),
                    json.dumps(output_value) if isinstance(output_value, dict) else str(output_value)
                )
                
                if diff_result.get('unified_diff'):
                    logger.info("🔍 변화 감지!")
                    
                    # 변화된 부분만 추출
                    changes = extract_changes(diff_result.get('draft_content', ''), diff_result.get('output_content', ''))
                    
                    # 삭제된 내용
                    if changes['original_changes']:
                        deleted_lines = [line.strip() for line in changes['original_changes'].split('\n') if line.strip()]
                        if deleted_lines:
                            logger.info("❌ 삭제됨:")
                            for line in deleted_lines:
                                logger.info(f"     '{line}'")
                    
                    # 추가된 내용
                    if changes['modified_changes']:
                        added_lines = [line.strip() for line in changes['modified_changes'].split('\n') if line.strip()]
                        if added_lines:
                            logger.info("✅ 추가됨:")
                            for line in added_lines:
                                logger.info(f"     '{line}'")
                    
                    # 변화 요약
                    deleted_count = len([line for line in changes['original_changes'].split('\n') if line.strip()]) if changes['original_changes'] else 0
                    added_count = len([line for line in changes['modified_changes'].split('\n') if line.strip()]) if changes['modified_changes'] else 0
                    
                    if deleted_count == 0 and added_count == 0:
                        logger.info("📝 내용은 동일, 형식만 변경됨")
                    else:
                        logger.info(f"📊 요약: {deleted_count}줄 삭제, {added_count}줄 추가")
                    
                    # 🆕 에이전트별 피드백 생성
                    logger.info("🤖 에이전트 피드백 생성 중...")
                    try:
                        from agent_feedback_analyzer import AgentFeedbackAnalyzer
                        
                        analyzer = AgentFeedbackAnalyzer()
                        feedback_list = await analyzer.analyze_diff_and_generate_feedback(
                            json.dumps(draft_value) if isinstance(draft_value, dict) else str(draft_value),
                            json.dumps(output_value) if isinstance(output_value, dict) else str(output_value)
                        )
                        
                        if feedback_list:
                            logger.info("💡 === 에이전트별 피드백 ===")
                            for feedback in feedback_list:
                                logger.info(f"🤖 {feedback.get('agent', 'Unknown')}: {feedback.get('feedback', 'No feedback')}")
                            
                            # 피드백 결과를 feedback 필드에 저장
                            try:
                                cur.execute(
                                    "UPDATE todolist SET feedback = %s WHERE id = %s",
                                    (json.dumps(feedback_list, ensure_ascii=False), row['id'])
                                )
                                logger.info(f"💾 피드백 결과가 feedback 필드에 저장되었습니다: {len(feedback_list)}개")
                            except Exception as e:
                                logger.error(f"피드백 저장 중 오류: {e}")
                        else:
                            logger.info("💡 의미 있는 변화가 아니어서 피드백이 생성되지 않았습니다. (단순 형식 변경)")
                            
                            # 빈 피드백 결과도 저장
                            try:
                                cur.execute(
                                    "UPDATE todolist SET feedback = %s WHERE id = %s",
                                    (json.dumps([], ensure_ascii=False), row['id'])
                                )
                                logger.info("💾 빈 피드백 결과가 저장되었습니다.")
                            except Exception as e:
                                logger.error(f"빈 피드백 저장 중 오류: {e}")
                    except Exception as e:
                        logger.error(f"피드백 생성 중 오류: {e}")
                else:
                    logger.info("✅ 변화 없음 - 완전히 동일")
                    
            except Exception as e:
                logger.error(f"Error comparing draft and output: {e}")
        
        # 처리 완료 후 상태 업데이트 (예시)
        # cur.execute(
        #     "UPDATE todolist SET processed_at = NOW() WHERE id = %s",
        #     (row['id'],)
        # )
        
        conn.commit()

    except Exception as e:
        logger.error(f"Error handling completed item {row['id']}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


async def feedback_polling_loop(poll_interval: int = 10):
    """
    주기적으로 polling을 반복하는 태스크
    """
    while True:
        try:
            items = await fetch_oldest_completed_todolist()
            if items:
                for bundle in items:
                    await handle_completed_item(bundle)
            else:
                logger.info("No completed items to process")
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(feedback_polling_loop()) 