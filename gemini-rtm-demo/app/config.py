"""
App configuration — reads environment variables injected by Databricks Apps
(via app.yaml secrets) or from .env when running locally.

See the root config.py for the full variable reference.
"""

import os
from pathlib import Path

def _load_dotenv(path: Path) -> None:
    """Load a .env file without external dependencies. No-op if file is absent."""
    if path.exists():
        for line in path.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())

_load_dotenv(Path(__file__).parent.parent / ".env")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(
            f"Required environment variable {name!r} is not set.\n"
            f"Copy .env.example to .env and fill in your values, or check app.yaml secrets."
        )
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


LAKEBASE_HOST            = _require("LAKEBASE_HOST")
LAKEBASE_DB              = _optional("LAKEBASE_DB", "databricks_postgres")
LAKEBASE_PASSWORD        = _require("LAKEBASE_PASSWORD")        # grafana_reader role
LAKEBASE_WRITER_PASSWORD = _require("LAKEBASE_WRITER_PASSWORD")  # rtm_writer role

LINEAR_API_KEY = _optional("LINEAR_API_KEY")
LINEAR_TEAM_ID = _optional("LINEAR_TEAM_ID")
