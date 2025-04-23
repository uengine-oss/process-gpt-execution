from typing import List, Dict, Any
from .clients import ClientFactory
from .factories import LangchainMessageFactory  


class ChatInterface:
    @staticmethod
    async def messages(vendor: str, model: str, messages: List[Dict[str, Any]], stream: bool, modelConfig: Dict[str, Any]):
        client = ClientFactory.get_client(vendor)
        lc_messages = LangchainMessageFactory.create_messages(messages)
        if stream:
            return await client.stream(
                messages=lc_messages,
                model=model,
                modelConfig=modelConfig
            )
        else:
            return await client.invoke(
                messages=lc_messages,
                model=model,
                modelConfig=modelConfig
            )
    
    @staticmethod
    async def count_tokens(vendor: str, model: str, messages: List[Dict[str, Any]]):
        client = ClientFactory.get_client(vendor)
        lc_messages = LangchainMessageFactory.create_messages(messages)
        return client.get_num_tokens_from_messages(
            messages=lc_messages,
            model=model
        )
    
    @staticmethod
    async def embeddings(vendor: str, model: str, text: str):
        client = ClientFactory.get_client(vendor)
        return await client.get_embedding(
            text=text,
            model=model
        )
