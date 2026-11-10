# Agent API

LangGraph agent served as a REST API via FastAPI. Deployed as a Databricks App.

## Setup

1. Copy `app.yaml.example` to `app.yaml`
2. Update the following values:

| Variable | Description | Where to find it |
|----------|-------------|-------------------|
| `DATABRICKS_WAREHOUSE_ID` | SQL warehouse for tool queries | Workspace → SQL Warehouses → your warehouse → ID in URL |
| `MODEL_NAME` | Foundation Model API endpoint | Default: `databricks-meta-llama-3-3-70b-instruct` |
| `MLFLOW_EXPERIMENT_NAME` | MLflow experiment for traces | Create one per the workshop guide (Step 3) |
| `LAKEBASE_CONN_STR` | Lakebase connection string | Stored as a secret — see workshop guide (Step 2) |
| `MLFLOW_PROMPT_NAME` | Prompt Registry name for the system prompt | Default: `agent-workshop-system-prompt` (registered from `system_prompt.md` if absent) |
| `MLFLOW_TRACE_STORAGE` | `volume` (default) or `uc_tables` (preview) | Set `uc_tables` to write traces to UC Delta tables |
| `MLFLOW_UC_CATALOG` / `MLFLOW_UC_SCHEMA` / `MLFLOW_UC_TABLE_PREFIX` | Destination for UC-table traces | Only with `MLFLOW_TRACE_STORAGE=uc_tables` |

## Files

| File | Purpose |
|------|---------|
| `agent.py` | LangGraph agent — `create_agent()` with LLM, tools, and checkpointer |
| `tools.py` | SQL query tool for Unity Catalog |
| `system_prompt.md` | Agent's system prompt — edit this to change behavior |
| `main.py` | FastAPI server — `/chat`, `/chat/stream`, `/history`, `/threads` |
| `index.html` | API docs page with interactive "Try it" buttons |
| `requirements.txt` | Python dependencies |
| `app.yaml.example` | Template for app configuration |

## Deploy

```bash
cp app.yaml.example app.yaml
# Edit app.yaml with your values

databricks workspace import-dir . /Workspace/Users/<YOU>/agent-workshop-api --overwrite
databricks apps deploy agent-workshop-api \
  --source-code-path /Workspace/Users/<YOU>/agent-workshop-api
```
