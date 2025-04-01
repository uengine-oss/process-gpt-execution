from typing import Dict, Type

from .base import BaseClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient
from .google_client import GoogleClient
from .ollama_client import OllamaClient

class ClientFactory:
    _clients: Dict[str, Type[BaseClient]] = {
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "google": GoogleClient,
        "ollama": OllamaClient
    }

    @staticmethod
    def get_client_class(vendor: str) -> Type[BaseClient]:
        client_class = ClientFactory._clients.get(vendor.lower())
        if not client_class:
            supported_vendors = ", ".join(ClientFactory._clients.keys())
            raise ValueError(f"Vendor '{vendor}' is not supported. Supported vendors: {supported_vendors}")
        return client_class