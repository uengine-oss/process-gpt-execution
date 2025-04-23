from .langchain_client import LangchainClient
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from typing import Any

class OpenAIClient(LangchainClient):
    def __init__(self):
        super().__init__("openai")

    def _get_langchain_llm_class(self) -> Any:
        return ChatOpenAI

    def _get_langchain_embedding_class(self) -> Any:
        return OpenAIEmbeddings