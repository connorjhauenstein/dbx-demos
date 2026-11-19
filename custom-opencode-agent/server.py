"""Agent Bricks invocation API over OpenCode. Each turn runs `opencode run` with the agent's config; one MLflow trace per turn.

OpenCode keeps conversation history per session on local disk, so a turn after the first resumes the OpenCode session
that the first turn created. The model and MCP calls use the signed-in user's token when the request carries one.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import mlflow
import nodejs_wheel
import yaml
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

OPENCODE_VERSION = "1.19.5"
ROOT = Path(__file__).parent
AGENT = yaml.safe_load((ROOT / "agent" / "agent.yml").read_text())
PROMPT = (ROOT / "agent" / "prompt.md").read_text().strip()
MODEL = AGENT["model"]
MCP_SERVICES = AGENT.get("mcps", [])

workspace = WorkspaceClient()
HOST = workspace.config.host.rstrip("/")
HOME = Path(tempfile.mkdtemp(prefix="opencode-"))  # OpenCode's install, config, and sessions. Lost on restart.
CONFIG = HOME / "opencode.json"
OPENCODE = HOME / "node_modules" / ".bin" / "opencode"
SESSIONS = {}  # Agent Bricks session_id -> OpenCode session ID

# OpenCode is an npm package. Node and npm come from the nodejs-wheel-binaries package, so the app needs no system Node.
os.environ["PATH"] = f"{Path(nodejs_wheel.__file__).parent / 'bin'}{os.pathsep}{os.environ['PATH']}"
os.environ["npm_config_cache"] = str(HOME / ".npm")
if nodejs_wheel.npm(["install", "--prefix", str(HOME), f"opencode-ai@{OPENCODE_VERSION}"]):
    raise SystemExit("npm install of opencode-ai failed")

# The provider and MCP servers read the token from the environment, which each turn sets to the caller's token.
# OpenCode's config is built once from agent.yml; only the token varies per turn.
AUTH = {"Authorization": "Bearer {env:DATABRICKS_TOKEN}"}
CONFIG.write_text(json.dumps({
    "$schema": "https://opencode.ai/config.json",
    "model": f"unity-gateway/{MODEL}",
    "provider": {
        "unity-gateway": {
            "npm": "@ai-sdk/anthropic",
            "options": {"baseURL": f"{HOST}/ai-gateway/anthropic/v1", "apiKey": "{env:DATABRICKS_TOKEN}", "headers": AUTH},
            "models": {MODEL: {"options": {"toolStreaming": False}}},
        }
    },
    "agent": {"build": {"prompt": PROMPT}},
    "mcp": {
        service.split(".")[-1]: {"type": "remote", "url": f"{HOST}/ai-gateway/mcp-services/{service}", "oauth": False, "headers": AUTH}
        for service in MCP_SERVICES
    },
    "permission": {"*": "deny"} | {f"{service.split('.')[-1]}_*": "allow" for service in MCP_SERVICES},
}, indent=2))

mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])
MS = 1_000_000  # OpenCode timestamps are milliseconds; MLflow takes nanoseconds


def usage(input_tokens, output_tokens, cache_read, cache_write):
    """MLflow token usage. OpenCode reports cached input separately from input tokens."""
    input_tokens += cache_read + cache_write
    return {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
        "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write,
    }


def turn(session_id, prompt, token):
    """Run one turn. Yields Agent Bricks events and records the turn as one MLflow trace."""
    trace = mlflow.start_span_no_context(
        "agent_turn", span_type="AGENT", inputs={"prompt": prompt}, metadata={"mlflow.trace.session": session_id}
    )
    status, answer, step, proc, failure = "OK", "", None, None, None
    cmd = [str(OPENCODE), "run", "--format", "json"]
    if session_id in SESSIONS:
        cmd += ["--session", SESSIONS[session_id]]
    env = os.environ | {"HOME": str(HOME), "OPENCODE_CONFIG": str(CONFIG), "DATABRICKS_HOST": HOST, "DATABRICKS_TOKEN": token}
    yield {"type": "run.started"}
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, cwd=HOME, text=True)
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "sessionID" in event:
                SESSIONS.setdefault(session_id, event["sessionID"])
            part = event.get("part", {})
            if event["type"] == "step_start":
                step = {"start": event["timestamp"] * MS, "text": []}
            elif event["type"] == "text":
                answer = part["text"]
                step["text"].append(answer)
                yield {"type": "delta", "content": answer}
                yield {"type": "message", "message": {"role": "assistant", "content": answer}}
            elif event["type"] == "tool_use":
                state, call_id, name = part["state"], part["callID"], part["tool"]
                done = state["status"] == "completed"
                output = state.get("output") if done else state.get("error")
                output = output if isinstance(output, str) else json.dumps(output)
                yield {"type": "message", "message": {"role": "assistant", "tool_calls": [{"id": call_id, "name": name, "args": state.get("input", {})}]}}
                yield {"type": "message", "message": {"role": "tool", "tool_call_id": call_id, "name": name, "content": output}}
                times = state.get("time", {})
                span = mlflow.start_span_no_context(
                    name, span_type="TOOL", parent_span=trace, inputs=state.get("input", {}),
                    start_time_ns=times.get("start", event["timestamp"]) * MS,
                )
                span.end(outputs=output, end_time_ns=times.get("end", event["timestamp"]) * MS, status="OK" if done else "ERROR")
            elif event["type"] == "step_finish":
                tokens = part["tokens"]
                span = mlflow.start_span_no_context("model_call", span_type="CHAT_MODEL", parent_span=trace, start_time_ns=step["start"])
                span.end(
                    outputs={"text": "".join(step["text"]), "finish_reason": part.get("reason")},
                    attributes={
                        "mlflow.chat.tokenUsage": usage(tokens["input"], tokens["output"], tokens["cache"]["read"], tokens["cache"]["write"]),
                        "mlflow.llm.model": MODEL,
                    },
                    end_time_ns=event["timestamp"] * MS,
                )
            elif event["type"] == "error":
                problem = event.get("error", {})
                failure = problem.get("data", {}).get("message") or problem.get("name", "unknown error")
        proc.wait()
        failure = failure or (f"opencode exited with code {proc.returncode}" if proc.returncode else None)
        if failure:
            raise RuntimeError(failure)
        yield {"type": "run.completed"}
    except Exception as error:
        status = "ERROR"
        yield {"type": "run.failed", "error": str(error)}
    finally:
        if proc and proc.poll() is None:  # the client went away mid-turn
            proc.kill()
        trace.end(outputs={"response": answer}, status=status)
        mlflow.flush_trace_async_logging()


app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/invocations")
def invocations(body: dict, x_forwarded_access_token: str | None = Header(default=None)):
    session_id = body.get("session_id")
    messages = (body.get("input") or {}).get("messages") or []
    prompt = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), None)
    if not session_id or not prompt:
        raise HTTPException(400, "session_id and a user message are required")
    # Databricks Apps forward the signed-in user's token when the app has user authorization scopes.
    token = x_forwarded_access_token or workspace.config.authenticate()["Authorization"].removeprefix("Bearer ")
    events = turn(session_id, prompt, token)
    if body.get("stream"):
        return StreamingResponse((f"data: {json.dumps(event)}\n\n" for event in events), media_type="text/event-stream")
    output, failure = [], None
    for event in events:
        if event["type"] == "message":
            output.append(event["message"])
        elif event["type"] == "run.failed":
            failure = event["error"]
    return {"output": output, "status": "failed" if failure else "completed", "error": failure}
