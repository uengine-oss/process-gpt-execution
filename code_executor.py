"""Commands to execute code"""

COMMAND_CATEGORY = "execute_code"
COMMAND_CATEGORY_TITLE = "Execute Code"

import logging
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

import docker
from docker.errors import DockerException, ImageNotFound
from docker.models.containers import Container as DockerContainer

# from autogpt.agents.utils.exceptions import (
#     CodeExecutionError,
#     CommandExecutionError,
#     InvalidArgumentError,
#     OperationNotAllowedError,
# )
# from autogpt.command_decorator import command
# from autogpt.config import Config
# from autogpt.core.utils.json_schema import JSONSchema

#from .decorators import sanitize_path_arg

logger = logging.getLogger(__name__)

ALLOWLIST_CONTROL = "allowlist"
DENYLIST_CONTROL = "denylist"



from typing import Optional, Dict
def execute_python_code(code: str, workspace_path: Optional[Path] = None, env_vars: Optional[Dict[str, str]] = None) -> str:
    """Create and execute a Python file in a Docker container and return the STDOUT of the
    executed code. If there is any data that needs to be captured use a print statement

    Args:
        code (str): The Python code to run
        workspace_path (Optional[Path]): The workspace path where the code file will be created
        env_vars (Optional[Dict[str, str]]): Environment variables to pass to the Docker container

    Returns:
        str: The STDOUT captured from the code when it ran
    """
    if not workspace_path:
        workspace_path = Path.cwd()

    tmp_code_file = NamedTemporaryFile(
        "w", dir=workspace_path, suffix=".py", encoding="utf-8"
    )
    tmp_code_file.write(code)
    tmp_code_file.flush()

    try:
        return execute_python_file(tmp_code_file.name, workspace_path, env_vars=env_vars)
    except Exception as e:
        raise BaseException(*e.args)
    finally:
        tmp_code_file.close()

def execute_python_file(
    filename: Path, workding_dir: Path, args: list[str] | str = [], env_vars: Optional[Dict[str, str]] = None
) -> str:
    """Execute a Python file in a Docker container and return the output

    Args:
        filename (Path): The name of the file to execute
        workding_dir (Path): The working directory for the execution
        args (list[str] | str, optional): The arguments with which to run the python script
        env_vars (Optional[Dict[str, str]]): Environment variables to pass to the Docker container

    Returns:
        str: The output of the file
    """
    logger.info(
        f"Executing python file '{filename}'"
    )

    if isinstance(args, str):
        args = args.split()  # Convert space-separated string to a list

    if not str(filename).endswith(".py"):
        raise InvalidArgumentError("Invalid file type. Only .py files are allowed.")

    file_path = Path(filename)
    if not file_path.is_file():
        # Mimic the response that you get from the command line so that it's easier to identify
        raise FileNotFoundError(
            f"python: can't open file '{filename}': [Errno 2] No such file or directory"
        )

    if we_are_running_in_a_docker_container():
        logger.debug(
            f"AutoGPT is running in a Docker container; executing {file_path} directly..."
        )
        result = subprocess.run(
            ["python", "-B", str(file_path)] + args,
            capture_output=True,
            encoding="utf8",
            cwd=str(workding_dir),
            env={**os.environ, **(env_vars if env_vars else {})}  # Merge current environment with provided env_vars
        )
        if result.returncode == 0:
            return result.stdout
        else:
            raise CodeExecutionError(result.stderr)

    logger.debug("AutoGPT is not running in a Docker container")
    try:
        client = docker.from_env()
        image_name = "python:3-alpine"
        try:
            client.images.get(image_name)
            logger.debug(f"Image '{image_name}' found locally")
        except ImageNotFound:
            logger.info(
                f"Image '{image_name}' not found locally, pulling from Docker Hub..."
            )
            # Use the low-level API to stream the pull response
            low_level_client = docker.APIClient()
            for line in low_level_client.pull(image_name, stream=True, decode=True):
                # Print the status and progress, if available
                status = line.get("status")
                progress = line.get("progress")
                if status and progress:
                    logger.info(f"{status}: {progress}")
                elif status:
                    logger.info(status)

        logger.debug(f"Running {file_path} in a {image_name} container...")
        container: DockerContainer = client.containers.run(
            image_name,
            [
                "python",
                "-B",
                file_path.relative_to(workding_dir).as_posix(),
            ]
            + args,
            volumes={
                str(workding_dir): {
                    "bind": "/workspace",
                    "mode": "rw",
                }
            },
            working_dir="/workspace",
            environment=env_vars,  # Pass environment variables to Docker container
            stderr=True,
            stdout=True,
            detach=True,
        )

        container.wait()
        logs = container.logs().decode("utf-8")
        container.remove()

        return logs

    except DockerException as e:
        logger.warn(
            "Could not run the script in a container. If you haven't already, please install Docker https://docs.docker.com/get-docker/"
        )
        raise BaseException(f"Could not run the script in a container: {e}")



def we_are_running_in_a_docker_container() -> bool:
    """Check if we are running in a Docker container

    Returns:
        bool: True if we are running in a Docker container, False otherwise
    """
    return os.path.exists("/.dockerenv")

current_dir = Path(__file__).parent
app_file_path = current_dir / "app.py"


print(execute_python_file(app_file_path, current_dir))

