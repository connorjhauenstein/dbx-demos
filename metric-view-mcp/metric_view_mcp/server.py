"""MCP tools over Unity Catalog metric views, served as a stateless streamable-HTTP app."""

import os
from concurrent.futures import ThreadPoolExecutor

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .metric_views import check_sql, compact, example_sql, matching_members
from .uc import Registry, load_include, run_sql

HOST = os.environ["DATABRICKS_HOST"]
WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
MAX_ROWS = 1000

registry = Registry(WAREHOUSE_ID, load_include())

mcp = MCPServer(
    name="metric-view-mcp",
    instructions=(
        "This server is the governed semantic layer and only exposes Unity Catalog metric views. "
        "Call list_metric_views, then describe_metric_view for exact measure and dimension names, "
        "then write SQL and run it with query_metric_views. Never invent names."
    ),
)


def as_user(ctx: Context) -> tuple[str, WorkspaceClient]:
    """The caller's identity and a client acting as them, from what Databricks Apps forwards (OBO)."""
    headers = ctx.headers or {}
    token, email = headers.get("x-forwarded-access-token"), headers.get("x-forwarded-email")
    if not token or not email:
        raise ToolError("No user token on this request. Connect through the Databricks App URL.")
    return email, WorkspaceClient(config=Config(host=HOST, token=token, auth_type="pat"))


@mcp.tool()
def list_metric_views(ctx: Context, search: str = "") -> dict:
    """List every governed metric view you can query: its description and its measures and dimensions
    (with synonyms in parentheses). Read this catalog to pick the right view and members for a question.

    For very large catalogs, pass search (for example "weekly active users") to return only views whose
    name, description, or members match those words, best matches first.
    """
    email, user = as_user(ctx)
    views = registry.views_for(email, user)
    with ThreadPoolExecutor(max_workers=8) as pool:
        definitions = dict(zip(views, pool.map(lambda n: registry.definition(n, user), views)))

    def entry(name):
        return {"view": name, "description": views[name], **compact(definitions[name])}

    if not search.strip():
        return {"metric_views": [entry(n) for n in sorted(views)]}
    terms = search.lower().split()
    scores = {n: sum(t in f"{n} {views[n]}".lower() for t in terms) + sum(matching_members(definitions[n], terms).values())
              for n in views}
    return {"metric_views": [entry(n) for n in sorted(views, key=lambda n: -scores[n]) if scores[n]]}


@mcp.tool()
def describe_metric_view(view: str, ctx: Context) -> dict:
    """Get a metric view's complete YAML definition (measures, dimensions, synonyms, formats, and more)
    and an example query."""
    email, user = as_user(ctx)
    name = registry.resolve(view, email, user)
    definition = registry.definition(name, user)
    return {"view": name, "definition": definition, "sql_example": example_sql(name, definition)}


@mcp.tool()
def query_metric_views(sql: str, ctx: Context) -> dict:
    """Run one read-only SQL query against the metric views from list_metric_views.

    Reference metric views by full catalog.schema.view name and wrap every measure in MEASURE(),
    for example: SELECT `Week`, MEASURE(`Active Users`) FROM cat.sch.view GROUP BY ALL.
    Measures aggregate correctly at whatever grain you group by (Active Users by Week = WAU).
    CTEs, subqueries, and joins across these metric views are allowed; other tables are not.
    Returns the column names and up to 1000 rows; truncated is true when more rows exist, so
    aggregate further or add filters rather than treating the rows as complete.
    """
    email, user = as_user(ctx)
    check_sql(sql, set(registry.views_for(email, user)))
    columns, rows, truncated = run_sql(user, WAREHOUSE_ID, sql, row_limit=MAX_ROWS)
    return {"columns": columns, "rows": rows, "truncated": truncated}


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
