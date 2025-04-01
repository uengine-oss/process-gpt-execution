import abc
import json
from typing import List, Dict, Any, AsyncGenerator
from datetime import datetime
from fastapi.responses import StreamingResponse
from langchain.schema import BaseMessage

class BaseClient(abc.ABC):
    def __init__(self, model: str, streaming: bool, token: str, modelConfig: Dict[str, Any]):
        self.model = model
        self.streaming = streaming
        self.token = token
        self.modelConfig = modelConfig
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
    async def invoke(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def stream(self, messages: List[BaseMessage]) -> StreamingResponse:
        pass

    @abc.abstractmethod
    async def _stream_logic(self, messages: List[BaseMessage]) -> AsyncGenerator[str, None]:
        yield

    @abc.abstractmethod
    def get_num_tokens_from_messages(self, messages: List[BaseMessage]) -> int:
        pass

    async def stream_response(self, messages: List[BaseMessage]) -> StreamingResponse:
        async def generator():
            async for chunk_content in self._stream_logic(messages):
                if chunk_content:
                    yield self._format_stream_chunk(chunk_content)
            yield self._format_stream_done()

        return StreamingResponse(generator(), media_type="text/event-stream")
