# Scheduled agent tasks

Run existing coding agents (Claude Code, or Codex on an open-source model) as **scheduled Lakeflow Jobs** that
run as a **service principal**. Prompts, MCP connections, and tool allowlists live in git, so shared tasks don't
depend on anyone's laptop or personal account.

```
Lakeflow Job (schedule / run-now / table trigger)  ── run_as: service principal
  └─ src/run_task.py  → installs the agent CLI, runs tasks/<task>.md headless
       └─ Unity Gateway (UC grants checked on every call)
            ├─ /ai-gateway/anthropic       Claude Code  → Claude models
            ├─ /ai-gateway/codex/v1        Codex        → open-source models (GLM, Kimi, …)
            └─ /ai-gateway/mcp-services/…  MCP tools    → system.ai.dbsql, plus any MCP you register
```

| Path | Contents |
|---|---|
| `databricks.yml` | One job per task: schedule, `run_as`, and `task` / `harness` parameters |
| `tasks/*.md` | Prompts. Both agents use the same prompt |
| `agents/claude/` | `mcp.json` (MCP servers) and `settings.json` (model + tool allowlist) |
| `agents/codex/config.toml` | Model, MCP servers, and tool allowlist for Codex |
| `src/run_task.py` | Gets the run-as token, installs the CLI, runs the agent, fails the job on error |

The example task, `cost-review`, reads `system.billing.usage` through the DBSQL MCP and summarizes week-over-week spend.

## Prerequisites

1. **Unity Gateway** is enabled, and so is the **Enhanced Unity Gateway** preview (for `system.ai.dbsql`). An account admin turns these on from the account console's Previews page.
2. **A service principal** for the agent with:
   - the `workspace-access` and `databricks-sql-access` entitlements (the gateway rejects tokens without them),
   - `SELECT` on the data the prompts query (for the example: `system.billing.usage` and `system.billing.list_prices`),
   - access to the model services the agents use.
3. **You** need the *Service Principal: User* role on that service principal so the job can run as it
   (**Settings → Identity and access → Service principals → \<name\> → Permissions**).
4. Recommended: set `disallow_writes=true` in `system.ai.dbsql_policy` so the agent can only read.

## Deploy and run

```bash
export DATABRICKS_CONFIG_PROFILE=<profile>
export BUNDLE_VAR_service_principal=<service principal application ID>

databricks bundle deploy
databricks bundle run cost_review                                        # Claude Code
databricks bundle run cost_review --params harness=codex                 # Codex + open-source model
```

The schedule (Mondays 8am PT) is deployed **paused**. To turn it on, set `pause_status: UNPAUSED` in `databricks.yml` and redeploy.
The agent's answer appears in the run output. Every model and MCP call is logged to `system.ai_gateway.usage` with
`requester` set to the service principal. Rows can take a few hours to appear.

## Add a task

1. Write the prompt in `tasks/<name>.md`. Name the MCP tools it should use, and say not to use a shell.
2. Copy the `cost_review` job in `databricks.yml` and set its `task` default and schedule.
3. If the task needs new tools, add them to both agent configs (see below).

## Change the model or agent

- Claude Code model: `model` in `agents/claude/settings.json`. It can be any model service that supports the Anthropic Messages API, including supported open-source models.
- Codex model: `model` in `agents/codex/config.toml`.
- Default agent: the `harness` parameter default in `databricks.yml`.

Before switching a task to a cheaper model, run both on the same prompt and compare the answers with a direct query.
In testing, an open-source model occasionally got the totals right but named the wrong top line item.

## Add an MCP (for example Jira or Slack)

The agent's identity is the service principal, but in Jira and Slack the agent acts as whatever credential is stored in the MCP's
connection. Use a shared service account for that credential, not a person. The built-in `system.ai.atlassian` and
`system.ai.slack` services use per-user sign-in, so for a shared identity, register the vendor's MCP as an external MCP service.

### 1. Register it in Unity Gateway (needs admin rights in the workspace and in the vendor's tool)

**Jira (Atlassian Rovo MCP).** No custom app needed.
1. An Atlassian org admin creates a **service account** with access to the target project, then creates
   **OAuth 2.0 client credentials** for it with the `*:agent-interface` scopes the tasks need, plus `read:me` and `read:account`.
2. In Databricks: **Unity Gateway → MCPs → + MCP → Connect an existing MCP server**.
   URL: `https://mcp.atlassian.com/v2/mcp`. Authentication: **OAuth M2M**, using the client ID and secret.
3. Note the cloud ID of your Atlassian site; tools need it when authenticating this way.

**Slack (official Slack MCP).** Needs a Slack app.
1. A Slack admin creates an **internal Slack app**, enables **Slack MCP Server** under **Agents**, and adds the user scopes
   the tasks need (for example `chat:write`).
2. Create a dedicated Slack user for the agent (for example `finops-agent`). Slack's MCP accepts **user tokens only**, so
   messages appear as that user.
3. In Databricks, register `https://mcp.slack.com/mcp` with **OAuth U2M Shared** authentication, and sign in once as the agent user.

### 2. Grant the service principal access

In **Unity Gateway → MCPs → \<service\> → Permissions**, grant the service principal `EXECUTE`.
To give a team access instead, grant it to a group.

### 3. Add it to both agents

`agents/claude/mcp.json`:
```json
"jira": {
  "type": "http",
  "url": "${DATABRICKS_HOST}/ai-gateway/mcp-services/<catalog>.<schema>.<mcp name>",
  "headers": { "Authorization": "Bearer ${DATABRICKS_TOKEN}" }
}
```
`agents/claude/settings.json`: allow only the tools the task needs, for example `"mcp__jira__createJiraIssue"`.

`agents/codex/config.toml`:
```toml
[mcp_servers.jira]
url = "${DATABRICKS_HOST}/ai-gateway/mcp-services/<catalog>.<schema>.<mcp name>"
bearer_token_env_var = "DATABRICKS_TOKEN"
enabled_tools = ["createJiraIssue"]
default_tools_approval_mode = "approve"
```

Tool names come from the MCP's tool list: **Unity Gateway → MCPs → \<service\> → Tools**.

## Notes

- Both agents run unattended. Claude Code uses `--permission-mode dontAsk`, so anything not in the allowlist is denied.
  Codex runs with its shell disabled and only the listed MCP tools enabled.
- Codex blocks MCP calls when run headless unless `default_tools_approval_mode = "approve"` is set on the server.
- Open-source models sometimes reach for a shell instead of a tool. Naming the tool in the prompt and disabling the shell fixes that.
- Anchor date windows to the data (for example "the 7 days ending the day before the latest `usage_date`"), not to "yesterday".
  The warehouse clock is UTC and billing data lags, so agents interpret "yesterday" differently.
- The job uses serverless compute and downloads Node.js plus the pinned CLI from `nodejs.org` and npm at the start of each run.
  If your workspace blocks outbound internet, mirror them and change the URLs in `src/run_task.py`.
