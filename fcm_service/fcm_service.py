import asyncio
import signal
from typing import Set
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from database import (
    setting_database, fetch_device_token, send_fcm_message,
    handle_new_notification, check_new_notifications
)

# 전역 변수로 현재 실행 중인 태스크들을 추적
running_tasks: Set[asyncio.Task] = set()
shutdown_event = asyncio.Event()

app = FastAPI(title="FCM Service", version="1.0.0")

class NotificationRequest(BaseModel):
    user_id: str
    title: str
    body: str
    type: str = "general"
    url: str = ""
    from_user_id: str = ""
    data: dict = {}

class DeviceTokenRequest(BaseModel):
    user_email: str
    device_token: str

@app.post("/send-notification")
async def send_notification(request: NotificationRequest):
    """FCM 푸시 알림 전송"""
    try:
        notification_data = {
            'title': request.title,
            'body': request.body,
            'type': request.type,
            'url': request.url,
            'from_user_id': request.from_user_id,
            'data': request.data
        }
        
        result = send_fcm_message(request.user_id, notification_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/device-token/{user_id}")
async def get_device_token(user_id: str):
    """사용자의 FCM 디바이스 토큰 조회"""
    try:
        token = fetch_device_token(user_id)
        return {"user_id": user_id, "device_token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy", "service": "fcm-service"}

async def notification_polling_task():
    """
    15초마다 새로운 알림을 체크하는 폴링 태스크
    """
    while not shutdown_event.is_set():
        try:
            await check_new_notifications()
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            print("[INFO] Notification polling task cancelled")
            break
        except Exception as e:
            print(f"[ERROR] Error in notification polling: {e}")
            await asyncio.sleep(15)

async def shutdown_handler():
    """Graceful shutdown 핸들러"""
    print("[INFO] Shutdown signal received")
    shutdown_event.set()
    
    # 실행 중인 모든 태스크 취소
    for task in running_tasks:
        if not task.done():
            task.cancel()
    
    # 모든 태스크가 완료될 때까지 대기
    if running_tasks:
        await asyncio.gather(*running_tasks, return_exceptions=True)
    
    print("[INFO] All tasks completed")

def setup_signal_handlers():
    """시그널 핸들러 설정"""
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda signum, frame: asyncio.create_task(shutdown_handler()))
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, lambda signum, frame: asyncio.create_task(shutdown_handler()))

async def run_fcm_service_async():
    """FCM 서비스 실행"""
    try:
        print("[INFO] Setting up database connection...")
        setting_database()
        
        print("[INFO] Starting notification polling task...")
        polling_task = asyncio.create_task(notification_polling_task())
        running_tasks.add(polling_task)
        
        # FastAPI 서버 실행 (백그라운드에서)
        config = uvicorn.Config(app=app, host="0.0.0.0", port=8666, log_level="info")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())
        running_tasks.add(server_task)
        
        print("[INFO] FCM Service started successfully")
        
        # shutdown 이벤트까지 대기
        await shutdown_event.wait()
        
    except Exception as e:
        print(f"[ERROR] Error in FCM service: {e}")
    finally:
        await shutdown_handler()

def run_fcm_service():
    """FCM 서비스 메인 실행 함수"""
    setup_signal_handlers()
    asyncio.run(run_fcm_service_async())