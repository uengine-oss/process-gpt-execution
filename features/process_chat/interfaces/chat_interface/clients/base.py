import abc
import json
import os
from typing import List, Dict, Any, AsyncGenerator
from datetime import datetime
from fastapi.responses import StreamingResponse
from langchain.schema import BaseMessage

class BaseClient(abc.ABC):
    def __init__(self, vendor: str):
        self.vendor = vendor
        self.token = os.getenv(f"{vendor.upper()}_API_KEY")
        self.response_id = self._generate_response_id()

    def _generate_response_id(self) -> str:
        return f"chatcmpl-{datetime.now().timestamp()}"

    def _format_non_stream_response(self, content: str) -> Dict[str, Any]:
        return {
            "id": self.response_id,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "index": 0,
                    "finish_reason": "stop"
                }
            ]
        }

    def _format_stream_chunk(self, chunk_content: str) -> str:
        data = {
            "id": self.response_id,
            "choices": [
                {
                    "delta": {"content": chunk_content},
                    "index": 0,
                    "finish_reason": None
                }
            ]
        }
        return f"data: {json.dumps(data)}\n\n"

    def _format_stream_done(self) -> str:
        return "data: [DONE]\n\n"

    @abc.abstractmethod
    async def invoke(self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def stream(self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]) -> StreamingResponse:
        pass

    @abc.abstractmethod
    async def _stream_logic(self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]) -> AsyncGenerator[str, None]:
        yield

    @abc.abstractmethod
    def get_num_tokens_from_messages(self, messages: List[BaseMessage], model: str) -> int:
        pass

    @abc.abstractmethod
    async def get_embedding(self, text: str, model: str) -> List[float]:
        pass

    async def stream_response(self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]) -> StreamingResponse:
        async def generator():
            async for chunk_content in self._stream_logic(messages, model, modelConfig):
                if chunk_content:
                    yield self._format_stream_chunk(chunk_content)
            yield self._format_stream_done()

        return StreamingResponse(generator(), media_type="text/event-stream")
