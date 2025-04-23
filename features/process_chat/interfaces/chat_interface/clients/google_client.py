from .langchain_client import LangchainClient
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Any

class GoogleClient(LangchainClient):
    def __init__(self):
        super().__init__("google")

    def _get_langchain_llm_class(self) -> Any:
        return ChatGoogleGenerativeAI

    def _get_langchain_embedding_class(self) -> Any:
        raise NotImplementedError("Embedding is not supported for Google. Use openai embedding instead.")