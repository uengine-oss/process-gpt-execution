from fastapi import Request, HTTPException
import json
from typing import Dict

def add_routes_to_app(app):
    app.add_api_route("/mcp-tools", load_mcp_tools, methods=["GET"])
    
def load_mcp_tools() -> Dict:
    """Load and return MCP configuration from mcp.json file."""
    try:
        with open('mcp.json', 'r') as f:
            mcp_config = json.load(f)
            return mcp_config.get("mcpServers", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=404, detail=f"Failed to load MCP config: {str(e)}")

    