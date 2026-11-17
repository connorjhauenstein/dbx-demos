"""Run a task headless with Claude Code or OpenCode, as the job's run-as identity, and record it as one MLflow trace.

Arguments: <bundle files root> <task> <harness> <model> <MLflow experiment name prefix> <job run ID>

The task folder holds prompt.md and task.yml, which lists the Unity Gateway MCP services the agent may use and the
task's cost tags. This script writes the harness's own config, with those MCPs allowed and the run's tags on every
gateway request, then runs it.
"""
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import mlflow
import yaml
from databricks.sdk import WorkspaceClient

NODE_VERSION = "24.22.0"
CLIS = {
    "claude": "@anthropic-ai/claude-code@2.1.323",
    "opencode": "opencode-ai@1.19.5",
}
TAGS_HEADER = "Databricks-Ai-Gateway-Request-Tags"


# Each harness function writes the harness's config and returns its command. Each events function turns one line of
# the harness's JSON output into events:
#   ("llm", call_id, usage, outputs, start_ns, end_ns)   a model call (times are None when the harness doesn't report them)
#   ("tool_start", call_id, name, inputs, start_ns)      ("tool_end", call_id, outputs, end_ns)
#   ("text", text)


def usage(input_tokens, output_tokens, cache_read=0, cache_write=0):
    """MLflow token usage. input_tokens includes cached input, which Claude and OpenCode report separately."""
    input_tokens += cache_read + cache_write
    return {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
        "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write,
    }


def claude(work, host, model, mcps, headers, env):
    env |= {
        "ANTHROPIC_BASE_URL": f"{host}/ai-gateway/anthropic",
        "ANTHROPIC_AUTH_TOKEN": env["DATABRICKS_TOKEN"],
        "ANTHROPIC_CUSTOM_HEADERS": "\n".join(f"{k}: {v}" for k, v in headers.items()),
    }
    servers = {
        name: {"type": "http", "url": url, "headers": {"Authorization": "Bearer ${DATABRICKS_TOKEN}", TAGS_HEADER: headers[TAGS_HEADER]}}
        for name, url in mcps.items()
    }
    allow = [f"mcp__{name}" for name in mcps]
    (work / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
    (work / "settings.json").write_text(json.dumps({"model": model, "permissions": {"allow": allow}}))
    return [
        "claude", "-p", "--bare", "--settings", "settings.json",
        "--mcp-config", "mcp.json", "--strict-mcp-config", "--permission-mode", "dontAsk",
        "--output-format", "stream-json", "--verbose",
    ]


def claude_events(e):
    content = e.get("message", {}).get("content", [])
    if e["type"] == "assistant":
        u = e["message"]["usage"]
        call_usage = usage(u["input_tokens"], u["output_tokens"], u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0))
        yield "llm", e["message"]["id"], call_usage, content, None, None
        for c in content:
            if c["type"] == "tool_use":
                yield "tool_start", c["id"], c["name"], c["input"], None
    elif e["type"] == "user":
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_result":
                yield "tool_end", c["tool_use_id"], c["content"], None
    elif e["type"] == "result":
        yield "text", e.get("result", "")


def opencode(work, host, model, mcps, headers, env):
    auth = {"Authorization": "Bearer {env:DATABRICKS_TOKEN}"}
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"unity-gateway/{model}",
        "provider": {
            "unity-gateway": {
                "npm": "@ai-sdk/anthropic",
                "options": {"baseURL": f"{host}/ai-gateway/anthropic/v1", "apiKey": "{env:DATABRICKS_TOKEN}", "headers": auth | headers},
                "models": {model: {"options": {"toolStreaming": False}}},
            }
        },
        "mcp": {
            "servers": {
                name: {"type": "remote", "url": url, "oauth": False, "headers": auth | {TAGS_HEADER: headers[TAGS_HEADER]}}
                for name, url in mcps.items()
            }
        },
        "permission": {"*": "deny"} | {f"{name}_*": "allow" for name in mcps},
    }
    (work / "opencode.json").write_text(json.dumps(config))
    env["OPENCODE_CONFIG"] = str(work / "opencode.json")
    return ["opencode", "run", "--format", "json"]


STEPS = {}  # OpenCode step start time, first tool start, and text, by message ID


def opencode_events(e):
    part, ms = e.get("part", {}), 1_000_000
    step = STEPS.setdefault(part.get("messageID"), {"start": e.get("timestamp", 0) * ms, "tool": None, "text": []})
    if e["type"] == "tool_use":
        state = part["state"]
        step["tool"] = step["tool"] or state["time"]["start"] * ms
        yield "tool_start", part["callID"], part["tool"], state.get("input"), state["time"]["start"] * ms
        yield "tool_end", part["callID"], state.get("output"), state["time"]["end"] * ms
    elif e["type"] == "text":
        step["text"].append(part["text"])
        yield "text", part["text"]
    elif e["type"] == "step_finish":
        tokens = part["tokens"]
        outputs = {"text": "".join(step["text"])} if step["text"] else {"finish_reason": part.get("reason")}
        call_usage = usage(tokens["input"], tokens["output"], tokens["cache"]["read"], tokens["cache"]["write"])
        yield "llm", part["messageID"], call_usage, outputs, step["start"], step["tool"] or e["timestamp"] * ms


HARNESSES = {"claude": (claude, claude_events), "opencode": (opencode, opencode_events)}


root, task, harness_name, model, experiments, job_run_id = sys.argv[1:7]
task_dir = Path(root) / "tasks" / task
config = yaml.safe_load((task_dir / "task.yml").read_text())
prompt = (task_dir / "prompt.md").read_text().strip()
tags = {"task": task, "harness": harness_name, "model": model, "job_run_id": job_run_id} | config.get("tags", {})

# The job's run-as identity (the service principal) authenticates every gateway call.
w = WorkspaceClient()
host = w.config.host.rstrip("/")
token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")
mcps = {name.split(".")[-1]: f"{host}/ai-gateway/mcp-services/{name}" for name in config.get("mcps", [])}

# Node.js and the agent CLI, installed into an empty scratch directory the agent runs in.
work = Path(tempfile.mkdtemp())
arch = {"x86_64": "x64", "aarch64": "arm64"}[platform.machine()]
node = f"node-v{NODE_VERSION}-linux-{arch}"
with urllib.request.urlopen(f"https://nodejs.org/dist/v{NODE_VERSION}/{node}.tar.xz") as r:
    with tarfile.open(fileobj=r, mode="r|xz") as tar:
        tar.extractall(work / ".node", filter="data")
env = {
    **os.environ,
    "PATH": f"{work / '.node' / node / 'bin'}:{os.environ['PATH']}",
    "HOME": str(work),
    "DATABRICKS_HOST": host,
    "DATABRICKS_TOKEN": token,
}
harness, events = HARNESSES[harness_name]
subprocess.run(["npm", "install", "-g", "--silent", CLIS[harness_name]], env=env, check=True)
cmd = harness(work, host, model, mcps, {TAGS_HEADER: json.dumps(tags)}, env)
print(f"Running {task} with {harness_name} and {model}, tags {tags}", flush=True)

# One trace per run: a root span for the task, a span per model call (with token usage), and a span per tool call.
# The session is the job run, so a compare_agents run groups its agents' traces.
os.environ["MLFLOW_TRACKING_URI"] = "databricks"
# The task's experiment (created by the bundle) and its Unity Catalog trace location; every run of the task lands here.
mlflow.set_experiment(experiment_id=mlflow.get_experiment_by_name(f"{experiments}{task}").experiment_id)
trace = mlflow.start_span_no_context(
    task, span_type="AGENT", inputs={"prompt": prompt}, tags=tags,
    metadata={"mlflow.trace.session": job_run_id, "mlflow.trace.user": w.current_user.me().user_name},
)
print(f"MLflow trace {trace.trace_id}", flush=True)
tools, text, ended = {}, [], set()
llm = None  # the model call being received: {"id", "span", "outputs", "usage", "end"}
cursor = time.time_ns()  # end of the previous step; a model call with no reported start time begins here


def end_llm():
    global llm, cursor
    if llm:
        attributes = {"mlflow.chat.tokenUsage": llm["usage"], "mlflow.llm.model": model}
        llm["span"].end(outputs=llm["outputs"], attributes=attributes, end_time_ns=llm["end"])
        ended.add(llm["id"])
        cursor, llm = llm["end"], None


proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, cwd=work, text=True)
proc.stdin.write(prompt)
proc.stdin.close()
for line in proc.stdout:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    for kind, *args in events(event):
        now = time.time_ns()
        if kind == "llm":
            call_id, call_usage, outputs, start, end = args
            if call_id in ended:  # a later event for a model call already recorded
                continue
            if not llm or llm["id"] != call_id:
                end_llm()
                span = mlflow.start_span_no_context("llm", span_type="CHAT_MODEL", parent_span=trace, start_time_ns=start or cursor)
                llm = {"id": call_id, "span": span, "outputs": []}
            llm["outputs"] += outputs if isinstance(outputs, list) else [outputs]
            llm["usage"], llm["end"] = call_usage, end or now
        elif kind == "tool_start":
            end_llm()
            call_id, name, inputs, start = args
            tools[call_id] = mlflow.start_span_no_context(name, span_type="TOOL", parent_span=trace, inputs=inputs, start_time_ns=start or now)
        elif kind == "tool_end" and args[0] in tools:
            call_id, outputs, end = args
            tools.pop(call_id).end(outputs=outputs, end_time_ns=end or now)
            cursor = end or now
        elif kind == "text":
            text.append(args[0])
end_llm()
proc.wait()

answer = text[-1] if text else ""
trace.end(outputs={"response": answer}, attributes={"exit_code": proc.returncode}, status="OK" if proc.returncode == 0 else "ERROR")
mlflow.flush_trace_async_logging()
print(answer)
if proc.returncode:
    sys.exit(f"{harness_name} exited with {proc.returncode}")
