from fastapi import HTTPException, Request
from database import update_user_admin, create_user, invite_user, set_initial_info

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

def add_routes_to_app(app) :
    app.add_api_route("/set-tenant", combine_input_with_tenant_id, methods=["POST"])
    app.add_api_route("/create-user", combine_input_with_new_user_info, methods=["POST"])
    app.add_api_route("/invite-user", combine_input_with_invite_user_info, methods=["POST"])
    app.add_api_route("/set-initial-info", combine_input_with_set_initial_info, methods=["POST"])
    app.add_api_route("/update-user", combine_input_with_user_info, methods=["POST"])


"""
"""