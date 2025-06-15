from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any
from uuid import uuid4
from dotenv import load_dotenv
from a2a_agent_client import process_a2a_message, cleanup_resources
from mem0_agent_client import process_mem0_message
from fastapi.responses import StreamingResponse, JSONResponse

load_dotenv()

def add_routes_to_app(app):
    app.add_api_route("/multi-agent/chat", chat_message, methods=["POST"])
    app.add_api_route("/multi-agent/health-check", health_check, methods=["GET"])
    app.add_event_handler("shutdown", cleanup_resources)

class ChatMessage(BaseModel):
    text: str
    type: str
    chat_room_id: str
    options: Optional[Dict[Any, Any]] = None

class ChatResponse(BaseModel):
    response: Dict[str, Any]

async def chat_message(message: ChatMessage):
    try:
        chat_room_id = message.chat_room_id
        if message.type == "a2a":
            agent_url = message.options.get("agent_url") if message.options else None
            task_id = message.options.get("task_id") if message.options else None
            
            if not agent_url:
                raise HTTPException(status_code=400, detail="agent_url is required for A2A agent")
            
            response = await process_a2a_message(
                text=message.text,
                agent_url=agent_url,
                task_id=task_id,
                context_id=chat_room_id
            )
            
            if isinstance(response, StreamingResponse):
                return response
            
            return JSONResponse(content=response)
        
        elif message.type == "mem0":
            agent_id = message.options.get("agent_id") if message.options else None
            
            if not agent_id:
                raise HTTPException(status_code=400, detail="agent_id is required for Mem0 agent")
            
            response = await process_mem0_message(
                text=message.text,
                agent_id=agent_id,
                chat_room_id=chat_room_id
            )
            return JSONResponse(content=response)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported message type: {message.type}")
        
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

