"""Unity Catalog access: which metric views a caller may use, and running their queries.

A caller can use the metric views that match config.yml and that they can see in Unity Catalog.
Everything runs as the caller (OBO), so UC enforces their grants, row filters, and column masks.
"""

import json
import time
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementState
from mcp.server.mcpserver.exceptions import ToolError

from .metric_views import quote

CONFIG = Path(__file__).resolve().parent.parent / "config.yml"
CACHE_SECONDS = 300


def load_include(path: Path = CONFIG) -> list[str]:
    return [str(entry).strip().lower() for entry in yaml.safe_load(path.read_text())["include"]]


def in_scope(full_name: str, include: list[str]) -> bool:
    """True if `catalog.schema.view` matches "*", its catalog, its schema, or itself."""
    parts = full_name.lower().split(".")
    return any(entry == "*" or parts[: entry.count(".") + 1] == entry.split(".") for entry in include)


def run_sql(client: WorkspaceClient, warehouse_id: str, sql: str, row_limit=None) -> tuple[list[str], list[list], bool]:
    resp = client.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        row_limit=row_limit,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    if resp.status.state != StatementState.SUCCEEDED:
        raise ToolError(resp.status.error.message if resp.status.error else f"Query {resp.status.state.value}")
    columns = [c.name for c in resp.manifest.schema.columns]
    return columns, resp.result.data_array or [], bool(resp.manifest.truncated)


class Registry:
    def __init__(self, warehouse_id: str, include: list[str]):
        self.warehouse_id, self.include = warehouse_id, include
        self._cache = {}

    def _cached(self, key, load):
        hit = self._cache.get(key)
        if not hit or time.monotonic() - hit[0] > CACHE_SECONDS:
            hit = self._cache[key] = (time.monotonic(), load())
        return hit[1]

    def _visible(self, user: WorkspaceClient) -> dict[str, str]:
        """Every metric view the user can see, with its description."""
        sql = (
            "SELECT lower(concat_ws('.', table_catalog, table_schema, table_name)), comment "
            "FROM system.information_schema.tables WHERE table_type = 'METRIC_VIEW'"
        )
        return {name: comment or "" for name, comment in run_sql(user, self.warehouse_id, sql)[1]}

    def views_for(self, email: str, user: WorkspaceClient) -> dict[str, str]:
        """In-scope metric views the user can see. Cached per user; queries still run as the user."""
        return self._cached(email, lambda: {n: c for n, c in self._visible(user).items() if in_scope(n, self.include)})

    def resolve(self, name: str, email: str, user: WorkspaceClient) -> str:
        """The full name of a full or bare view name the user may use."""
        name = name.strip("` ").lower()
        matches = [n for n in self.views_for(email, user) if n == name or n.split(".")[-1] == name]
        if len(matches) > 1:
            raise ToolError(f"{name!r} matches several metric views; use one of: {', '.join(sorted(matches))}")
        if not matches:
            raise ToolError(f"{name!r} is not an available metric view. Call list_metric_views to see what you can use.")
        return matches[0]

    def definition(self, full_name: str, user: WorkspaceClient) -> dict:
        """The metric view's complete YAML definition, as stored in Unity Catalog."""
        def load():
            rows = run_sql(user, self.warehouse_id, f"DESCRIBE TABLE EXTENDED {quote(full_name)} AS JSON")[1]
            return yaml.safe_load(json.loads(rows[0][0])["view_text"])

        return self._cached(("definition", full_name), load)
