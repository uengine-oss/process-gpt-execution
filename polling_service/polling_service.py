import asyncio
import signal
import sys
from typing import Set

from database import (
    setting_database, fetch_workitem_with_submitted_status, 
    fetch_workitem_with_agent, upsert_workitem, cleanup_stale_consumers
)
from workitem_processor import handle_workitem, handle_agent_workitem

# 전역 변수로 현재 실행 중인 태스크들을 추적
running_tasks: Set[asyncio.Task] = set()
shutdown_event = asyncio.Event()

async def safe_handle_workitem(workitem):
    try:
        upsert_workitem({
            "id": workitem['id'],
            "log": f"'{workitem['activity_name']}' 업무를 실행합니다."
        }, workitem['tenant_id'])
        
        if workitem['status'] == "SUBMITTED":
            print(f"[DEBUG] Starting safe_handle_workitem for workitem: {workitem['id']}")
            await handle_workitem(workitem)
        elif workitem['agent_mode'] == "A2A" and workitem['status'] == "IN_PROGRESS":
            print(f"[DEBUG] Starting safe_handle_workitem for agent workitem: {workitem['id']}")
            await handle_agent_workitem(workitem)

    except Exception as e:
        print(f"[ERROR] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}")
        workitem['retry'] = workitem['retry'] + 1
        workitem['consumer'] = None
        if workitem['retry'] >= 3:
            workitem['status'] = "DONE"
            workitem['log'] = f"[Error] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}"
        else:
            workitem['log'] = f"실행하는 중 오류가 발생했습니다. 다시 시도하겠습니다."
        upsert_workitem(workitem, workitem['tenant_id'])
    finally:
        # 워크아이템 처리 완료 시 consumer 해제
        try:
            upsert_workitem({
                "id": workitem['id'],
                "consumer": None
            }, workitem['tenant_id'])
            print(f"[INFO] Released consumer lock for workitem: {workitem['id']}")
        except Exception as e:
            print(f"[ERROR] Failed to release consumer lock for workitem {workitem['id']}: {str(e)}")
        
        # 태스크 완료 시 추적 목록에서 제거
        if asyncio.current_task() in running_tasks:
            running_tasks.remove(asyncio.current_task())

async def polling_workitem():
    all_workitems = []
    submitted_workitems = fetch_workitem_with_submitted_status()
    if submitted_workitems:
        all_workitems.extend(submitted_workitems)
    agent_workitems = fetch_workitem_with_agent()
    if agent_workitems:
        all_workitems.extend(agent_workitems)

    if len(all_workitems) == 0:
        return

    tasks = []
    for workitem in all_workitems:
        # shutdown 이벤트가 설정되었으면 새 태스크를 시작하지 않음
        if shutdown_event.is_set():
            print("[INFO] Shutdown in progress, skipping new workitems")
            break
            
        task = asyncio.create_task(safe_handle_workitem(workitem))
        running_tasks.add(task)
        tasks.append(task)
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def cleanup_task():
    """주기적으로 오래된 consumer를 정리하는 태스크"""
    while not shutdown_event.is_set():
        try:
            cleanup_stale_consumers()
        except Exception as e:
            print(f"[ERROR] Cleanup task error: {e}")
        
        # 5분마다 정리 작업 실행
        await asyncio.sleep(300)

async def start_polling():
    setting_database()

    # cleanup 태스크 시작
    cleanup_task_obj = asyncio.create_task(cleanup_task())

    while not shutdown_event.is_set():
        try:
            await polling_workitem()
        except Exception as e:
            print(f"[Polling Loop Error] {e}")
        
        # shutdown 이벤트가 설정되었으면 루프 종료
        if shutdown_event.is_set():
            break
            
        await asyncio.sleep(5)
    
    # cleanup 태스크 취소
    cleanup_task_obj.cancel()
    try:
        await cleanup_task_obj
    except asyncio.CancelledError:
        pass

async def graceful_shutdown():
    """Graceful shutdown을 위한 함수"""
    print("[INFO] Starting graceful shutdown...")
    shutdown_event.set()
    
    # 진행 중인 모든 태스크가 완료될 때까지 대기
    if running_tasks:
        print(f"[INFO] Waiting for {len(running_tasks)} running tasks to complete...")
        await asyncio.gather(*running_tasks, return_exceptions=True)
        print("[INFO] All running tasks completed")
    
    print("[INFO] Graceful shutdown completed")

def signal_handler(signum, frame):
    """시그널 핸들러"""
    print(f"[INFO] Received signal {signum}, initiating graceful shutdown...")
    asyncio.create_task(graceful_shutdown())

def run_polling_service():
    try:
        # 시그널 핸들러 등록
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        print("[INFO] Starting polling service with graceful shutdown support...")
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("[INFO] Polling service stopped by user")
    except Exception as e:
        print(f"[ERROR] Polling service failed: {str(e)}")
        raise e

if __name__ == "__main__":
    run_polling_service() 