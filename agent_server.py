
import os
import sys
import asyncio

import click
import uvicorn

from agent_executor import ProcessAgentExecutor
from dotenv import load_dotenv

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from a2a.server.tasks import InMemoryTaskStore

if os.getenv("ENV") != "production":
    load_dotenv(override=True)


@click.command()
@click.option(
    "--host", "host", default="localhost", help="Hostname to bind the server to."
)
@click.option(
    "--port", "port", default=10002, type=int, help="Port to bind the server to."
)
@click.option("--log-level", "log_level", default="info", help="Uvicorn log level.")
def cli_main(host: str, port: int, log_level: str):
    """Command Line Interface to start the Airbnb Agent server."""
    async def run_server_async():
        agent_executor = ProcessAgentExecutor(
        )

        request_handler = DefaultRequestHandler(
            agent_executor=agent_executor,
            task_store=InMemoryTaskStore(),
        )

        # Create the A2AServer instance
        a2a_server = A2AStarletteApplication(
            agent_card=get_agent_card(host, port), http_handler=request_handler
        )

        # Get the ASGI app from the A2AServer instance
        asgi_app = a2a_server.build()

        config = uvicorn.Config(
            app=asgi_app,
            host=host,
            port=port,
            log_level=log_level.lower(),
            lifespan="auto",
        )

        uvicorn_server = uvicorn.Server(config)

        print(
            f"Starting Uvicorn server at http://{host}:{port} with log-level {log_level}..."
        )
        try:
            await uvicorn_server.serve()
        except KeyboardInterrupt:
            print("Server shutdown requested (KeyboardInterrupt).")
        finally:
            print("Uvicorn server has stopped.")
            # The app_lifespan's finally block handles mcp_client shutdown

    try:
        asyncio.run(run_server_async())
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            print(
                "Critical Error: Attempted to nest asyncio.run(). This should have been prevented.",
                file=sys.stderr,
            )
        else:
            print(f"RuntimeError in cli_main: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred in cli_main: {e}", file=sys.stderr)
        sys.exit(1)


def get_agent_card(host: str, port: int):
    """Returns the Agent Card for the Currency Agent."""
    capabilities = AgentCapabilities(streaming=True, pushNotifications=True)
    skill = AgentSkill(
        id="airbnb_search",
        name="Search airbnb accommodation",
        description="Helps with accommodation search using airbnb",
        tags=["airbnb accommodation"],
        examples=[
            "Please find a room in LA, CA, April 15, 2025, checkout date is april 18, 2 adults"
        ],
    )
    return AgentCard(
        name="Airbnb Agent",
        description="Helps with searching accommodation",
        url=f"http://{host}:{port}/",
        version="1.0.0",
        defaultInputModes=["text", "text/plain", "application/json"],
        defaultOutputModes=["text", "text/plain", "application/json"],
        capabilities=capabilities,
        skills=[skill],
    )


if __name__ == "__main__":
    cli_main()
