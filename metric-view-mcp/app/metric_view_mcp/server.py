"""MCP tools over Unity Catalog metric views, served as a stateless streamable-HTTP app."""

import os
from dataclasses import asdict
from typing import Any, Literal

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from .metric_views import OPERATORS, build_query
from .uc import Registry, run_sql

WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
MAX_ROWS = 1000

sp = WorkspaceClient()
registry = Registry(sp, WAREHOUSE_ID, [s.strip().lower() for s in os.environ["MV_ALLOWED_SCHEMAS"].split(",")])

mcp = MCPServer(
    name="metric-view-mcp",
    instructions=(
        "This server is the governed semantic layer and only exposes Unity Catalog metric views. "
        "Call list_metric_views, then describe_metric_view for exact measure and dimension names, "
        "then query_metric with those names. Never invent names. For a query query_metric can't express, "
        "adapt describe_metric_view's sql_example and run it with the Databricks SQL MCP (execute_sql), "
        "querying only these metric views and wrapping every measure in MEASURE()."
    ),
)


class Filter(BaseModel):
    dimension: str
    op: Literal[OPERATORS]
    value: Any  # a list for IN, a [low, high] pair for BETWEEN


def as_user(ctx: Context) -> tuple[str, WorkspaceClient]:
    """The caller's identity and a client acting as them, from what Databricks Apps forwards (OBO)."""
    headers = ctx.headers or {}
    token, email = headers.get("x-forwarded-access-token"), headers.get("x-forwarded-email")
    if not token or not email:
        raise ToolError("No user token on this request. Connect through the Databricks App URL.")
    return email, WorkspaceClient(config=Config(host=sp.config.host, token=token, auth_type="pat"))


@mcp.tool()
def list_metric_views(ctx: Context) -> dict:
    """List the governed metric views you can query, with their measure and dimension names."""
    views = [registry.definition(n) for n in sorted(registry.names_for(*as_user(ctx)))]
    return {"metric_views": [{"view": v.name, "description": v.description,
                              "measures": [m["name"] for m in v.measures],
                              "dimensions": [d["name"] for d in v.dimensions]} for v in views]}


@mcp.tool()
def describe_metric_view(view: str, ctx: Context) -> dict:
    """Get a metric view's measures and dimensions with types, business descriptions, and example SQL."""
    v = registry.get(view, *as_user(ctx))
    example = build_query(v, [v.measures[0]["name"]], [v.dimensions[0]["name"]], limit=10)[0]
    return {**asdict(v), "sql_example": example}


@mcp.tool()
def query_metric(view: str, measures: list[str], ctx: Context, dimensions: list[str] = [],
                 filters: list[Filter] = [], order_by: list[str] = [], limit: int = 100) -> dict:
    """Query measures from one metric view, grouped by the given dimensions.

    Measures aggregate correctly at the grain the dimensions define (Active Users by Week = WAU).
    Filters apply to dimensions. order_by entries are selected names, optionally with DESC ("Week DESC").
    Returns the SQL that ran, column names, and rows.
    """
    email, user = as_user(ctx)
    sql, params = build_query(registry.get(view, email, user), measures, dimensions,
                              [f.model_dump() for f in filters], order_by, limit, MAX_ROWS)
    columns, rows = run_sql(user, WAREHOUSE_ID, sql, params)
    return {"sql": sql, "columns": columns, "rows": rows}


# Stateless, so any app instance can serve any request.
mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")


async def app(scope, receive, send):
    # AI Playground appends /mcp to the app's listed MCP URL (which already ends in /mcp).
    if scope["type"] == "http" and scope["path"] == "/mcp/mcp":
        scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
    await mcp_app(scope, receive, send)


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
