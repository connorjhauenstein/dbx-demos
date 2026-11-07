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
  - "*"                              # every metric view the caller can see
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

Users still only see the in-scope metric views they can access in Unity Catalog. Redeploy and
restart the app after changing this file.

## Deploy

Prerequisites: Databricks CLI ≥ 1.3, a Unity Catalog workspace with Databricks Apps, and
**user authorization for Apps** (OBO) enabled.

```bash
git clone https://github.com/connorjhauenstein/dbx-demos.git && cd dbx-demos/metric-view-mcp
# edit config.yml
export DATABRICKS_CONFIG_PROFILE=<profile>

databricks bundle deploy
databricks bundle run metric_view_mcp
```

| Variable | Default | Meaning |
|---|---|---|
| `consumer_group` | `account users` | Group allowed to use the app |
| `warehouse_id` | "Serverless Starter Warehouse" | Warehouse that runs queries (serverless autoscales) |

Override either with `BUNDLE_VAR_<name>=...`. Add `-t prod` for a production deployment.

The app runs everything as the caller, so it needs no Unity Catalog grants of its own. Users need
`SELECT` on the metric views they should query, plus `USE CATALOG` / `USE SCHEMA` on their
parents. That's usually granted in the same repo that creates the metric views. They don't need
access to the source tables, because metric views run with their owner's rights.

## Tools

| Tool | Does |
|---|---|
| `list_metric_views` | The whole in-scope catalog, compactly: each view's description plus its measure and dimension names with synonyms, e.g. `Active Users (WAU, weekly actives)`. The agent's own LLM reads it to choose the right metric. For very large catalogs, optional `search` returns only views matching those words, best first |
| `describe_metric_view` | The metric view's complete YAML definition as stored in Unity Catalog (measures, dimensions, synonyms, display names, formats, and any keys added later), plus a ready-to-run `MEASURE()` SQL example |
| `query_metric_views` | Runs one read-only SQL query written by the agent's own LLM. Returns columns and up to 1000 rows |

There's no LLM inside the server. The client's model (Claude, or whichever model the agent uses)
writes the SQL, the same way Cube's MCP takes LLM-written Cube SQL. Before running anything, the
server parses the SQL and rejects it unless it's a single `SELECT` whose every table is an
in-scope metric view the caller can see. CTEs, subqueries, window functions, and joins across
those metric views are fine. Raw tables, file paths, `read_files()`, and writes are rejected.

## Access

A caller sees and queries only metric views that match `config.yml` **and** that they can access
in Unity Catalog. Discovery, definitions, and queries all run with the caller's forwarded token
(OBO), so their grants, row filters, and column masks apply, and query history shows them.

### Strongest setup

A query runs as exactly one identity, so there's no engine-level "service principal scope plus
user permissions". To get both from Unity Catalog itself, grant this MCP's users `SELECT` on the
metric views and nothing on the source tables (metric views run with their owner's rights, so users
don't need source access). Then UC enforces the metric-views-only boundary and each user's row
filters and masks in the same query, and the server's SQL check is a second layer. For users who
also have raw-table access elsewhere, the SQL check is what keeps this MCP on metric views.

**Synonyms matter.** The agent picks metrics from names, descriptions, and synonyms, so add
`synonyms` and `comment` to measures and dimensions in your metric view YAML.

## Connect an agent

The app is named `mcp-metric-views`. The `mcp-` prefix makes it show up in
**Unity Gateway → MCPs** and in AI Playground's tool picker.

- **AI Playground:** Unity Gateway → MCPs → `mcp-metric-views` → *Try in Playground*. Choose a
  model with tools enabled (Claude works; GPT-6.1 Terra doesn't support tools in Playground).
- **Claude Code and other coding agents:** `ug mcp add --names "app:mcp-metric-views"`.
- **Any MCP client:** `https://<app-url>/mcp` with a Databricks OAuth token for the user.

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
