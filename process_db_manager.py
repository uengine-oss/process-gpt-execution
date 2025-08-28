from fastapi import HTTPException, Request
from database import update_user_admin, create_user, invite_user, set_initial_info, get_vecs_memories, delete_vecs_memories


async def combine_input_with_tenant_id(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    return update_user_admin(input)

async def combine_input_with_new_user_info(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    return create_user(input)

async def combine_input_with_invite_user_info(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    return invite_user(input)

async def combine_input_with_set_initial_info(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    return set_initial_info(input)

async def combine_input_with_user_info(request: Request):
    json_data = await request.json()
    input = json_data.get('input')
    return update_user_admin(input)

async def get_vecs_documents(request: Request):
    input = await request.json()
    agent_id = input.get('agent_id')
    limit = input.get('limit', 10)
    
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    if not limit:
        raise HTTPException(status_code=400, detail="limit is required")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be greater than 0")
    if limit > 100:
        limit = 100

    return get_vecs_memories(agent_id, limit)

async def delete_vecs_documents(request: Request):
    input = await request.json()
    agent_id = input.get('agent_id')
    memory_id = input.get('memory_id')
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    if not memory_id:
        raise HTTPException(status_code=400, detail="memory_id is required")

    return delete_vecs_memories(agent_id, memory_id)


def add_routes_to_app(app) :
    app.add_api_route("/set-tenant", combine_input_with_tenant_id, methods=["POST"])
    app.add_api_route("/create-user", combine_input_with_new_user_info, methods=["POST"])
    app.add_api_route("/invite-user", combine_input_with_invite_user_info, methods=["POST"])
    app.add_api_route("/set-initial-info", combine_input_with_set_initial_info, methods=["POST"])
    app.add_api_route("/update-user", combine_input_with_user_info, methods=["POST"])
    app.add_api_route("/get-vecs-documents", get_vecs_documents, methods=["POST"])
    app.add_api_route("/delete-vecs-documents", delete_vecs_documents, methods=["POST"])


"""
"""