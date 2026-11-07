# Metric-view MCP

An MCP server that exposes **only Unity Catalog metric views**, so agents (Claude, AI Playground,
Agent Bricks) query your governed semantic layer instead of raw tables. It's one Databricks App
deployed with one bundle. Point it at your metric views with a single variable.

## Tools

| Tool | Does |
|---|---|
| `list_metric_views` | Metric views the caller can use, with measure and dimension names |
| `describe_metric_view` | Measures and dimensions, with types, descriptions, and a ready-to-run `MEASURE()` SQL example |
| `query_metric` | `view`, `measures`, `dimensions`, `filters`, `order_by`, `limit`. Returns rows plus the SQL that ran |

`query_metric` never takes free-form SQL. It checks every name against the metric view's
definition and binds filter values as parameters. For queries it can't express, pair this server
with the Databricks SQL MCP (see below).

## Access: service principal ceiling ∩ user

- **Ceiling:** the app's service principal only gets `SELECT` on metric views, and only
  `METRIC_VIEW` objects in `allowed_schemas` are offered. Raw tables never are.
- **Scope down (OBO):** each caller's token is forwarded. Queries run as the user, so their
  grants, row filters, and column masks apply, and query history shows them.
- **Source tables:** no one needs grants on them. Metric views run with their owner's rights.

## Prerequisites

- Databricks CLI ≥ 1.3 and a Unity Catalog workspace with Databricks Apps
- **User authorization for Apps** (OBO), so the app can act as each caller
- One or more schemas containing metric views (or run the demo below)
- A SQL warehouse. Serverless is recommended so queries autoscale; it defaults to "Serverless Starter Warehouse"

## Deploy and point it at your metric views

```bash
git clone https://github.com/connorjhauenstein/dbx-demos.git && cd dbx-demos/metric-view-mcp

export DATABRICKS_CONFIG_PROFILE=<profile>
export BUNDLE_VAR_allowed_schemas="my_catalog.my_semantic_schema"   # comma-separate several

databricks bundle deploy
databricks bundle run grant_metric_view_access
databricks bundle run metric_view_mcp
```

| Variable | Default | Meaning |
|---|---|---|
| `allowed_schemas` | required | Comma-separated `catalog.schema` list. Only metric views here are exposed |
| `consumer_group` | `account users` | Group allowed to use the app and query the metric views |
| `warehouse_id` | "Serverless Starter Warehouse" | Warehouse that runs queries |

The grant job gives `SELECT` on each metric view to the app's service principal and to
`consumer_group`. Rerun it after adding metric views. Override other variables the same way
(`BUNDLE_VAR_consumer_group=analysts`), and add `-t prod` for a production deployment.

The app is named `mcp-metric-views`. The `mcp-` prefix makes it show up in
**Unity Gateway → MCPs** and in AI Playground's tool picker.

## Connect an agent

- **AI Playground:** Unity Gateway → MCPs → `mcp-metric-views` → *Try in Playground*. Choose a
  model with tools enabled (Claude works; GPT-6.1 Terra doesn't support tools in Playground).
- **Claude Code and other coding agents:** `ug mcp add --names "app:mcp-metric-views"`.
- **Any MCP client:** `https://<app-url>/mcp` with a Databricks OAuth token for the user.

### Pair with the Databricks SQL MCP (optional)

Add `system.ai.dbsql` (Unity Gateway beta) next to this server. The agent discovers metrics here,
then adapts `sql_example` and runs it with `execute_sql`. That's the same pattern as Cube's
`searchDataModel` + `runQuery`. `execute_sql` runs any SQL as the user, so:

- grant users `SELECT` on the metric views, not on raw tables
- make it read-only by setting `disallow_writes = true` on the built-in `system.ai.dbsql_policy`.
  This applies to every user of `system.ai.dbsql` in the account.

## Demo data (optional)

```bash
export BUNDLE_VAR_allowed_schemas="<catalog>.demo_semantic"
databricks bundle deploy
databricks bundle run setup_demo_data --params catalog=<catalog>
databricks bundle run grant_metric_view_access
```

This creates synthetic app events in `<catalog>.demo_raw` and two metric views
(`engagement_metrics`, `funnel_metrics`) in `<catalog>.demo_semantic`. It also creates a plain
`scratch_notes` table, which the MCP must ignore.

## Test

```bash
PYTHONPATH=app python -m pytest tests
python scripts/smoke_test.py https://<app-url>/mcp --token "$(databricks auth token | jq -r .access_token)" \
  --view funnel_metrics --raw-table <catalog>.demo_raw.app_events
```

The smoke test lists and queries metric views, and checks that raw tables, plain tables,
invented measures, and injection attempts are rejected.
