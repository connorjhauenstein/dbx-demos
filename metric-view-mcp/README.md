# Metric-view MCP

An MCP server that exposes **only Unity Catalog metric views**, so agents (Claude, AI Playground,
Agent Bricks) query your governed semantic layer instead of raw tables. It's one Databricks App
deployed with one bundle. You choose which metric views it exposes in `config.yml`.

This repo is only the MCP server. Your metric views live wherever you already manage them, for
example a bundle that creates them from YAML with a SQL job, or a dbt project.

## Choose your metric views

Edit `config.yml`. Put one entry per line, in any mix:

```yaml
include:
  - "*"                              # every metric view the app's service principal can see
  - prod                             # every metric view in a catalog
  - prod.semantic                    # every metric view in a schema
  - prod.finance.revenue_metrics     # one metric view
```

For example, to expose a few specific views plus one whole schema:

```yaml
include:
  - prod.finance.revenue_metrics
  - prod.finance.margin_metrics
  - prod.marketing
```

The app and the grant job both read this file. Rerun the grant job after changing it.

## Deploy

Prerequisites: Databricks CLI ≥ 1.3, a Unity Catalog workspace with Databricks Apps, and
**user authorization for Apps** (OBO) enabled.

```bash
git clone https://github.com/connorjhauenstein/dbx-demos.git && cd dbx-demos/metric-view-mcp
# edit config.yml
export DATABRICKS_CONFIG_PROFILE=<profile>

databricks bundle deploy
databricks bundle run grant_metric_view_access   # rerun after changing config.yml
databricks bundle run metric_view_mcp
```

| Variable | Default | Meaning |
|---|---|---|
| `consumer_group` | `account users` | Group allowed to use the app and query the metric views |
| `warehouse_id` | "Serverless Starter Warehouse" | Warehouse that runs queries (serverless autoscales) |

Override either with `BUNDLE_VAR_<name>=...`. Add `-t prod` for a production deployment.

The grant job gives `SELECT` on each in-scope metric view, plus `USE CATALOG` / `USE SCHEMA` on
their parents, to the app's service principal and to `consumer_group`. Nothing is granted on
source tables, because metric views run with their owner's rights. Whoever runs the job needs
permission to grant on those metric views.

## Tools

| Tool | Does |
|---|---|
| `list_metric_views` | Metric views the caller can use, with measure and dimension names |
| `describe_metric_view` | Measures and dimensions, with types, descriptions, and a ready-to-run `MEASURE()` SQL example |
| `query_metric` | `view`, `measures`, `dimensions`, `filters`, `order_by`, `limit`. Returns rows plus the SQL that ran |

`query_metric` never takes free-form SQL. It checks every name against the metric view's
definition and binds filter values as parameters.

## Access: service principal ceiling ∩ user

- **Ceiling:** only metric views that match `config.yml` and that the app's service principal can
  read are offered. Raw tables never are.
- **Scope down (OBO):** each caller's token is forwarded. Discovery and queries run as the user,
  so their grants, row filters, and column masks apply, and query history shows them.

## Connect an agent

The app is named `mcp-metric-views`. The `mcp-` prefix makes it show up in
**Unity Gateway → MCPs** and in AI Playground's tool picker.

- **AI Playground:** Unity Gateway → MCPs → `mcp-metric-views` → *Try in Playground*. Choose a
  model with tools enabled (Claude works; GPT-6.1 Terra doesn't support tools in Playground).
- **Claude Code and other coding agents:** `ug mcp add --names "app:mcp-metric-views"`.
- **Any MCP client:** `https://<app-url>/mcp` with a Databricks OAuth token for the user.

### Pair with the Databricks SQL MCP (optional)

Add `system.ai.dbsql` (Unity Gateway beta) next to this server. The agent discovers metrics here,
then adapts `sql_example` and runs it with `execute_sql`. That's the same pattern as Cube's
`searchDataModel` + `runQuery`. `execute_sql` runs any SQL as the user, so grant users `SELECT`
on the metric views, not on raw tables. To make it read-only, set `disallow_writes = true` on
the built-in `system.ai.dbsql_policy`. This applies to every user of `system.ai.dbsql` in the account.

## Observability

Agents built on Databricks (Playground, Agent Bricks, MLflow-traced agents) record each tool call
and the SQL it returned in their traces. Every query also runs as the user, so
`system.query.history` shows who queried which metric view from any client.

## Test

```bash
pip install -r requirements.txt pytest && python -m pytest tests
python scripts/smoke_test.py https://<app-url>/mcp --token "$(databricks auth token | jq -r .access_token)" \
  --view <an in-scope metric view> --raw-table <a source table that must be rejected>
```
