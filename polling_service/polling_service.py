import asyncio

from database import (
    setting_database, fetch_workitem_with_submitted_status, 
    fetch_workitem_with_agent, upsert_workitem
)
from workitem_processor import handle_workitem, handle_agent_workitem

semaphore = asyncio.Semaphore(3)

async def limited_safe_handle_workitem(workitem):
    async with semaphore:
        await safe_handle_workitem(workitem)

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
        task = asyncio.create_task(limited_safe_handle_workitem(workitem))
        tasks.append(task)
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def start_polling():
    setting_database()

    while True:
        try:
            await polling_workitem()
        except Exception as e:
            print(f"[Polling Loop Error] {e}")
        await asyncio.sleep(10)

def run_polling_service():
    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("[INFO] Polling service stopped by user")
    except Exception as e:
        print(f"[ERROR] Polling service failed: {str(e)}")
        raise e

if __name__ == "__main__":
    run_polling_service() 