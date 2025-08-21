from features.process_chat import (
    BASE_URL, 
    ChatRequest, TokenCountRequest, EmbeddingRequest, 
    ChatInterface
)
from fastapi import HTTPException

def add_routes_to_app(app):
    app.add_api_route(f"{BASE_URL}/sanity-check", sanity_check, methods=["GET"])
    app.add_api_route(f"{BASE_URL}/health", health_check, methods=["GET"])
    app.add_api_route(f"{BASE_URL}/messages", process_chat_messages, methods=["POST"])
    app.add_api_route(f"{BASE_URL}/count-tokens", count_tokens, methods=["POST"])
    app.add_api_route(f"{BASE_URL}/embeddings", get_embedding_vector, methods=["POST"])

def sanity_check():
    return {"is_sanity_check": True}

def health_check():
    return {"status": "healthy", "service": "process-chat"}

async def process_chat_messages(chat_request: ChatRequest):
    try:

        response = await ChatInterface.messages(
            vendor=chat_request.vendor,
            model=chat_request.model,
            messages=chat_request.messages,
            stream=chat_request.stream,
            modelConfig=chat_request.modelConfig
        )
        return response

    except ValueError as ve:
        raise HTTPException(status_code=501, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

async def count_tokens(count_request: TokenCountRequest):
    try:

        token_count = await ChatInterface.count_tokens(
            vendor=count_request.vendor,
            model=count_request.model,
            messages=count_request.messages
        )
        return {"input_tokens": token_count}

    except ValueError as ve:
        raise HTTPException(status_code=501, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error counting tokens: {str(e)}")

async def get_embedding_vector(embedding_request: EmbeddingRequest):
    try:

        embedding_vector = await ChatInterface.embeddings(
            vendor=embedding_request.vendor,
            model=embedding_request.model,
            text=embedding_request.text
        )
        return {"embedding": embedding_vector}

    except ValueError as ve:
        raise HTTPException(status_code=501, detail=str(ve))
    except NotImplementedError as nie:
        raise HTTPException(status_code=501, detail=f"Embedding not implemented for vendor: {embedding_request.vendor}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating embedding: {str(e)}")
