from .base import BaseClient
import abc
from typing import List, Dict, Any, AsyncGenerator
from fastapi.responses import StreamingResponse
from langchain.schema import BaseMessage
from langchain_core.messages import AIMessageChunk

class LangchainClient(BaseClient):
    def __init__(self, vendor: str):
        super().__init__(vendor)

    @abc.abstractmethod
    def _get_langchain_llm_class(self) -> Any:
        pass

    @abc.abstractmethod
    def _get_langchain_embedding_class(self) -> Any:
        pass

    async def invoke(
        self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]
    ) -> Dict[str, Any]:
        llm = self._get_langchain_llm_class()(
            model=model,
            streaming=False,
            api_key=self.token,
            **modelConfig
        )
        response = await llm.ainvoke(messages)
        return self._format_non_stream_response(
            self._process_invoke_response(response)
        )

    def _process_invoke_response(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        elif isinstance(response, BaseMessage):
            return response.content
        else:
            raise ValueError(f"Unsupported response type: {type(response)}")

    async def _stream_logic(
        self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        llm = self._get_langchain_llm_class()(
            model=model,
            streaming=True,
            api_key=self.token,
            **modelConfig
        )
        async for chunk in llm.astream(messages):
            yield self._process_stream_chunk(chunk)
    
    def _process_stream_chunk(self, chunk: Any) -> str:
        if isinstance(chunk, str):
            return chunk
        elif isinstance(chunk, AIMessageChunk):
            return chunk.content
        else:
            raise ValueError(f"Unsupported chunk type: {type(chunk)}")

    async def stream(
        self, messages: List[BaseMessage], model: str, modelConfig: Dict[str, Any]
    ) -> StreamingResponse:
        return await self.stream_response(messages, model, modelConfig)

    def get_num_tokens_from_messages(self, messages: List[BaseMessage], model: str) -> int:
        try:
            llm = self._get_langchain_llm_class()(model=model, api_key=self.token)
            return llm.get_num_tokens_from_messages(messages=messages)
        except Exception as e:
            raise RuntimeError(f"Langchain get_num_tokens failed: {str(e)}")

    async def get_embedding(self, text: str, model: str) -> List[float]:
        try:
            embedding_client = self._get_langchain_embedding_class()(
                model=model,
                openai_api_key=self.token
            )
            embedding_vector = await embedding_client.aembed_query(text)
            return embedding_vector
        except Exception as e:
            raise RuntimeError(f"Failed to get embedding: {str(e)}")