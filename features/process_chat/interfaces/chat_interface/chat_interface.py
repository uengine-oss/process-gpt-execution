from typing import List, Dict, Any
from .clients import ClientFactory
from .factories import LangchainMessageFactory
from .clients.base import StreamingResponse
from Usage import get_service_by_category, usage

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
        # 요청 모델의 서비스 정보
        service = get_service_by_category("llm", model)
        print(service)
        # 요청 프롬프트 토큰 계산
        request_tokens = ChatInterface.count_tokens(vendor, model, messages)
        print(f"[DEBUG] Request tokens: {request_tokens}")
        
        def record_usage(total_tokens: int, response_text: str = ""):
            """토큰 사용량을 기록하는 헬퍼 함수"""
            raw_data = { 
                "service_master_id": "", # get_service_by_category 의 service_master_id            
                "used_at": "2023-10-01T12:00:00+09:00", #실제 시작 시점/요청시점
                "model": model, #모델명
                "user_id": "jaeh@uengine.org", # 사용자 아이디
                "quantity": total_tokens, #총 토크수, 총 호출 수
                "metadata": {
                    # get_service_by_category의 dimension 정보로 구분
                    "request": {
                        "tokens": request_tokens,
                        "creditPerUnit": 0 # get_service_by_category의 credit_per_unit
                    },
                    "cached_request": {
                        "tokens": 0,
                        "creditPerUnit": 0
                    },
                    "response": {
                        "tokens": total_tokens - request_tokens,
                        "creditPerUnit": 0
                    },
                    "usedFor": "chat",
                    "usedForId": "1234567890",
                    "usedForName": "AI 생성 처리 채팅"
                }

            }
            try:
                # usage(raw_data)
                print(f"[DEBUG] Usage recorded - Total tokens: {total_tokens} (Request: {request_tokens}, Response: {total_tokens - request_tokens})")
            except Exception as e:
                print(f"[ERROR] Failed to record usage: {e}")
        
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

                # 스트리밍 완료 후 응답 토큰 계산 및 사용량 기록
                if result_text:
                    response_tokens = ChatInterface.count_tokens(vendor, model, [{"role": "assistant", "content": result_text}])
                    total_tokens = request_tokens + response_tokens
                    print(f"[DEBUG] Response tokens: {response_tokens}, Total tokens: {total_tokens}")
                    record_usage(total_tokens, result_text)
                else:
                    print(f"[WARNING] No response text in streaming, recording request tokens only")
                    record_usage(request_tokens, "")

                # try:
                #     cache.update(prompt, llm_string, [Generation(text=result_text)])
                # except Exception as e:
                #     print(f"[cache error] {e}")

            return StreamingResponse(streaming_response(), media_type="text/event-stream")

        else:
            response = await client.invoke(messages=lc_messages, model=model, modelConfig=modelConfig)
            
            # 비스트리밍 응답에서 텍스트 추출 및 토큰 계산
            try:
                response_text = ""
                if "choices" in response and len(response["choices"]) > 0:
                    if "message" in response["choices"][0]:
                        response_text = response["choices"][0]["message"].get("content", "")
                    elif "text" in response["choices"][0]:
                        response_text = response["choices"][0]["text"]
                
                if response_text:
                    response_tokens = ChatInterface.count_tokens(vendor, model, [{"role": "assistant", "content": response_text}])
                    total_tokens = request_tokens + response_tokens
                    print(f"[DEBUG] Response tokens: {response_tokens}, Total tokens: {total_tokens}")
                    record_usage(total_tokens, response_text)
                else:
                    print(f"[WARNING] No response text found, recording request tokens only")
                    record_usage(request_tokens, "")
            except Exception as e:
                print(f"[ERROR] Failed to calculate response tokens: {e}")
                record_usage(request_tokens, "")

            # try:
            #     cache.update(prompt, llm_string, [Generation(text=text)])
            # except Exception as e:
            #     print(f"[cache error] {e}")

            return response

    @staticmethod
    def count_tokens(vendor: str, model: str, messages: List[Dict[str, Any]]):
        try:
            client = ClientFactory.get_client(vendor)
            lc_messages = LangchainMessageFactory.create_messages(messages)
            token_count = client.get_num_tokens_from_messages(
                messages=lc_messages,
                model=model
            )
            print(f"[DEBUG] Token count for {vendor}:{model}: {token_count}")
            return token_count
        except Exception as e:
            print(f"[ERROR] Failed to count tokens for {vendor}:{model}: {str(e)}")
            # 토큰 계산 실패 시 대략적인 추정값 반환
            total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
            estimated_tokens = total_chars // 4  # 대략적인 추정 (4글자 ≈ 1토큰)
            print(f"[DEBUG] Using estimated token count: {estimated_tokens}")
            return estimated_tokens
        
    @staticmethod
    async def embeddings(vendor: str, model: str, text: str):
        client = ClientFactory.get_client(vendor)
        return await client.get_embedding(
            text=text,
            model=model
        )
