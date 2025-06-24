from typing import List, Dict, Any
from .clients import ClientFactory
from .factories import LangchainMessageFactory
from .clients.base import StreamingResponse

# from langchain.schema import Generation
# from langchain.globals import get_llm_cache
import hashlib, json, asyncio

def build_prompt_for_cache(vendor: str, model: str, messages: list, model_config: dict) -> str:
    return json.dumps({
        "vendor": vendor,
        "model": model,
        "messages": messages,
        "model_config": model_config
    }, sort_keys=True, ensure_ascii=False)

def build_llm_string(vendor: str, model: str) -> str:
    return f"{vendor}:{model}"

class ChatInterface:
    @staticmethod
    async def messages(vendor: str, model: str, messages: List[Dict[str, Any]], stream: bool, modelConfig: Dict[str, Any]):
        client = ClientFactory.get_client(vendor)
        lc_messages = LangchainMessageFactory.create_messages(messages)
        
        # prompt = build_prompt_for_cache(vendor, model, messages, modelConfig)
        # llm_string = build_llm_string(vendor, model)
        
        # cache = get_llm_cache()
        # cached_generations = cache.lookup(prompt, llm_string)
        
        # if cached_generations:
        #     cached_text = cached_generations[0].text

        #     async def stream_cached_response(text: str):
        #         yield f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\n"
        #         yield "data: [DONE]\n\n"

        #     return StreamingResponse(stream_cached_response(cached_text), media_type="text/event-stream")

        if stream:
            response = await client.stream_response(
                messages=lc_messages,
                model=model,
                modelConfig=modelConfig
            )

            result_text = ""
            
            async def streaming_response():
                nonlocal result_text
                async for chunk in response.body_iterator:
                    parsed = chunk.strip().removeprefix("data: ").removesuffix("\n\n")
                    try:
                        obj = json.loads(parsed)
                        content = obj["choices"][0]["delta"].get("content")
                        if content:
                            result_text += content
                    except:
                        pass
                    yield chunk

                # try:
                #     cache.update(prompt, llm_string, [Generation(text=result_text)])
                # except Exception as e:
                #     print(f"[cache error] {e}")

            return StreamingResponse(streaming_response(), media_type="text/event-stream")

        else:
            response = await client.invoke(messages=lc_messages, model=model, modelConfig=modelConfig)
            # text = response["text"]

            # try:
            #     cache.update(prompt, llm_string, [Generation(text=text)])
            # except Exception as e:
            #     print(f"[cache error] {e}")

            return response

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
