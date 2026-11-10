# Agent Workshop

An AI agent with conversation memory, tool use, token streaming, and MLflow tracing — deployed as two Databricks Apps.

## Architecture

```
Frontend App (Chat UI)  →  Agent API App (LangGraph + MLflow)  →  Lakebase (Memory)
                                       ↓
                              MLflow Experiment (Traces in UC Volume)
```

## Project Structure

```
agent-api/              # Agent REST API (Databricks App)
├── agent.py            # LangGraph agent using create_agent()
├── tools.py            # SQL query tool for Unity Catalog
├── system_prompt.md    # Editable system prompt
├── main.py             # FastAPI server
├── index.html          # API docs page
├── app.yaml            # App configuration
└── requirements.txt

frontend/               # Chat UI (Databricks App)
├── main.py             # Static file server
├── static/
│   ├── index.html      # Chat UI structure
│   ├── styles.css      # Styles
│   └── app.js          # Streaming, tool blocks, markdown, threads
├── app.yaml
└── requirements.txt

notebooks/              # Development & observability
├── run_agent.py        # Run agent with full MLflow trace visibility
└── workshop_guide.py   # Step-by-step setup walkthrough
```

## Quick Start

See `notebooks/workshop_guide.py` for the full setup walkthrough, or:

1. **Set up Lakebase** — create a project, generate native Postgres credentials for the app's SP
2. **Set up MLflow** — create a UC Volume + experiment with `artifact_location="dbfs:/Volumes/..."`
3. **Deploy agent-api** — update `app.yaml` with your warehouse ID, deploy as a Databricks App
4. **Deploy frontend** — update `app.yaml` with the agent-api URL, deploy as a Databricks App

## Features

- **Token streaming** — responses appear word-by-word via Server-Sent Events
- **Tool calls** — expandable blocks showing SQL queries and results (Cursor-style)
- **Conversation memory** — persisted to Lakebase (PostgreSQL) via LangGraph checkpointer
- **MLflow tracing** — full span trees viewable in the Experiments UI
- **Markdown rendering** — inline code, code blocks, lists, bold/italic
- **Thread management** — rename, delete, ordered by recent activity
