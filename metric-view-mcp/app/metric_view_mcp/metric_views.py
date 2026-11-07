"""Metric view definitions and the only SQL this server can produce against them."""

import json
from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError

OPERATORS = ("=", "!=", ">", ">=", "<", "<=", "IN", "BETWEEN")


@dataclass(frozen=True)
class MetricView:
    name: str
    description: str
    measures: list[dict]
    dimensions: list[dict]


def parse(table: dict) -> MetricView:
    """Build a MetricView from a Unity Catalog Tables API response."""
    measures, dimensions = [], []
    for col in table["columns"]:
        field = {"name": col["name"], "type": col["type_text"], "description": col.get("comment", "")}
        kind = json.loads(col["type_json"])["metadata"].get("metric_view.type")
        (measures if kind == "measure" else dimensions).append(field)
    return MetricView(table["full_name"].lower(), table.get("comment", ""), measures, dimensions)


def quote(name: str) -> str:
    return ".".join("`" + part.replace("`", "``") + "`" for part in name.split("."))


def build_query(view: MetricView, measures, dimensions=(), filters=(), order_by=(), limit=100, max_rows=1000):
    """Return (sql, parameters). Names must exist in the view; filter values are always bound."""

    def pick(name, fields, kind):
        by_key = {f["name"].lower(): f["name"] for f in fields}
        if name.lower() not in by_key:
            raise ToolError(f"Unknown {kind} {name!r}. Valid {kind}s: {', '.join(by_key.values())}")
        return by_key[name.lower()]

    if not measures:
        raise ToolError("At least one measure is required.")
    measures = [pick(m, view.measures, "measure") for m in measures]
    dimensions = [pick(d, view.dimensions, "dimension") for d in dimensions]

    params = []

    def bind(value):
        params.append({"name": f"p{len(params)}", "value": str(value)})
        return f":p{len(params) - 1}"

    where = []
    for f in filters:
        column, op, value = quote(pick(f["dimension"], view.dimensions, "dimension")), f["op"], f["value"]
        if op in ("IN", "BETWEEN") and not (isinstance(value, list) and value and (op == "IN" or len(value) == 2)):
            raise ToolError(f"{op} needs a list value ([low, high] for BETWEEN).")
        if op == "IN":
            where.append(f"{column} IN ({', '.join(bind(v) for v in value)})")
        elif op == "BETWEEN":
            where.append(f"{column} BETWEEN {bind(value[0])} AND {bind(value[1])}")
        else:
            where.append(f"{column} {op} {bind(value)}")

    selected = [{"name": n} for n in dimensions + measures]
    order = []
    for o in order_by:
        field, _, direction = o.strip().rpartition(" ")
        if direction.upper() not in ("ASC", "DESC"):
            field, direction = o.strip(), "ASC"
        order.append(f"{quote(pick(field, selected, 'selected field'))} {direction.upper()}")

    sql = "SELECT " + ", ".join([quote(d) for d in dimensions] + [f"MEASURE({quote(m)}) AS {quote(m)}" for m in measures])
    sql += f"\nFROM {quote(view.name)}"
    if where:
        sql += "\nWHERE " + "\n  AND ".join(where)
    sql += "\nGROUP BY ALL"
    if order:
        sql += "\nORDER BY " + ", ".join(order)
    sql += f"\nLIMIT {min(limit, max_rows)}"
    return sql, params
