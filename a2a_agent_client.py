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

async def cleanup_resources():
    """Cleanup resources on shutdown."""
    for client in httpx_client_cache.values():
        await client.aclose()
    client_cache.clear()
    httpx_client_cache.clear()

async def stream_a2a_response(text: str, agent_url: str, task_id: str = None, context_id: str = None) -> AsyncGenerator[str, None]:
    """Stream A2A message response."""
    try:
        # A2A 클라이언트 가져오기
        client = await get_a2a_client(str(agent_url))
        
        # 메시지 전송 요청 생성
        send_payload = {
            'message': {
                'role': 'user',
                'parts': [{'kind': 'text', 'text': text}],
                'messageId': uuid4().hex,
            }
        }
        
        if task_id:
            send_payload['message']['taskId'] = task_id
        if context_id:
            send_payload['message']['contextId'] = context_id

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

async def process_a2a_message(text: str, agent_url: str, task_id: str = None, context_id: str = None) -> StreamingResponse:
    """Process A2A message and return streaming response."""
    return StreamingResponse(
        stream_a2a_response(text, agent_url, task_id, context_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

