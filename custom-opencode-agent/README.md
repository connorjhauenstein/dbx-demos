# Custom agent on OpenCode

An interactive chat agent whose brain is the open-source [OpenCode](https://opencode.ai) harness. There is no agent code: you configure it with a system prompt (`agent/prompt.md`) and a small config (`agent/agent.yml`: model and MCP services), and the app turns that into OpenCode's config and serves it as a Databricks App.

The demo agent is a FinOps assistant. It answers cost questions over `system.billing.usage` using the Unity Catalog `system.ai.dbsql` MCP service.

Point: use an open-source harness for an agent you configure with a prompt, a model, and MCPs, instead of writing agent code.

## Layout

```text
agent/prompt.md          system prompt (the agent's instructions)
agent/agent.yml          model and Unity Gateway MCP services
server.py                Agent Bricks invocation API over `opencode run`, one MLflow trace per turn
requirements.txt         Python dependencies, including Node.js (nodejs-wheel-binaries)
resources/app.yml        the app, its MLflow experiment with a UC trace location, and the app's command and env
databricks.yml           bundle: name, variables (trace catalog and schema), dev target
```

## How config maps to OpenCode

At startup `server.py` writes `opencode.json` from `agent/agent.yml` and `agent/prompt.md`:

| Config | OpenCode config |
|---|---|
| `model: system.ai.claude-sonnet-5-5` | `model: unity-gateway/system.ai.claude-sonnet-5-5`, with a provider `unity-gateway` (`@ai-sdk/anthropic`, base URL `<host>/ai-gateway/anthropic/v1`, `toolStreaming: false`) |
| `prompt.md` | `agent.build.prompt`, the prompt of the agent that `opencode run` uses by default |
| `mcps: [system.ai.dbsql]` | a remote MCP server named `dbsql` at `<host>/ai-gateway/mcp-services/system.ai.dbsql`; its tools are `dbsql_*` |
| (always) | `permission: {"*": "deny", "dbsql_*": "allow"}`, so OpenCode's built-in file and shell tools are off |

Each MCP service's tools are named by its last segment (`system.ai.dbsql` becomes `dbsql`), because tool names can't contain dots.

## How a turn works

Each turn runs `opencode run --format json` with the prompt on stdin. The first turn of a session creates an OpenCode session. Later turns pass `--session <id>`, so OpenCode resumes the conversation from its history on local disk. The server maps Agent Bricks `session_id` to the OpenCode session ID in memory.

The token is set per turn. The OpenCode config reads `DATABRICKS_TOKEN` from the environment, and each turn sets it to the caller's token. The caller's token is the `x-forwarded-access-token` header that Databricks Apps forwards when the app has user authorization scopes. Without that header the app's service principal is used. This is why the server runs `opencode run` per turn instead of one long-lived `opencode serve`: a server would hold one fixed token for every user.

Each turn writes one MLflow trace to the `/Shared/agents/custom-opencode` experiment, stored in UC tables `<catalog>.agent_traces.custom_opencode_agent_*`. The trace has an `agent_turn` root span with `mlflow.trace.session` set to the session ID, a `model_call` span per model step (with token usage), and a span per tool call.

Node and npm come from the `nodejs-wheel-binaries` pip package, and OpenCode (`opencode-ai@1.19.5`) is installed with npm when the app starts. This needs outbound access to the npm registry, which the Apps runtime has.

## Calling the agent

Endpoint: `POST /api/invocations`, the same shape as Agent Bricks agents.

```bash
APP=https://<app-url>
TOKEN=$(databricks auth token -p <profile> | jq -r .access_token)
SESSION=$(uuidgen)

# Streamed: SSE lines of `data: {json}`. Events: delta (text chunk), message (completed assistant text,
# tool call, or tool result), run.failed.
curl -sN $APP/api/invocations -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"id\":\"$(uuidgen)\",\"session_id\":\"$SESSION\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"What did we spend on usage in the last 7 days?\"}]},\"stream\":true}"

# Same session, next turn: the agent remembers the earlier one.
curl -sN $APP/api/invocations -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"id\":\"$(uuidgen)\",\"session_id\":\"$SESSION\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"Break that down by SKU.\"}]},\"stream\":true}"
```

Without `"stream": true` the response is `{"output": [message items], "status": "completed"}`. Only the last user message in `input.messages` is sent to the agent. `id` is accepted but not used for idempotency. `GET /health` returns `{"status": "ok"}`.

## Deploy

Pick a catalog and schema for the MLflow trace tables. The bundle has no workspace-specific values.

```bash
databricks bundle deploy -t dev -p <profile> \
  --var trace_catalog=<catalog> --var trace_schema=<schema>
databricks bundle run custom_opencode_agent -p <profile> \
  --var trace_catalog=<catalog> --var trace_schema=<schema>
```

After the first deploy, grant the app's service principal (its client ID is shown by `databricks apps get agent-custom-opencode`) `USE CATALOG` on the trace catalog and `USE SCHEMA`, `SELECT`, `MODIFY`, and `CREATE TABLE` on the trace schema. Without these, the agent still answers but the traces are not saved. The app also needs the `workspace-access` and `databricks-sql-access` entitlements.

To change the agent, edit `agent/prompt.md` or `agent/agent.yml` and run `bundle deploy` and `bundle run` again.

## Limitations

- **Session state is on the app's local disk** under a temp directory, and it is lost on restart or redeploy. The server's session map is also in memory. Conversations then start fresh.
- **Text arrives per model step, not per token.** `opencode run --format json` emits completed text parts, so each `delta` is a whole text part. Token-level streaming would need `opencode serve`, which has a fixed token per process and so cannot forward each user's token.
- **Concurrent turns in one session are not serialized.** Two requests in the same session at once would race on the same OpenCode session.
- **Idempotency is not implemented.** A retried request with the same `id` runs again.
- **Timeouts.** A turn that runs past the Apps request limit (about 120 s) is cut off. Streaming keeps bytes flowing, so long answers survive.
- **User authorization is required for per-user identity.** Model and MCP calls run as the signed-in user only when the app has the `sql` and `ai-gateway` user scopes. The `ai-gateway` scope is required: without it the forwarded token gets `Forbidden: Invalid scope, required scopes: ai-gateway`. The service-principal fallback is not exercised by this demo (Apps always forward the header for signed-in callers), so it is untested.
- **This is a custom integration.** It is not a Databricks-supported path for OpenCode or for custom agents on Agent Bricks.
