import pytest
import yaml
from mcp.server.mcpserver.exceptions import ToolError

from metric_view_mcp.metric_views import check_sql, compact, example_sql, matching_members
from metric_view_mcp.uc import Registry, in_scope, load_include

NAME = "main.demo_semantic.funnel_metrics"
DEFINITION = yaml.safe_load("""
version: 1.1
source: main.demo_raw.app_events
dimensions:
  - name: Event Date
    expr: event_date
    synonyms: [day]
measures:
  - name: Upgrade Viewers
    expr: COUNT(DISTINCT member_id) FILTER (WHERE event_name = 'upgrade_viewed')
    display_name: Upgrade Viewers
""")
ALLOWED = {NAME, "main.demo_semantic.engagement_metrics"}


@pytest.mark.parametrize("definition", [DEFINITION, {**{k: v for k, v in DEFINITION.items() if k != "dimensions"},
                                                     "fields": DEFINITION["dimensions"]}])
def test_example_sql_uses_measure_syntax(definition):
    assert example_sql(NAME, definition) == (
        "SELECT `Event Date`, MEASURE(`Upgrade Viewers`)\n"
        "FROM `main`.`demo_semantic`.`funnel_metrics`\n"
        "GROUP BY ALL\n"
        "LIMIT 10"
    )


def test_compact_lists_members_with_synonyms():
    assert compact(DEFINITION) == {"measures": ["Upgrade Viewers"], "dimensions": ["Event Date (day)"]}


def test_matching_members_searches_names_display_names_synonyms_and_comments():
    definition = {
        "measures": [{"name": "Active Users", "synonyms": ["WAU", "weekly actives"]},
                     {"name": "Events", "comment": "Total app events"}],
        "fields": [{"name": "Week", "display_name": "Calendar Week"}],
    }
    assert matching_members(definition, ["weekly", "actives"]) == {"Active Users": 2}
    assert matching_members(definition, ["wau"]) == {"Active Users": 1}
    assert matching_members(definition, ["calendar"]) == {"Week": 1}
    assert matching_members(definition, ["app"]) == {"Events": 1}
    assert matching_members(definition, ["revenue"]) == {}


@pytest.mark.parametrize("sql", [
    example_sql(NAME, DEFINITION),
    "SELECT `Week`, MEASURE(`Active Users`) FROM main.demo_semantic.engagement_metrics "
    "WHERE `Platform` = 'ios' GROUP BY ALL ORDER BY 1 DESC LIMIT 4",
    "WITH w AS (SELECT `Week`, MEASURE(`Active Users`) AS u FROM main.demo_semantic.engagement_metrics GROUP BY ALL) "
    "SELECT `Week`, u - LAG(u) OVER (ORDER BY `Week`) FROM w",
    "SELECT * FROM (SELECT MEASURE(`Upgrade Viewers`) FROM MAIN.Demo_Semantic.Funnel_Metrics) t",
    "SELECT MEASURE(a) FROM main.demo_semantic.funnel_metrics UNION ALL "
    "SELECT MEASURE(b) FROM main.demo_semantic.engagement_metrics",
])
def test_allows_queries_on_metric_views(sql):
    check_sql(sql, ALLOWED)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM main.demo_raw.app_events",
    "SELECT * FROM (SELECT * FROM main.demo_raw.app_events) t",
    "SELECT MEASURE(a), (SELECT max(x) FROM main.demo_raw.t) FROM main.demo_semantic.funnel_metrics",
    "SELECT * FROM main.demo_semantic.funnel_metrics JOIN main.demo_raw.dim_member USING (x)",
    "SELECT * FROM funnel_metrics",
    "SELECT * FROM read_files('s3://bucket/x')",
    "SELECT * FROM delta.`s3://bucket/x`",
    "SELECT * FROM system.information_schema.tables",
    "DROP TABLE main.demo_semantic.funnel_metrics",
    "INSERT INTO main.demo_semantic.x SELECT 1",
    "SELECT 1 FROM main.demo_semantic.funnel_metrics; DROP TABLE x",
    "SELECT FROM WHERE",
    "SELECT http_request(conn => 'c', method => 'POST', path => '/', json => to_json(named_struct('v', MEASURE(a)))) "
    "FROM main.demo_semantic.funnel_metrics",
    "SELECT ai_query('databricks-claude', 'summarize') FROM main.demo_semantic.funnel_metrics",
    "SELECT AI_GEN('x') FROM main.demo_semantic.funnel_metrics",
    "SELECT remote_query('conn', query => 'SELECT 1') FROM main.demo_semantic.funnel_metrics",
    "SELECT secret('scope', 'key') FROM main.demo_semantic.funnel_metrics",
    "SELECT try_secret('scope', 'key') FROM main.demo_semantic.funnel_metrics",
    "SELECT (SELECT count(*) FROM read_files('s3://b/x')) FROM main.demo_semantic.funnel_metrics",
    "SELECT * FROM vector_search(index => 'i', query_text => 'q')",
])
def test_rejects_anything_else(sql):
    with pytest.raises(ToolError):
        check_sql(sql, ALLOWED)


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


def test_access_is_config_scope_intersected_with_what_the_user_sees():
    registry = Registry(warehouse_id="w", include=["c.s"])
    registry._visible = lambda user: {n: f"about {n}" for n in ["c.s.b", "c.s.c", "c.other.x"]}
    assert registry.views_for("u@x.com", "user") == {"c.s.b": "about c.s.b", "c.s.c": "about c.s.c"}
    assert registry.resolve("b", "u@x.com", "user") == "c.s.b"
    registry._visible = lambda user: {n: "" for n in ["c.s.b", "c.s.c", "c.t.b", "c.other.x"]}
    registry.include = ["c.s", "c.t"]
    registry._cache.clear()
    with pytest.raises(ToolError, match="matches several metric views.*c.s.b, c.t.b"):
        registry.resolve("b", "u@x.com", "user")
    assert registry.resolve("c.t.b", "u@x.com", "user") == "c.t.b"
    for name in ("a", "x", "c.other.x", "c.raw.events"):
        with pytest.raises(ToolError):
            registry.resolve(name, "u@x.com", "user")
