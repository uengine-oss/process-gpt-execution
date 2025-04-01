from .base import BaseClient
from langchain_ollama import OllamaLLM
from typing import List, Dict, Any, AsyncGenerator
from fastapi.responses import StreamingResponse
from langchain.schema import BaseMessage

class OllamaClient(BaseClient):
    def __init__(self, model: str, streaming: bool, token: str, modelConfig: Dict[str, Any]):
        super().__init__(model, streaming, token, modelConfig)
        self.llm = OllamaLLM(
            model=self.model,
            streaming=self.streaming,
            **self.modelConfig
        )

    async def invoke(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        response = await self.llm.ainvoke(messages)
        return self._format_non_stream_response(response)

    async def _stream_logic(self, messages: List[BaseMessage]) -> AsyncGenerator[str, None]:
        async for chunk in self.llm.astream(messages):
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content

    async def stream(self, messages: List[BaseMessage]) -> StreamingResponse:
        return await self.stream_response(messages)

    def get_num_tokens_from_messages(self, messages: List[BaseMessage]) -> int:
        return self.llm.get_num_tokens_from_messages(messages=messages)