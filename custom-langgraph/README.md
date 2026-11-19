# Custom LangGraph agent

Build your own agent outside Agent Bricks when you need full control of the loop, the server, memory, and tracing. This demo is a LangGraph agent served by FastAPI as a Databricks App. You own the code, the checkpointer, and the HTTP API.

It shows:

- **Model through Unity AI Gateway.** `ChatDatabricks(use_ai_gateway=True)` calls `system.ai.claude-sonnet-5-5` by default.
- **A tool you write in code.** `tools.py` is a SQL tool over Unity Catalog. The system prompt makes the agent a FinOps assistant over `system.billing`.
- **Memory you own.** A LangGraph checkpointer stores each conversation (session ID) in Lakebase (Postgres).
- **Traces in MLflow and Unity Catalog.** Every turn is a trace in the `/Shared/agents/custom-langgraph` experiment, stored in UC tables `<catalog>.agent_traces.custom_langgraph_*`.
- **The standard agent API.** It serves the Agent Bricks invocation API (`POST /api/invocations`), so the agent playground and any other Agent Bricks client can call it, even though it isn't built with Agent Bricks.

## Layout

```
databricks.yml      # One bundle: Lakebase project, MLflow experiment, app
agent.py            # create_agent() with the gateway model, tool, and checkpointer; run_turn() emits invocation events
tools.py            # query_databricks_sql: the in-code SQL tool
system_prompt.md    # Agent instructions (FinOps over system.billing)
main.py             # FastAPI: /api/invocations, /health
requirements.txt
```

## Prerequisites

- Databricks CLI with bundle support (tested with v1.26), authenticated to the target workspace (`databricks auth login`).
- A SQL warehouse. Its ID is the `warehouse_id` variable.
- A Unity Catalog catalog and an existing schema for traces (default `agent_traces`). The `catalog` variable is the catalog name.
- Access to `system.billing` for the app's service principal, for the FinOps questions.

## Deploy

```bash
databricks bundle deploy -p <profile> \
  --var catalog=<catalog> --var warehouse_id=<warehouse-id>
databricks bundle run custom_langgraph -p <profile> \
  --var catalog=<catalog> --var warehouse_id=<warehouse-id>
```

After the first deploy, grant the app's service principal access to the trace schema. Without this, the app runs but traces are not saved. Get the principal's client ID from the app, then run in a SQL editor or with `databricks api`:

```sql
GRANT USE CATALOG ON CATALOG <catalog> TO `<app-service-principal-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.agent_traces TO `<app-service-principal-client-id>`;
GRANT SELECT, MODIFY ON SCHEMA <catalog>.agent_traces TO `<app-service-principal-client-id>`;
```

Get the client ID with `databricks apps get agent-custom-langgraph -p <profile> -o json`, field `service_principal_client_id`.

The bundle creates the Lakebase project and the app's Postgres resource. The app creates its own schema (`agent_custom_langgraph`) for LangGraph checkpoints, so no admin grant is needed on `public`.

## Call it

The app URL is in `databricks apps get agent-custom-langgraph -p <profile>` (field `url`). Calls use a Databricks token:

```bash
TOKEN=$(databricks auth token -p <profile> -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
APP=<app-url>

# Stream one turn. SSE events: run.started, delta (text), message (assistant text, tool calls,
# tool results), run.completed or run.failed. Reuse the session_id to continue the conversation.
curl -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"'"$(uuidgen)"'","session_id":"demo-1","input":{"messages":[{"role":"user","content":"What did we spend in the last 7 days?"}]},"stream":true}' \
  $APP/api/invocations
```

Traces appear in the UC trace tables `<catalog>.agent_traces.custom_langgraph_*`, tagged with the session ID.

## Change the agent

- Edit `system_prompt.md` to change behavior. Redeploy with `bundle deploy`, then `bundle run`.
- Add tools in `tools.py` and append them to `TOOLS`.
- Change the model with the `model` variable (`--var model=<model>`). The agent sets Claude's thinking mode to `between_tools` in `agent.py`, so use a Claude model or remove that setting.
