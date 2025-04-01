from features.process_chat import (
    BASE_URL, 
    ChatRequest, TokenCountRequest, 
    TokenUtil, 
    ClientFactory, LangchainMessageFactory
)
from fastapi import HTTPException, Request

def add_routes_to_app(app):
    app.add_api_route(f"{BASE_URL}/sanity-check", sanity_check, methods=["GET"])
    app.add_api_route(f"{BASE_URL}/messages", process_chat_messages, methods=["POST"])
    app.add_api_route(f"{BASE_URL}/count-tokens", count_tokens, methods=["POST"])

def sanity_check(request: Request):
    return {"is_sanity_check": True}

async def process_chat_messages(fastapi_request: Request, chat_request: ChatRequest):
    try:

        client_class = ClientFactory.get_client_class(chat_request.vendor)
        token = TokenUtil.getTokenFromHeader(fastapi_request, chat_request.vendor)

        client = client_class(
            model=chat_request.model,
            streaming=chat_request.stream,
            token=token,
            modelConfig=chat_request.modelConfig
        )

        lc_messages = LangchainMessageFactory.create_messages(chat_request.messages)
        if chat_request.stream:
            return await client.stream(lc_messages)
        else:
            return await client.invoke(lc_messages)

    except ValueError as ve:
        raise HTTPException(status_code=501, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

async def count_tokens(fastapi_request: Request, count_request: TokenCountRequest):
    try:

        client_class = ClientFactory.get_client_class(count_request.vendor)
        token = TokenUtil.getTokenFromHeader(fastapi_request, count_request.vendor)

        client = client_class(
            model=count_request.model,
            streaming=False,
            token=token,
            modelConfig={}
        )

        lc_messages = LangchainMessageFactory.create_messages(count_request.messages)
        token_count = client.get_num_tokens_from_messages(lc_messages)

        return {"input_tokens": token_count}

    except ValueError as ve:
        raise HTTPException(status_code=501, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error counting tokens: {str(e)}")
