"""Commands to execute code"""

COMMAND_CATEGORY = "execute_code"
COMMAND_CATEGORY_TITLE = "Execute Code"

import logging
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

logger = logging.getLogger(__name__)

ALLOWLIST_CONTROL = "allowlist"
DENYLIST_CONTROL = "denylist"

from typing import Optional, Dict
def execute_python_code(code: str, workspace_path: Optional[Path] = None, env_vars: Optional[Dict[str, str]] = None) -> str:
    """Execute Python code directly in the local environment and return the STDOUT.

    Args:
        code (str): The Python code to run
        workspace_path (Optional[Path]): The workspace path where the code file will be created
        env_vars (Optional[Dict[str, str]]): Environment variables to pass to the execution environment

    Returns:
        str: The STDOUT captured from the code when it ran
    """
    if not workspace_path:
        workspace_path = Path.cwd()

    with NamedTemporaryFile("w", dir=workspace_path, suffix=".py", delete=False) as tmp_code_file:
        tmp_code_file.write(code)
        tmp_code_file_path = Path(tmp_code_file.name)

    try:
        return execute_python_file(tmp_code_file_path, workspace_path, env_vars=env_vars)
    finally:
        os.remove(tmp_code_file_path)

def execute_python_file(
    filename: Path, workding_dir: Path, env_vars: Optional[Dict[str, str]] = None
) -> str:
    """Execute a Python file directly in the local environment and return the output

    Args:
        filename (Path): The name of the file to execute
        workding_dir (Path): The working directory for the execution
        env_vars (Optional[Dict[str, str]]): Environment variables to pass to the execution environment

    Returns:
        str: The output of the file
    """
    logger.info(
        f"Executing python file '{filename}'"
    )

    if not filename.suffix == ".py":
        raise ValueError("Invalid file type. Only .py files are allowed.")

    if not filename.is_file():
        raise FileNotFoundError(f"Cannot find the specified Python file: {filename}")

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    result = subprocess.run(
        ["python", str(filename)],
        capture_output=True,
        text=True,
        cwd=str(workding_dir),
        env=env
    )

    if result.returncode != 0:
        logger.error(f"Error executing Python file: {result.stderr}")
        raise Exception(f"Error executing Python file: {result.stderr}")

    return result.stdout

# Example usage
if __name__ == "__main__":
    code = "print('Hello, world!')"
    print(execute_python_code(code))

