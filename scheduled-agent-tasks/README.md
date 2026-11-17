# Scheduled agent tasks

Run Claude Code or OpenCode (open source) headless as **scheduled Lakeflow Jobs** that run as a **service principal**.
Each task is a prompt plus a small config file in git. Models and MCPs come from **Unity Gateway**, so access, usage,
and traces are governed in Unity Catalog, and runs don't depend on anyone's laptop or personal account.

```
tasks/<task>/
  prompt.md        what the agent should do
  task.yml         harness, model, Unity Gateway MCPs, cost tags, schedule
     │
     ▼  databricks bundle deploy  (resources/__init__.py)
agent-task-<task>    job: runs the task on its schedule, as the service principal
traces-<task>        MLflow experiment: one trace per run, stored in Unity Catalog
     │
     ▼  src/run_task.py  (writes the harness's config, tags every gateway call, records the trace)
Unity Gateway
  ├─ /ai-gateway/anthropic            models: Claude, or open-source models that support the Anthropic Messages API
  └─ /ai-gateway/mcp-services/<name>  MCPs listed in task.yml, e.g. system.ai.dbsql
sql/agent_run_costs.sql              estimated cost per run
```

The example task, `cost-review`, summarizes week-over-week spend from `system.billing.usage` with one query through the DBSQL MCP.

## Prerequisites

1. **Unity Gateway** is enabled, with the **Enhanced Unity Gateway** preview for `system.ai.dbsql` (an account admin turns it on from the account console's Previews page).
2. **A service principal** for the agents with:
   - the `workspace-access` and `databricks-sql-access` entitlements (the gateway rejects tokens without them),
   - access to the model services and MCP services the tasks use, and `SELECT` on the data they query
     (for the example: `system.billing.usage` and `system.billing.list_prices`),
   - `USE CATALOG`, `USE SCHEMA`, `SELECT`, and `MODIFY` on the trace schema.
3. **You** need the *Service Principal: User* role on that service principal so the jobs can run as it
   (**Settings → Identity and access → Service principals → \<name\> → Permissions**).
4. Recommended: set `disallow_writes=true` in `system.ai.dbsql_policy` so agents can only read.
5. Databricks CLI 1.20 or later, and a local virtual environment with a matching `databricks-bundles`:
   ```bash
   uv venv .venv && uv pip install --python .venv/bin/python "databricks-bundles==$(databricks --version | grep -oE '[0-9.]+$')" pyyaml
   ```

## Deploy and run

```bash
export DATABRICKS_CONFIG_PROFILE=<profile>
export BUNDLE_VAR_service_principal=<service principal application ID>
export BUNDLE_VAR_trace_catalog=<catalog> BUNDLE_VAR_trace_schema=<schema>

databricks bundle deploy
databricks bundle run cost_review                                                      # harness and model from task.yml
databricks bundle run cost_review --params harness=opencode,model=system.ai.kimi-k3    # try another harness and model
```

The schedule in `task.yml` is deployed paused. Set `pause_status: UNPAUSED` and redeploy to turn it on.

## Add a task

Create a folder in `tasks/` with a `prompt.md` and a `task.yml`. The next deploy creates its job and experiment.

```yaml
harness: claude                  # claude or opencode
model: system.ai.claude-sonnet-5-5
mcps: [system.ai.dbsql]          # Unity Gateway MCP services the agent may use
tags:                            # added to the job, every gateway request, and the MLflow trace
  team: data-platform
  cost_center: finops
schedule:                        # optional; passed to the job as-is
  quartz_cron_expression: "0 0 8 ? * MON"
  timezone_id: America/Los_Angeles
  pause_status: UNPAUSED
```

Write prompts that say exactly what to run. The example gives the agent its one query and tells it not to explore schemas
or use a shell, which keeps runs short, cheap, and consistent across models.

## MCPs

Agents may use every tool on the MCPs listed in `task.yml`. Manage MCPs in Unity Gateway (**Unity Gateway → MCPs**), not in this repo:

- **Which tools exist:** the MCP's **Tools** tab. Hide tools there to keep them from every caller.
- **Who can use it:** grant `EXECUTE` on the MCP service to the agents' service principal, or to a group.
- **Whose identity it acts as:** set by the MCP's connection. For a scheduled job, the connection needs a shared
  service-account credential (OAuth M2M, shared OAuth, or a bearer token). Per-user sign-in, as used by the built-in
  `system.ai.slack` and `system.ai.atlassian`, can't work for a service principal.

Reference an MCP by its full name, for example `mcps: [system.ai.dbsql, main.agents.jira]`.
To post results to Slack, an existing Slack app's bot token in a Databricks secret is simpler than an MCP.

## Traces and costs

Every run is tagged with `task`, `harness`, `model`, `job_run_id`, and the task's `tags`. Tags are applied to the job,
to every Unity Gateway request (`system.ai_gateway.usage.request_tags`), and to the MLflow trace.

- **Experiment `traces-<task>`:** one trace per run of the task, whichever harness or model ran it. The trace has the prompt, the answer, a span
  per model call and per tool call, and total tokens. Its session is the job run, and its user is the service principal.
  Filter by `harness` or `model` to compare runs, or query the `<task>_trace_unified` table:
  ```sql
  SELECT tags['harness'] AS harness, tags['model'] AS model, state, execution_duration_ms / 1000 AS seconds,
         variant_get(trace_metadata, '$["mlflow.trace.tokenUsage"]', 'string') AS tokens, response
  FROM <trace_catalog>.<trace_schema>.cost_review_trace_unified
  ORDER BY request_time DESC;
  ```
- **`sql/agent_run_costs.sql`:** estimated list cost per run. Job compute is exact per job run. Model cost is split
  across runs by token share, because model usage is billed per hour. Usage and billing tables can lag by a few hours.
- For tags directly in billing `custom_tags`, set a serverless usage policy on the jobs.

## Notes

- Claude Code runs with `--permission-mode dontAsk`, so anything outside the task's MCPs is denied.
  OpenCode denies every tool except the task's MCPs.
- OpenCode has a built-in `databricks` provider that reads `DATABRICKS_HOST`. `run_task.py` uses its own provider name
  and points `OPENCODE_CONFIG` at the generated file, so the built-in provider isn't picked up.
- Jobs use serverless compute and download Node.js plus the pinned CLI from `nodejs.org` and npm at the start of each run.
  If your workspace blocks outbound internet, mirror them and change the URLs in `src/run_task.py`.
