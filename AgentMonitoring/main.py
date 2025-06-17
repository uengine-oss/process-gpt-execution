# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import os
import asyncio

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

os.environ["PYTHONIOENCODING"] = "utf-8"

# 환경에 따른 캐시 디렉토리 설정
CACHE_DIR = "/data" if os.path.exists("/.dockerenv") else "."
os.makedirs(CACHE_DIR, exist_ok=True)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from router import add_routes_to_app

app = FastAPI(
    title="AgentMonitoring Server",
    version="1.0",
    description="Agent Monitoring API Server",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)

# 라우터 추가
add_routes_to_app(app)

# polling 시작
from src.parallel.todolist_poller import todolist_polling_task

@app.on_event("startup")
async def start_background_tasks():
    # todolist 폴링 태스크 시작
    asyncio.create_task(todolist_polling_task())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8001) 