import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from metric_view_mcp.metric_views import build_query, parse
from metric_view_mcp.scope import in_scope, load_include
from metric_view_mcp.uc import Registry

VIEW = parse(json.loads((Path(__file__).parent / "funnel_metrics_table.json").read_text()))


def test_parse_splits_measures_and_dimensions_without_exposing_source_sql():
    assert [m["name"] for m in VIEW.measures] == ["Upgrade Viewers", "Subscribers Started", "Upgrade Conversion Rate"]
    assert "Acquisition Channel" in [d["name"] for d in VIEW.dimensions]
    assert "app_events" not in str(VIEW)


def test_builds_grouped_query_with_bound_filters():
    sql, params = build_query(
        VIEW, ["upgrade conversion rate"], ["Week", "Platform"],
        filters=[{"dimension": "Platform", "op": "IN", "value": ["ios", "android"]},
                 {"dimension": "Event Date", "op": "BETWEEN", "value": ["2026-06-01", "2026-06-30"]}],
        order_by=["week desc"], limit=10,
    )
    assert sql == (
        "SELECT `Week`, `Platform`, MEASURE(`Upgrade Conversion Rate`) AS `Upgrade Conversion Rate`\n"
        "FROM `main`.`demo_semantic`.`funnel_metrics`\n"
        "WHERE `Platform` IN (:p0, :p1)\n"
        "  AND `Event Date` BETWEEN :p2 AND :p3\n"
        "GROUP BY ALL\n"
        "ORDER BY `Week` DESC\n"
        "LIMIT 10"
    )
    assert [p["value"] for p in params] == ["ios", "android", "2026-06-01", "2026-06-30"]


def test_filter_values_are_bound_not_interpolated():
    sql, params = build_query(VIEW, ["Upgrade Viewers"], filters=[{"dimension": "Country", "op": "=", "value": "US' OR 1=1"}])
    assert "1=1" not in sql and params == [{"name": "p0", "value": "US' OR 1=1"}]


@pytest.mark.parametrize("kwargs", [
    {"measures": []},
    {"measures": ["Revenue"]},
    {"measures": ["Upgrade Viewers"], "dimensions": ["member_id"]},
    {"measures": ["Upgrade Viewers"], "filters": [{"dimension": "Upgrade Viewers", "op": ">", "value": 1}]},
    {"measures": ["Upgrade Viewers"], "filters": [{"dimension": "Country", "op": "IN", "value": "US"}]},
    {"measures": ["Upgrade Viewers"], "order_by": ["Country"]},
])
def test_rejects_anything_outside_the_view(kwargs):
    with pytest.raises(ToolError):
        build_query(VIEW, **kwargs)


def test_limit_is_capped():
    assert build_query(VIEW, ["Upgrade Viewers"], limit=10_000, max_rows=500)[0].endswith("LIMIT 500")


@pytest.mark.parametrize("include, expected", [
    (["*"], True),
    (["prod"], True),
    (["prod.semantic"], True),
    (["prod.semantic.revenue"], True),
    (["prod.finance", "dev"], False),
    (["prod.semantic.rev"], False),
    (["pro"], False),
])
def test_scope_matches_catalog_schema_or_view(include, expected):
    assert in_scope("prod.semantic.revenue", include) is expected


def test_load_include_reads_config(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("include:\n  - Prod.Semantic\n  - '*'\n")
    assert load_include(config) == ["prod.semantic", "*"]


def test_access_is_service_principal_ceiling_intersected_with_user():
    registry = Registry(sp="sp", warehouse_id="w", include=["c.s"])
    registry._visible = {"sp": {"c.s.a", "c.s.b", "c.other.x"}, "user": {"c.s.b", "c.s.c", "c.other.x"}}.get
    registry.definition = lambda name: name
    assert registry.names_for("u@x.com", "user") == {"c.s.b"}
    assert registry.get("b", "u@x.com", "user") == "c.s.b"
    for name in ("a", "c", "x", "c.raw.events"):
        with pytest.raises(ToolError):
            registry.get(name, "u@x.com", "user")
