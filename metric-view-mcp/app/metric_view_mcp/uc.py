"""Unity Catalog access: which metric views a caller may use, and running their queries.

Access is the app service principal's view of the allowed schemas (the ceiling) intersected
with the calling user's view (OBO). Queries run as the user, so UC enforces their grants,
row filters, and column masks.
"""

import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementParameterListItem, StatementState
from mcp.server.mcpserver.exceptions import ToolError

from .metric_views import MetricView, parse

CACHE_SECONDS = 300


def run_sql(client: WorkspaceClient, warehouse_id: str, sql: str, params=()) -> tuple[list[str], list[list]]:
    resp = client.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        parameters=[StatementParameterListItem(**p) for p in params],
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    if resp.status.state != StatementState.SUCCEEDED:
        raise ToolError(resp.status.error.message if resp.status.error else f"Query {resp.status.state.value}")
    return [c.name for c in resp.manifest.schema.columns], resp.result.data_array or []


class Registry:
    def __init__(self, sp: WorkspaceClient, warehouse_id: str, allowed_schemas: list[str]):
        self.sp, self.warehouse_id, self.allowed_schemas = sp, warehouse_id, allowed_schemas
        self._cache = {}

    def _cached(self, key, load):
        hit = self._cache.get(key)
        if not hit or time.monotonic() - hit[0] > CACHE_SECONDS:
            hit = self._cache[key] = (time.monotonic(), load())
        return hit[1]

    def _visible(self, client: WorkspaceClient) -> set[str]:
        """Metric views in the allowed schemas that this client's identity can see."""
        placeholders = ", ".join(f":s{i}" for i in range(len(self.allowed_schemas)))
        sql = (
            "SELECT lower(concat_ws('.', table_catalog, table_schema, table_name)) "
            "FROM system.information_schema.tables WHERE table_type = 'METRIC_VIEW' "
            f"AND lower(concat_ws('.', table_catalog, table_schema)) IN ({placeholders})"
        )
        params = [{"name": f"s{i}", "value": s} for i, s in enumerate(self.allowed_schemas)]
        return {row[0] for row in run_sql(client, self.warehouse_id, sql, params)[1]}

    def names_for(self, email: str, user: WorkspaceClient) -> set[str]:
        # Discovery is cached per user; queries still run as the user, so UC enforces access live.
        return self._cached("ceiling", lambda: self._visible(self.sp)) & self._cached(email, lambda: self._visible(user))

    def definition(self, full_name: str) -> MetricView:
        return self._cached(("definition", full_name), lambda: parse(self.sp.tables.get(full_name).as_dict()))

    def get(self, name: str, email: str, user: WorkspaceClient) -> MetricView:
        """Resolve a full or bare view name the user may use, and return its definition."""
        name = name.strip("` ").lower()
        matches = [n for n in self.names_for(email, user) if n == name or n.split(".")[-1] == name]
        if len(matches) != 1:
            raise ToolError(f"{name!r} is not an available metric view. Call list_metric_views to see what you can use.")
        return self.definition(matches[0])
