import sys
from pathlib import Path


# Ensure repository root (one level above 'polling_service') is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


