from .langchain_client import LangchainClient
from langchain_anthropic import ChatAnthropic
from typing import Any

class AnthropicClient(LangchainClient):
    def __init__(self):
        super().__init__("anthropic")

    def _get_langchain_llm_class(self) -> Any:
        return ChatAnthropic

    def _get_langchain_embedding_class(self) -> Any:
        raise NotImplementedError("Embedding is not supported for Anthropic. Use openai embedding instead.")