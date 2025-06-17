from fastapi import APIRouter, FastAPI
from datetime import datetime

router = APIRouter()

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AgentMonitoring"
    }

def add_routes_to_app(app: FastAPI):
    app.include_router(router, prefix="/api")