from typing import Any, Dict, AsyncGenerator
from uuid import uuid4
import asyncio
import httpx
import json
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from a2a.client import A2AClient
from a2a.types import (
    SendStreamingMessageRequest,
    MessageSendParams,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    GetTaskRequest,
    GetTaskResponse,
    TaskQueryParams,
    Task
)

client_cache: Dict[str, A2AClient] = {}
httpx_client_cache: Dict[str, httpx.AsyncClient] = {}

# 타임아웃 설정
TIMEOUT = 60  # 60초

async def get_a2a_client(agent_url: str) -> A2AClient:
    """Get or create A2A client for the given agent URL."""
    if agent_url not in client_cache:
        # 새로운 httpx 클라이언트 생성
        httpx_client = httpx.AsyncClient(timeout=TIMEOUT)
        httpx_client_cache[agent_url] = httpx_client
        
        # A2A 클라이언트 생성
        client_cache[agent_url] = await A2AClient.get_client_from_agent_card_url(
            httpx_client, agent_url
        )
    return client_cache[agent_url]

def create_send_message_payload(
    text: str, task_id: str | None = None, context_id: str | None = None
) -> dict[str, Any]:
    """Helper function to create the payload for sending a task."""
    payload: dict[str, Any] = {
        'message': {
            'role': 'user',
            'parts': [{'kind': 'text', 'text': text}],
            'messageId': uuid4().hex,
        },
    }

    if task_id:
        payload['message']['taskId'] = task_id

    if context_id:
        payload['message']['contextId'] = context_id
    return payload

async def cleanup_resources():
    """Cleanup resources on shutdown."""
    for client in httpx_client_cache.values():
        await client.aclose()
    client_cache.clear()
    httpx_client_cache.clear()

async def non_stream_a2a_response(text: str, agent_url: str, task_id: str = None, context_id: str = None) -> dict:
    """Process A2A message and return collected response as dict."""
    try:
        client = await get_a2a_client(str(agent_url))
        
        send_payload = create_send_message_payload(text, task_id, context_id)
        
        request = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(**send_payload))
        send_response: SendMessageResponse = await client.send_message(request)
        
        if not isinstance(send_response.root, SendMessageSuccessResponse):
            print('received non-success response. Aborting get task ')
            return

        if not isinstance(send_response.root.result, Task):
            print('received non-task response. Aborting get task ')
            return

        task_id: str = send_response.root.result.id
        get_request = GetTaskRequest(id=str(uuid4()), params=TaskQueryParams(id=task_id))
        get_response: GetTaskResponse = await client.get_task(get_request)
        
        response = get_response.root.model_dump_json(exclude_none=True)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def stream_a2a_response(agent_url: str, text: str, task_id: str = None, context_id: str = None) -> AsyncGenerator[str, None]:
    """Stream A2A message response."""
    try:
        # A2A 클라이언트 가져오기
        client = await get_a2a_client(str(agent_url))
        
        # 메시지 전송 요청 생성
        send_payload = create_send_message_payload(text, task_id, context_id)
        
        request = SendStreamingMessageRequest(id=str(uuid4()), params=MessageSendParams(**send_payload))
        
        # 스트리밍 응답 처리
        async for chunk in client.send_message_streaming(request):
            try:
                chunk_data = chunk.model_dump(mode='json', exclude_none=True)
                response = None
                if chunk_data.get('result'):
                    response = chunk_data.get('result')
                else:
                    response = chunk_data
                
                # 응답 데이터 구조화
                response_data = {
                    'task_id': task_id,
                    'response': response
                }
                
                # SSE 형식으로 데이터 전송
                yield f"data: {json.dumps(response_data)}\n\n"
                
                # 작업이 완료되었는지 확인
                if chunk_data.get('status', {}).get('state') == 'completed':
                    break
                    
            except Exception as e:
                print(f"Error processing chunk: {str(e)}")
                continue
                
    except httpx.TimeoutException as e:
        yield f"data: {json.dumps({'error': f'Timeout error: {str(e)}'})}\n\n"
    except httpx.HTTPStatusError as e:
        yield f"data: {json.dumps({'error': f'HTTP error: {str(e)}'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': f'Error in A2A message processing: {str(e)}'})}\n\n"
    finally:
        # 스트림 종료 표시
        yield "data: [DONE]\n\n"

async def process_a2a_message(text: str, agent_url: str, task_id: str = None, context_id: str = None, stream: bool = True) -> Any:
    """Process A2A message and return response."""
    if stream:
        return StreamingResponse(
            stream_a2a_response(text, agent_url, task_id, context_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        return await non_stream_a2a_response(text, agent_url, task_id, context_id)



