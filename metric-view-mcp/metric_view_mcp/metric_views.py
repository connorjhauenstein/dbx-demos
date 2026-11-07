"""Metric view YAML helpers, and the check that keeps agent-written SQL on metric views."""

import sqlglot
from mcp.server.mcpserver.exceptions import ToolError
from sqlglot import exp

# Functions that reach outside the query (external HTTP, model calls, secrets, files, streams).
BLOCKED_PREFIXES = ("ai_", "read_")
BLOCKED_FUNCTIONS = {"http_request", "remote_query", "secret", "try_secret", "vector_search", "cloud_files"}


def quote(name: str) -> str:
    return ".".join("`" + part.replace("`", "``") + "`" for part in name.split("."))


def example_sql(name: str, definition: dict) -> str:
    """A runnable MEASURE() query over the view's first dimension and measure."""
    measures, dimensions = members(definition)
    columns = [quote(d["name"]) for d in dimensions[:1]] + [f"MEASURE({quote(m['name'])})" for m in measures[:1]]
    return f"SELECT {', '.join(columns)}\nFROM {quote(name)}\nGROUP BY ALL\nLIMIT 10"


def members(definition: dict) -> tuple[list[dict], list[dict]]:
    return definition.get("measures", []), definition.get("dimensions") or definition.get("fields") or []


def compact(definition: dict) -> dict:
    """Measure and dimension names with their synonyms, e.g. "Active Users (WAU, weekly actives)"."""
    def label(member):
        synonyms = member.get("synonyms") or []
        return f"{member['name']} ({', '.join(synonyms)})" if synonyms else member["name"]

    measures, dimensions = members(definition)
    return {"measures": [label(m) for m in measures], "dimensions": [label(d) for d in dimensions]}


def matching_members(definition: dict, terms: list[str]) -> dict[str, int]:
    """Measures and dimensions whose name, display name, synonyms, or comment contain search terms,
    with how many terms each matched."""
    matches = {}
    measures, dimensions = members(definition)
    for member in measures + dimensions:
        text = " ".join([member.get("name", ""), member.get("display_name", ""), member.get("comment", ""),
                         *member.get("synonyms", [])]).lower()
        hits = sum(term in text for term in terms)
        if hits:
            matches[member["name"]] = hits
    return matches


def check_sql(sql: str, allowed: set[str]) -> None:
    """Allow one read-only query whose every table is an allowed metric view (or a CTE it defines)."""
    try:
        statements = sqlglot.parse(sql, read="databricks")
    except sqlglot.errors.ParseError as e:
        raise ToolError(f"Could not parse the SQL: {e}")
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ToolError("Send exactly one SELECT query.")
    query = statements[0]
    for func in query.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name.startswith(BLOCKED_PREFIXES) or name in BLOCKED_FUNCTIONS:
            raise ToolError(f"{name}() isn't allowed. Query metric views with standard SQL functions.")
    ctes = {cte.alias.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        name = ".".join(p for p in (table.catalog, table.db, table.name) if p).lower()
        if name in ctes or name in allowed:
            continue
        raise ToolError(
            f"{table.sql(dialect='databricks')!r} is not an available metric view. Query only metric views "
            "from list_metric_views, by full catalog.schema.view name."
        )
