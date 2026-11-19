"""Agent Playground: a Databricks App that chats with deployed agents.

The browser only talks to this app. Every call to an agent is made here, with the
signed-in user's token (the x-forwarded-access-token header Databricks Apps adds when
user authorization is enabled), so agents see the real user.

Every agent speaks the Agent Bricks invocation API (POST /api/invocations). Agents come from:
- Databricks Apps named agent-* (discovered with the user's token, so users only see apps
  they can access). Unity Gateway lists the same apps on its Agents tab.
- Entries in agents.yml and agents.local.yml.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).parent
DATABRICKS_HOST = "https://" + os.environ.get("DATABRICKS_HOST", "").removeprefix("https://")
DISCOVERY_PREFIX = "agent-"  # the apps Unity Gateway lists as agents

app = FastAPI(title="Agent Playground")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


def user_token(request: Request) -> str:
    token = request.headers.get("x-forwarded-access-token")
    if not token:
        raise HTTPException(
            401,
            "No forwarded user token. Run as a Databricks App with user authorization "
            "enabled (scopes: apps, sql, ai-gateway).",
        )
    return token


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def text_of(content) -> str:
    """Plain text of a message's content; skips reasoning and other non-text parts."""
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text"
    )


def manual_agents() -> list[dict]:
    """Agents from agents.yml, plus agents.local.yml (gitignored, for workspace-specific URLs)."""
    agents = []
    for name in ("agents.yml", "agents.local.yml"):
        path = HERE / name
        if path.exists():
            agents += (yaml.safe_load(path.read_text()) or {}).get("agents") or []
    return agents


def manual_agent(entry: dict) -> dict:
    return {
        "id": entry["name"],
        "name": entry["name"],
        "source": "agents.yml",
        "url": entry["url"].rstrip("/"),
        "description": entry.get("description", ""),
        "available": True,
        "unavailable_reason": "",
    }


def traces_url(app_item: dict | None) -> str:
    """Link to the Traces tab of the MLflow experiment the agent's app declares as a resource."""
    for resource in (app_item or {}).get("resources", []):
        if experiment_id := resource.get("experiment", {}).get("experiment_id"):
            return f"{DATABRICKS_HOST}/ml/experiments/{experiment_id}?compareRunsMode=TRACES"
    return ""


def app_agent(item: dict) -> dict:
    return {
        "id": item["name"],
        "name": item["name"],
        "source": "agentbricks" if item["name"].startswith("agent-bricks-") else "app",
        "url": item["url"].rstrip("/"),
        "description": item.get("description", ""),
        "available": item.get("compute_status", {}).get("state") == "ACTIVE",
        "unavailable_reason": "" if item.get("compute_status", {}).get("state") == "ACTIVE" else "not running",
        "traces_url": traces_url(item),
    }


async def list_apps(client: httpx.AsyncClient, token: str) -> list[dict]:
    """Every app the signed-in user can see."""
    apps, params = [], {}
    while True:
        r = await client.get(f"{DATABRICKS_HOST}/api/2.0/apps", headers=auth_headers(token), params=params)
        if r.status_code != 200:
            raise HTTPException(r.status_code, f"Could not list apps as the signed-in user: {r.text[:200]}")
        body = r.json()
        apps += body.get("apps", [])
        if not body.get("next_page_token"):
            return apps
        params = {"page_token": body["next_page_token"]}


async def check_served(agent: dict, client: httpx.AsyncClient, token: str) -> dict:
    """Mark an agent unavailable if it doesn't serve the invocation API.

    An empty request makes no model call: an agent rejects it as a bad request, while an app without the
    route returns 404 or 405. check_agent.py is the full conformance check.
    """
    if not agent["available"]:
        return agent
    try:
        r = await client.post(f"{agent['url']}/api/invocations", json={}, headers=auth_headers(token), timeout=15)
    except httpx.HTTPError:
        return agent | {"available": False, "unavailable_reason": "not reachable"}
    if r.status_code in (404, 405):
        return agent | {"available": False, "unavailable_reason": "doesn't serve /api/invocations"}
    return agent


async def resolve_agent(agent_id: str, client: httpx.AsyncClient, token: str) -> dict:
    for entry in manual_agents():
        if entry["name"] == agent_id:
            return manual_agent(entry)
    if agent_id.startswith(DISCOVERY_PREFIX):
        # Looked up with the user's token, so this fails for apps the user cannot access.
        r = await client.get(f"{DATABRICKS_HOST}/api/2.0/apps/{agent_id}", headers=auth_headers(token))
        if r.status_code == 200:
            return app_agent(r.json())
    raise HTTPException(404, f"Agent {agent_id} not found or not accessible")


def public(agent: dict) -> dict:
    return {k: v for k, v in agent.items() if k != "url"}


async def stream_agentbricks(url: str, payload: dict, token: str):
    """Call an Agent Bricks invocation and re-emit its events in the playground's event shape."""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{url}/api/invocations", json=payload, headers=auth_headers(token)) as r:
            if r.status_code != 200:
                detail = (await r.aread()).decode()[:300]
                yield sse({"event": "error", "detail": f"Agent returned {r.status_code}: {detail}"})
                return
            final = ""
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                kind = event.get("type")
                if kind == "delta":
                    yield sse({"event": "token", "content": event["content"]})
                elif kind == "message":
                    msg = event["message"]
                    role = msg.get("type") or msg.get("role")
                    if role in ("ai", "assistant"):
                        for call in msg.get("tool_calls") or []:
                            yield sse({"event": "tool_call", "id": call["id"], "name": call["name"], "args": call.get("args", {})})
                        if not msg.get("tool_calls") and text_of(msg.get("content")):
                            final = text_of(msg.get("content"))
                    elif role == "tool":
                        yield sse({"event": "tools", "tool_call_id": msg.get("tool_call_id"), "output": text_of(msg.get("content"))})
                elif kind == "interrupt":
                    yield sse({"event": "interrupt", "requests": (event.get("value") or {}).get("action_requests", [])})
                    return
                elif kind == "run.failed":
                    yield sse({"event": "error", "detail": str(event.get("error") or "Agent run failed")})
                    return
                elif kind == "run.completed":
                    yield sse({"event": "done", "content": final})
                    return


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/agents")
async def list_agents(request: Request):
    token = user_token(request)
    async with httpx.AsyncClient(timeout=30) as client:
        apps = await list_apps(client, token)
        discovered = [app_agent(a) for a in apps if a["name"].startswith(DISCOVERY_PREFIX)]
        # Agents outside the agent-* naming are apps too; find each one's app by URL to link its traces.
        apps_by_url = {a.get("url", "").rstrip("/"): a for a in apps}
        manual = [
            manual_agent(entry) | {"traces_url": traces_url(apps_by_url.get(entry["url"].rstrip("/")))}
            for entry in manual_agents()
        ]
        agents = await asyncio.gather(*(check_served(a, client, token) for a in discovered + manual))
    return {
        "me": request.headers.get("x-forwarded-email", ""),
        "agents": [public(a) for a in agents],
    }


@app.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, request: Request):
    """One turn, or a resume after an approval interrupt, using the Agent Bricks invocation API."""
    token = user_token(request)
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        agent = await resolve_agent(agent_id, client, token)
    if "resume" in body:
        agent_input = {"resume": body["resume"]}
    else:
        agent_input = {"messages": [{"role": "user", "content": body["message"]}]}
    agent_input["actor"] = request.headers.get("x-forwarded-email", "")
    payload = {"id": str(uuid.uuid4()), "session_id": body["session_id"], "input": agent_input, "stream": True}
    return StreamingResponse(stream_agentbricks(agent["url"], payload, token), media_type="text/event-stream")
