"""Tools available to the Agent Workshop agent."""

import os

from databricks.sdk import WorkspaceClient
from langchain_core.tools import tool


@tool
def query_databricks_sql(query: str) -> str:
    """Execute a read-only SQL query against Databricks Unity Catalog.

    Use this tool when the user asks about data, tables, or wants to run SQL queries.
    Always use fully qualified table names: catalog.schema.table
    """
    w = WorkspaceClient()
    result = w.statement_execution.execute_statement(
        warehouse_id=os.environ["DATABRICKS_WAREHOUSE_ID"],
        statement=query,
        wait_timeout="30s",
    )
    if result.status.state.value != "SUCCEEDED":
        return f"Query failed: {result.status.error.message}"

    cols = [c.name for c in result.manifest.schema.columns]
    rows = result.result.data_array or []
    lines = [" | ".join(cols)]
    lines += [" | ".join(str(v) for v in row) for row in rows[:20]]
    return "\n".join(lines)


TOOLS = [query_databricks_sql]
