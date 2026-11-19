# Scheduled agent tasks

Run Claude Code or OpenCode (open source) headless as **scheduled Lakeflow Jobs** that run as a **service principal**.
Each task is a prompt plus a small config file in git. Models and MCPs come from **Unity Gateway**, so access, usage,
and traces are governed in Unity Catalog, and runs don't depend on anyone's laptop or personal account.

```
tasks/<task>/
  prompt.md        what the agent should do
  task.yml         harness, model, Unity Gateway MCPs, Unity Catalog function tools, cost tags, schedule
     │
     ▼  databricks bundle deploy  (resources/__init__.py)
agent-task-<task>    job: runs the task on its schedule, as the service principal
traces-<task>        MLflow experiment: one trace per run, stored in Unity Catalog
     │
     ▼  src/run_task.py  (writes the harness's config, tags every gateway call, records the trace)
Unity Gateway                         models and MCPs
  ├─ /ai-gateway/anthropic            models: Claude, or open-source models that support the Anthropic Messages API
  └─ /ai-gateway/mcp-services/<name>  MCPs listed in task.yml, e.g. system.ai.dbsql
Databricks managed MCP                Unity Catalog functions listed in task.yml, e.g. post_slack_message
sql/agent_run_costs.sql              estimated cost per run: job compute, model, and SQL warehouse
sql/slack_tool.sql                   a governed Slack tool: bot token in a UC connection, exposed as a UC function
```

The example task, `cost-review`, summarizes week-over-week spend from `system.billing.usage` with one query through the DBSQL MCP.

## Prerequisites

1. **Unity Gateway** is enabled, with the **Enhanced Unity Gateway** preview for `system.ai.dbsql` (an account admin turns it on from the account console's Previews page).
   For tools from Unity Catalog functions, also enable the **Managed MCP Servers** workspace preview.
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
functions: []                    # optional; Unity Catalog functions the agent may call, e.g. <catalog>.<schema>.post_slack_message
tags:                            # added to the job, every gateway request, and the MLflow trace
  team: data-platform
  cost_center: finops
schedule:                        # optional; passed to the job as-is
  quartz_cron_expression: "0 0 8 ? * MON"
  timezone_id: America/Los_Angeles
  pause_status: UNPAUSED
```

A prompt can include `{traces_url}`; `run_task.py` replaces it with the task's MLflow Traces link, for example for a
"View traces" button in a Slack message.

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

Choose a headless connector in this order:

1. **The vendor's MCP in Unity Gateway with a shared credential**, when the vendor's MCP accepts one (service account,
   OAuth client credentials, or an API key). You get its full toolset, tool selection, policies, and gateway traces.
2. **A Unity Catalog function over an HTTP connection**, when the vendor's MCP needs a person's sign-in or you only need
   one or two actions. `sql/slack_tool.sql` is an example.
3. **Your own MCP server as a Databricks App**, when you need many custom tools.

## Tools from Unity Catalog functions

List functions in `task.yml` under `functions:`. Databricks managed MCP serves each one as a tool
(`/api/2.0/mcp/functions/<catalog>/<schema>/<function>`), so agents call it like any other MCP tool, and the call shows up
in the trace. Grant the agents' service principal `EXECUTE` on the function.

### Post to Slack as a bot

Slack's own MCP accepts only user tokens, so a team-owned agent posts with a Slack app's **bot token** instead:

1. In your Slack app, add the bot scopes `chat:write` and `im:write`, reinstall it, and copy the **Bot User OAuth Token** (`xoxb-…`).
   The client ID and secret aren't needed.
2. Store the token in a Databricks secret: `databricks secrets create-scope slack`, then `databricks secrets put-secret slack bot_token`.
3. Fill in the placeholders in `sql/slack_tool.sql` and run it. It creates the `slack_bot` HTTP connection from the secret,
   the `post_slack_message(channel, text, blocks)` function, and the grants. Rerun it after any change: replacing a
   function drops its grants, and the file restores them.
4. Add the function to a task's `functions:`, and tell the prompt where to post, for example
   "post the summary to Slack channel `C…` with `post_slack_message`". For a richer message, include a Block Kit template
   in the prompt and ask the agent to pass it as `blocks`; Slack's error (for example `invalid_blocks`) comes back to the
   agent so it can fix the JSON and retry.

Things to know:

- The function calls Slack with the caller's access to the connection, so the service principal needs `USE CONNECTION`
  as well as `EXECUTE`. With `USE CONNECTION` it could also call Slack's API directly through SQL, so keep the bot
  token's scopes narrow, or give each agent its own connection.
- Posting is the agent's decision, driven by the prompt. A failed post doesn't fail the job. For guaranteed delivery,
  have the job post after the agent finishes.
- `http_request`, which the function uses, is deprecated in favor of the Unity Catalog connections proxy. Use the proxy
  for production code.

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
- **`sql/agent_run_costs.sql`:** estimated list cost per run, in four parts:
  - `job_compute_usd`: the job's serverless compute, exact per job run.
  - `model_usd`: model usage, billed per hour, split across that hour's calls by token share.
  - `sql_usd`: the SQL warehouse behind the DBSQL MCP. Each hour of warehouse cost, idle time included, is split across
    that hour's queries by duration, and the agent's queries are matched to the run by service principal and time window.
    This is often the largest part, because a warehouse that starts for one run stays up until it auto-stops. Give agents
    their own warehouse to make it exact.
  - `status`: `pending` until billing covers the run (billing lags by a few hours); `total_usd` is blank until then.
- For tags directly in billing `custom_tags`, set a serverless usage policy on the jobs.

## Notes

- Claude Code runs with `--permission-mode dontAsk`, so anything outside the task's MCPs is denied.
  OpenCode denies every tool except the task's MCPs.
- OpenCode has a built-in `databricks` provider that reads `DATABRICKS_HOST`. `run_task.py` uses its own provider name
  and points `OPENCODE_CONFIG` at the generated file, so the built-in provider isn't picked up.
- Jobs use serverless compute and download Node.js plus the pinned CLI from `nodejs.org` and npm at the start of each run.
  If your workspace blocks outbound internet, mirror them and change the URLs in `src/run_task.py`.
