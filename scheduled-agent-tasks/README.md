# Scheduled agent tasks

Run existing coding agents as **scheduled Lakeflow Jobs** that run as a **service principal**. The shared pieces they use,
MCPs and skills, are deployed once to **Unity Gateway** as governed Unity Catalog objects. Tasks then refer to them by name.
Three agents are included: Claude Code, plus two open-source ones, Codex and OpenCode, running on open-source models.

```
platform/   deployed by a platform team or admin (bundle + script)
  databricks.yml       MCP services: connection, allowed tools, grants      → Unity Gateway: MCPs
  skills/<name>/       shared instructions (SKILL.md)                        → Unity Gateway: skills
agents/     agent setups: harness + model                                    claude-sonnet.yml, codex-glm.yml, …
tasks/      prompts; frontmatter picks agent, MCPs + tools, skills, tags, schedule   cost-review.md
sql/        cost per agent run                                               agent_run_costs.sql
     │
     ▼  databricks bundle deploy  (resources/__init__.py builds the jobs)
agent-task-<task>    one job per task: runs it with its default agent, on its schedule
agent-task-compare   runs any task with every agent in parallel, for side-by-side answers
traces-<task>        MLflow experiment per task: every run of the task, from any agent, with traces in Unity Catalog
     │
     ▼  src/run_task.py  (writes the harness's own config, with only the task's tools allowed, tags every call,
     │                    and records the run as one MLflow trace)
Unity Gateway, as the service principal
  ├─ /ai-gateway/anthropic            Claude Code, OpenCode  → Claude or open-source models
  ├─ /ai-gateway/codex/v1             Codex                  → open-source models
  ├─ /ai-gateway/mcp-services/<name>  MCP tools              → system.ai.dbsql, platform MCPs
  └─ /ai-gateway/skills/              skills                 → platform skills
```

MCPs and skills in Unity Gateway aren't tied to these jobs. Anyone granted access can find and use them from any client,
for example Claude Code on a laptop (`ug claude`), AI Playground, or a Genie agent. Agents here are run profiles, not
Unity Gateway objects: a headless CLI isn't an endpoint, and Unity Gateway agent services can't be called through the gateway yet.

| Agent | Harness | Model |
|---|---|---|
| `claude-sonnet` | [Claude Code](https://docs.claude.com/en/docs/claude-code) | `system.ai.claude-sonnet-5-5` |
| `codex-glm` | [Codex CLI](https://github.com/openai/codex) (Apache-2.0) | `system.ai.glm-5-3` |
| `opencode-kimi` | [OpenCode](https://github.com/sst/opencode) (MIT) | `system.ai.kimi-k3` |

The example task, `cost-review`, follows the `databricks-billing` skill to summarize week-over-week spend from `system.billing.usage`
through the DBSQL MCP. The platform deploys one example external MCP, `databricks_docs` (the public Databricks Developer Docs
MCP), to show registration, tool selection, and grants as code. A Slack example for shared credentials is under [Add an MCP](#add-an-mcp-for-example-jira-or-slack).

## Prerequisites

1. **Unity Gateway** is enabled, along with these previews: **Enhanced Unity Gateway** (for `system.ai.dbsql`), enabled by an
   account admin from the account console's Previews page, and **Unity Gateway skills**, enabled from the workspace Previews page.
2. **A service principal** for the agents with:
   - the `workspace-access` and `databricks-sql-access` entitlements (the gateway rejects tokens without them),
   - `SELECT` on the data the tasks query (for the example: `system.billing.usage` and `system.billing.list_prices`),
   - `USE CATALOG` and `USE SCHEMA` on the platform schema, and access to the model services the agents use,
   - `USE CATALOG`, `USE SCHEMA`, `SELECT`, and `MODIFY` on the trace schema (`ALL PRIVILEGES` alone isn't enough for trace tables).
3. **You** need the *Service Principal: User* role on that service principal so the jobs can run as it
   (**Settings → Identity and access → Service principals → \<name\> → Permissions**).
4. Recommended: set `disallow_writes=true` in `system.ai.dbsql_policy` so agents can only read.
5. Databricks CLI 1.20 or later, and a local virtual environment with a matching `databricks-bundles`:
   ```bash
   uv venv .venv && uv pip install --python .venv/bin/python "databricks-bundles==$(databricks --version | grep -oE '[0-9.]+$')" pyyaml
   ```

```bash
export DATABRICKS_CONFIG_PROFILE=<profile>
export PLATFORM_SCHEMA=<catalog>.<schema>                     # holds shared MCPs, connections, and skills
export AGENTS_SP=<service principal application ID>
export TRACE_CATALOG=<catalog> TRACE_SCHEMA=<schema>          # MLflow trace tables
```

## 1. Deploy the platform (MCPs and skills)

This needs `CREATE CONNECTION`, `CREATE SERVICE`, and `CREATE VOLUME` on the platform schema.

```bash
cd platform

# Connections hold MCP credentials, so they're created once outside the bundle.
databricks connections create --json "$(jq --arg p "schemas/$PLATFORM_SCHEMA" '. + {parent: $p}' connections/databricks_docs.json)"

# MCP services, their allowed tools, and grants.
BUNDLE_VAR_schema=$PLATFORM_SCHEMA BUNDLE_VAR_agents_principal=$AGENTS_SP databricks bundle deploy

# Skills: each skills/<name>/ directory becomes <catalog>.<schema>.<name>, readable by the service principal.
./publish_skills.sh "$PLATFORM_SCHEMA" "$AGENTS_SP"
cd ..
```

To give a team access as well, grant a group `EXECUTE` on an MCP service (add it under `grants`) and `READ VOLUME` on a skill.

## 2. Deploy and run tasks

```bash
export BUNDLE_VAR_service_principal=$AGENTS_SP BUNDLE_VAR_platform_schema=$PLATFORM_SCHEMA
export BUNDLE_VAR_trace_catalog=$TRACE_CATALOG BUNDLE_VAR_trace_schema=$TRACE_SCHEMA

databricks bundle deploy
databricks bundle run cost_review                                  # the task's default agent
databricks bundle run cost_review --params agent=opencode-kimi     # the same task with another agent
databricks bundle run compare_agents --params task=cost-review     # every agent, in parallel
```

Each agent's answer appears in its task's run output, followed by its MLflow trace ID.

## Traces and costs

Every run gets the same tags: `task`, `agent`, `model`, `job_run_id`, plus the task's own `tags:` (for example `team` and
`cost_center`, matching your cost-attribution taxonomy). They're applied in four places:

| Where | What you get |
|---|---|
| **MLflow experiment `traces-<task>`**, one per task (stored as Unity Catalog tables `<task>_*`) | One trace per run, from whichever agent ran it: the prompt, the answer, a span per model call and per tool call, and the trace's total tokens. The trace's session is the job run, so a compare run groups its agents' traces, and its user is the service principal. Task owners watch one experiment; filter by `agent` to compare. |
| **Unity Gateway request tags** (a header on every model and MCP call) | `system.ai_gateway.usage.request_tags`, and `databricks.request_tags` on each span in the unified trace table if your metastore has it (**Govern → Traces**): full prompts, responses, tool arguments, and results. |
| **Job tags** | `system.lakeflow.jobs.tags`, to join with job compute in `system.billing.usage`. For tags directly in billing `custom_tags`, set a serverless usage policy on the jobs. |
| **`sql/agent_run_costs.sql`** | Estimated list cost per run and agent: exact job compute per job run, plus model cost split by tokens. |

Compare agents on one task in its experiment (filter on `agent`, or open the compare run's session), or with SQL:

```sql
SELECT tags['agent'] AS agent, state, execution_duration_ms / 1000 AS seconds,
       variant_get(trace_metadata, '$["mlflow.trace.tokenUsage"]', 'string') AS tokens,
       size(filter(spans, s -> s.name LIKE '%execute_sql%')) AS sql_calls, response
FROM <trace_catalog>.<trace_schema>.<task>_trace_unified          -- task name with underscores, e.g. cost_review
WHERE tags['job_run_id'] = '<compare_agents run ID>';
```

The usage and billing tables can lag by a few hours. MLflow traces and gateway spans arrive within minutes.

## Add a task

Create `tasks/<name>.md`. The next deploy creates job `agent-task-<name>` and its experiment `traces-<name>`.

```markdown
---
agent: claude-sonnet                              # default agent for scheduled runs
mcps:                                             # Unity Gateway MCP services → tools this task may call
  system.ai.dbsql: [execute_sql, poll_sql_result]
  databricks_docs: [get_doc_resource]             # names without a catalog resolve to the platform schema
skills: [databricks-billing]                      # loaded first through /ai-gateway/skills/
tags:                                             # added to the job, every gateway request, and the MLflow trace
  team: data-platform
  cost_center: finops
schedule:                                         # optional; passed to the job as-is
  quartz_cron_expression: "0 0 8 ? * MON"
  timezone_id: America/Los_Angeles
  pause_status: UNPAUSED
---
The prompt. Name the MCP tools it should use, and say not to use a shell.
```

Put reusable knowledge (table semantics, calculation rules, house style) in a skill rather than in each prompt. The skill is
then shared by every task and by people using the same skills interactively.

## Add an agent

Create `agents/<name>.yml` with a `harness` (`claude`, `codex`, or `opencode`) and a `model`. The compare job picks it up on the next deploy.

- `claude` and `opencode` call `/ai-gateway/anthropic`, so they work with Claude models and with open-source models that support the Anthropic Messages API.
- `codex` calls `/ai-gateway/codex/v1` and needs a model that supports the Responses API.

Before switching a task to a cheaper agent, run the compare job and check the answers against a direct query.
In testing, open-source models sometimes drifted from the requested date window or ranked line items wrongly. A skill that states the rules helped,
but only when the agent loaded it: the trace shows whether it called `load_skill`.

## Add an MCP (for example Jira or Slack)

The agents' identity in Databricks is the service principal. In Jira and Slack, they act as whatever credential is stored in the
MCP's connection. Use a shared service account for that credential, not a person. The built-in `system.ai.atlassian` and
`system.ai.slack` services use per-user sign-in, so for a shared identity, register the vendor's MCP in `platform/`.

1. **Create the connection** (admin rights needed in the workspace and in the vendor's tool):
   - **Jira (Atlassian Rovo MCP)**, no custom app needed:
     1. An Atlassian org admin creates a **service account** with access to the target project.
     2. They create **OAuth 2.0 client credentials** for it with the `*:agent-interface` scopes the tasks need, plus `read:me` and `read:account`.
     3. Create an HTTP connection to `https://mcp.atlassian.com/v2/mcp` using **OAuth M2M** with that client ID and secret.
     4. Tools need your site's cloud ID with this authentication, so put it in the task prompt.
   - **Slack (official Slack MCP)**, needs a Slack app:
     1. A Slack admin creates an **internal Slack app**, enables **Slack MCP Server** under **Agents**, and adds the user scopes the tasks need (for example `chat:write`).
     2. Create a dedicated Slack user for the agent. Slack's MCP accepts **user tokens only**, so messages appear as that user.
     3. Create a connection to `https://mcp.slack.com/mcp` with **OAuth U2M Shared**, and sign in once as the agent user.
2. **Register it** by adding an entry under `resources.mcp_services` in `platform/databricks.yml`, then redeploy the platform bundle.
   For example, Slack limited to posting messages, usable by the agents' service principal and a team group:
   ```yaml
       slack:
         parent: schemas/${var.schema}
         mcp_service_id: slack
         comment: Slack, acting as the shared agent user
         config:
           source_connection:
             name: connections/${var.schema}.slack
           include_tool_selectors: [slack_send_message]
         grants:
           - principal: ${var.agents_principal}
             privileges: [EXECUTE]
           - principal: data-platform-team
             privileges: [EXECUTE]
   ```
3. **Use it** by adding the service name and the tools a task may call to that task's `mcps:` frontmatter.

Tool names are listed under **Unity Gateway → MCPs → \<service\> → Tools**.

## Notes

- Tools are restricted twice:
  - The platform's `include_tool_selectors` limits what an MCP exposes to anyone.
  - Each task's `mcps:` limits what that task's agent may call.
- Agents run unattended:
  - Claude Code uses `--permission-mode dontAsk` and an allowlist.
  - Codex runs with its shell disabled and `enabled_tools` per server.
  - OpenCode denies every tool except the allowed MCP tools.
- Codex blocks MCP calls when run headless unless `default_tools_approval_mode = "approve"` is set. `run_task.py` sets it.
- Codex reports token usage per turn, not per model call, so its traces show tool spans and the trace total but no model-call spans.
- OpenCode has a built-in `databricks` provider that reads `DATABRICKS_HOST`. `run_task.py` uses its own provider name
  and points `OPENCODE_CONFIG` at the generated file, so the built-in provider isn't picked up.
- HTTP connections require credentials. For a public MCP like `databricks_docs`, the bearer token is a placeholder the server ignores.
- Jobs use serverless compute and download Node.js plus the pinned CLI from `nodejs.org` and npm at the start of each run.
  If your workspace blocks outbound internet, mirror them and change the URLs in `src/run_task.py`.
