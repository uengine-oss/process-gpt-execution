from .langchain_client import LangchainClient
from langchain_ollama import OllamaLLM
from typing import Any

class OllamaClient(LangchainClient):
    def __init__(self):
        super().__init__("ollama")

    def _get_langchain_llm_class(self) -> Any:
        return OllamaLLM

    def _get_langchain_embedding_class(self) -> Any:
        raise NotImplementedError("Embedding is not supported for Ollama. Use openai embedding instead.")