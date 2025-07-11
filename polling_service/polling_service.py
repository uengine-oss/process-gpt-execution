import asyncio
import signal
from typing import Set

from database import (
    setting_database, fetch_workitem_with_submitted_status, 
    fetch_workitem_with_agent, upsert_workitem, cleanup_stale_consumers,
    fetch_process_definition
)
from workitem_processor import handle_workitem, handle_agent_workitem, handle_service_workitem

# 전역 변수로 현재 실행 중인 태스크들을 추적
running_tasks: Set[asyncio.Task] = set()
shutdown_event = asyncio.Event()

async def safe_handle_workitem(workitem):
    try:
        # 워크아이템 처리 시작 로그
        try:
            upsert_workitem({
                "id": workitem['id'],
                "log": f"'{workitem['activity_name']}' 업무를 실행합니다."
            }, workitem['tenant_id'])
        except Exception as log_error:
            print(f"[WARNING] Failed to update workitem log: {log_error}")
        
        if workitem['status'] == "SUBMITTED":
            print(f"[DEBUG] Starting safe_handle_workitem for workitem: {workitem['id']}")
            process_definition = fetch_process_definition(workitem['proc_def_id'], workitem['tenant_id'])
            activities = process_definition.get('activities', [])
            
            task_type = 'userTask'
            for activity in activities:
                if activity.get('id') == workitem['activity_id']:
                    task_type = activity.get('type')
                    break
            
            if task_type == 'userTask' or task_type == 'scriptTask':
                await handle_workitem(workitem)
            elif task_type == 'serviceTask':
                await handle_service_workitem(workitem)
        elif workitem['agent_mode'] == "A2A" and workitem['status'] == "IN_PROGRESS":
            print(f"[DEBUG] Starting safe_handle_workitem for agent workitem: {workitem['id']}")
            await handle_agent_workitem(workitem)
        else:
            print(f"[WARNING] Unknown workitem status: {workitem['status']} for workitem: {workitem['id']}")

    except Exception as e:
        print(f"[ERROR] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}")
        try:
            workitem['retry'] = workitem.get('retry', 0) + 1
            workitem['consumer'] = None
            if workitem['retry'] >= 3:
                workitem['status'] = "DONE"
                workitem['log'] = f"[Error] Error in safe_handle_workitem for workitem {workitem['id']}: {str(e)}"
            else:
                workitem['log'] = f"실행하는 중 오류가 발생했습니다. 다시 시도하겠습니다. (시도 {workitem['retry']}/3)"
            upsert_workitem(workitem, workitem['tenant_id'])
        except Exception as update_error:
            print(f"[ERROR] Failed to update workitem error status: {update_error}")
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
    try:
        all_workitems = []
        
        # SUBMITTED 상태 워크아이템 조회
        try:
            submitted_workitems = fetch_workitem_with_submitted_status()
            if submitted_workitems:
                all_workitems.extend(submitted_workitems)
                print(f"[DEBUG] Found {len(submitted_workitems)} submitted workitems")
        except Exception as e:
            print(f"[ERROR] Failed to fetch submitted workitems: {str(e)}")
        
        # A2A 에이전트 워크아이템 조회
        try:
            agent_workitems = fetch_workitem_with_agent()
            if agent_workitems:
                all_workitems.extend(agent_workitems)
                print(f"[DEBUG] Found {len(agent_workitems)} agent workitems")
        except Exception as e:
            print(f"[ERROR] Failed to fetch agent workitems: {str(e)}")

        if len(all_workitems) == 0:
            return

        print(f"[INFO] Processing {len(all_workitems)} workitems")
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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # 결과 확인 및 로깅
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"[ERROR] Task {i} failed: {result}")
                else:
                    print(f"[DEBUG] Task {i} completed successfully")
    except Exception as e:
        print(f"[ERROR] Polling workitem failed: {str(e)}")
        # Supabase 연결 오류인 경우 잠시 대기
        if "Supabase client is not configured" in str(e) or "DB fetch failed" in str(e) or "network" in str(e).lower():
            print("[INFO] Database connection error, waiting before retry...")
            await asyncio.sleep(10)
        else:
            # 다른 오류의 경우 짧은 대기 후 재시도
            print("[INFO] Other error occurred, waiting before retry...")
            await asyncio.sleep(5)

async def cleanup_task():
    """주기적으로 오래된 consumer를 정리하는 태스크"""
    while not shutdown_event.is_set():
        try:
            cleanup_stale_consumers()
            print("[DEBUG] Cleanup task completed successfully")
        except Exception as e:
            print(f"[ERROR] Cleanup task error: {e}")
            # 오류 발생 시 짧은 대기 후 재시도
            await asyncio.sleep(60)
            continue
        
        # 정상적인 경우 5분 대기
        await asyncio.sleep(300)

async def start_polling():
    try:
        setting_database()
        print("[INFO] Database configuration completed")
    except Exception as e:
        print(f"[ERROR] Failed to configure database: {e}")
        return

    # cleanup 태스크 시작
    cleanup_task_obj = asyncio.create_task(cleanup_task())
    print("[INFO] Cleanup task started")

    while not shutdown_event.is_set():
        try:
            await polling_workitem()
        except Exception as e:
            print(f"[Polling Loop Error] {e}")
            # 오류 발생 시 짧은 대기
            await asyncio.sleep(5)
            continue
        
        if shutdown_event.is_set():
            break
            
        await asyncio.sleep(5)
    
    # cleanup 태스크 취소
    print("[INFO] Cancelling cleanup task...")
    cleanup_task_obj.cancel()
    try:
        await cleanup_task_obj
    except asyncio.CancelledError:
        print("[INFO] Cleanup task cancelled successfully")
    except Exception as e:
        print(f"[ERROR] Error cancelling cleanup task: {e}")

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