"""Custom LangGraph agent on Databricks Apps: Lakebase memory, served with the Agent Bricks invocation API."""

import json
import logging
import os

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from agent import create_graph, run_turn

logging.basicConfig(level=logging.INFO)

SCHEMA = "agent_custom_langgraph"  # the app service principal can create schemas, but not write to public
_workspace = WorkspaceClient()


def _lakebase_kwargs() -> dict:
    """Fresh Lakebase OAuth token for each new connection (tokens expire after an hour)."""
    token = _workspace.postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"]).token
    return {"password": token, "autocommit": True, "options": f"-c search_path={SCHEMA}"}


# The Lakebase app resource injects PGHOST, PGPORT, PGDATABASE and PGUSER for the app's service principal.
pool = ConnectionPool(
    conninfo=(
        f"host={os.environ['PGHOST']} port={os.environ['PGPORT']} dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} sslmode=require"
    ),
    kwargs=_lakebase_kwargs,
    max_size=5,
    open=True,
)
with pool.connection() as conn:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
checkpointer = PostgresSaver(pool)
checkpointer.setup()
graph = create_graph(checkpointer)

app = FastAPI(title="Custom LangGraph Agent")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/invocations")
async def invocations(body: dict):
    """The Agent Bricks invocation API: {"session_id", "input": {"messages": [...]}, "stream"}."""
    session_id = body.get("session_id")
    messages = (body.get("input") or {}).get("messages") or []
    prompt = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), None)
    if not session_id or not prompt:
        raise HTTPException(400, "session_id and a user message are required")
    events = run_turn(graph, session_id, prompt)
    if body.get("stream"):

        async def sse():
            async for event in events:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
    output, failure = [], None
    async for event in events:
        if event["type"] == "message":
            output.append(event["message"])
        elif event["type"] == "run.failed":
            failure = event["error"]
    return {"output": output, "status": "failed" if failure else "completed", "error": failure}
