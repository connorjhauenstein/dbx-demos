"""Run a task with an agent, headless, as the job's run-as identity, and record it as one MLflow trace.

Arguments: <bundle files root> <task> <agent> <platform schema> <MLflow experiment ID> <job run ID>

The task (tasks/<task>.md) names the Unity Gateway MCP services and skills it needs, the tools it may call, and its
cost tags. The agent (agents/<agent>.yml) names a harness and model. This script writes that harness's own config,
with only the task's tools allowed and the run's tags on every gateway request, then runs it.
Names without a catalog resolve to the platform schema.
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
    "codex": "@openai/codex@0.163.0",
    "opencode": "opencode-ai@1.19.5",
}
TAGS_HEADER = "Databricks-Ai-Gateway-Request-Tags"


# Each harness function writes the harness's config and returns its command. Each events function turns one line of
# the harness's JSON output into ("tool_start", id, name, input), ("tool_end", id, output), ("text", text), or
# ("tokens", input, output) events.


def claude(work, host, model, mcps, headers, env):
    env |= {
        "ANTHROPIC_BASE_URL": f"{host}/ai-gateway/anthropic",
        "ANTHROPIC_AUTH_TOKEN": env["DATABRICKS_TOKEN"],
        "ANTHROPIC_CUSTOM_HEADERS": "\n".join(f"{k}: {v}" for k, v in headers.items()),
    }
    servers = {
        name: {"type": "http", "url": m["url"], "headers": {"Authorization": "Bearer ${DATABRICKS_TOKEN}", TAGS_HEADER: headers[TAGS_HEADER]}}
        for name, m in mcps.items()
    }
    allow = [f"mcp__{name}__{tool}" for name, m in mcps.items() for tool in m["tools"]]
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
        for c in content:
            if c["type"] == "tool_use":
                yield "tool_start", c["id"], c["name"], c["input"]
    elif e["type"] == "user":
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_result":
                yield "tool_end", c["tool_use_id"], c["content"]
    elif e["type"] == "result":
        yield "text", e.get("result", "")
        yield "tokens", e["usage"]["input_tokens"], e["usage"]["output_tokens"]


def codex(work, host, model, mcps, headers, env):
    http_headers = "http_headers = { " + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in headers.items()) + " }"
    lines = [
        f"model = {json.dumps(model)}",
        'model_provider = "databricks"',
        "[model_providers.databricks]",
        'name = "Databricks"',
        f'base_url = "{host}/ai-gateway/codex/v1"',
        'wire_api = "responses"',
        "requires_openai_auth = false",
        "supports_websockets = false",
        'env_key = "DATABRICKS_TOKEN"',
        http_headers,
    ]
    for name, m in mcps.items():
        lines += [
            f"[mcp_servers.{name}]",
            f"url = {json.dumps(m['url'])}",
            'bearer_token_env_var = "DATABRICKS_TOKEN"',
            f"http_headers = {{ {json.dumps(TAGS_HEADER)} = {json.dumps(headers[TAGS_HEADER])} }}",
            f"enabled_tools = {json.dumps(m['tools'])}",
            'default_tools_approval_mode = "approve"',
        ]
    (work / ".codex").mkdir()
    (work / ".codex" / "config.toml").write_text("\n".join(lines) + "\n")
    env["CODEX_HOME"] = str(work / ".codex")
    return ["codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--disable", "shell_tool", "-"]


def codex_events(e):
    item = e.get("item", {})
    if item.get("type") == "mcp_tool_call":
        if e["type"] == "item.started":
            yield "tool_start", item["id"], f"{item['server']}.{item['tool']}", item["arguments"]
        elif e["type"] == "item.completed":
            yield "tool_end", item["id"], item.get("result") or item.get("error")
    elif item.get("type") == "agent_message" and e["type"] == "item.completed":
        yield "text", item["text"]
    elif e["type"] == "turn.completed":
        yield "tokens", e["usage"]["input_tokens"], e["usage"]["output_tokens"]


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
                name: {"type": "remote", "url": m["url"], "oauth": False, "headers": auth | {TAGS_HEADER: headers[TAGS_HEADER]}}
                for name, m in mcps.items()
            }
        },
        "permission": {"*": "deny"} | {f"{name}_{tool}": "allow" for name, m in mcps.items() for tool in m["tools"]},
    }
    (work / "opencode.json").write_text(json.dumps(config))
    env["OPENCODE_CONFIG"] = str(work / "opencode.json")
    return ["opencode", "run", "--format", "json"]


def opencode_events(e):
    part = e.get("part", {})
    if e["type"] == "tool_use":
        state = part["state"]
        yield "tool_start", part["callID"], part["tool"], state.get("input"), state["time"]["start"] * 1_000_000
        yield "tool_end", part["callID"], state.get("output"), state["time"]["end"] * 1_000_000
    elif e["type"] == "text":
        yield "text", part["text"]
    elif e["type"] == "step_finish":
        yield "tokens", part["tokens"]["input"], part["tokens"]["output"]


HARNESSES = {"claude": (claude, claude_events), "codex": (codex, codex_events), "opencode": (opencode, opencode_events)}


def uc_name(name):
    """Names without a catalog resolve to the platform schema."""
    return name if "." in name else f"{platform_schema}.{name}"


root, task, agent_name, platform_schema, experiment_id, job_run_id = sys.argv[1:7]
root = Path(root)
_, meta, prompt = (root / "tasks" / f"{task}.md").read_text().split("---", 2)
meta = yaml.safe_load(meta)
agent = yaml.safe_load((root / "agents" / f"{agent_name}.yml").read_text())
tags = {"task": task, "agent": agent_name, "model": agent["model"], "job_run_id": job_run_id} | meta.get("tags", {})

# The job's run-as identity (the service principal) authenticates every gateway call.
w = WorkspaceClient()
host = w.config.host.rstrip("/")
token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")

mcps = {
    uc_name(name).split(".")[-1]: {"url": f"{host}/ai-gateway/mcp-services/{uc_name(name)}", "tools": tools}
    for name, tools in meta.get("mcps", {}).items()
}
skills = [uc_name(name) for name in meta.get("skills", [])]
prompt = prompt.strip()
if skills:
    schemas = "&".join(f"schema={s}" for s in sorted({s.rsplit(".", 1)[0] for s in skills}))
    mcps["skills"] = {"url": f"{host}/ai-gateway/skills/?{schemas}", "tools": ["load_skill", "get_skill_files"]}
    prompt = f"First load these skills with the `skills` MCP tool `load_skill`: {', '.join(skills)}.\n\n{prompt}"

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
harness, events = HARNESSES[agent["harness"]]
subprocess.run(["npm", "install", "-g", "--silent", CLIS[agent["harness"]]], env=env, check=True)
cmd = harness(work, host, agent["model"], mcps, {TAGS_HEADER: json.dumps(tags)}, env)
print(f"Running {task} with {agent_name} ({agent['harness']}, {agent['model']}), tags {tags}", flush=True)

# One trace per run: a root span for the task, and a child span per tool call.
os.environ["MLFLOW_TRACKING_URI"] = "databricks"
mlflow.set_experiment(experiment_id=experiment_id)  # resolves the experiment's Unity Catalog trace location
trace = mlflow.start_span_no_context(task, span_type="AGENT", inputs={"prompt": prompt}, tags=tags)
print(f"MLflow trace {trace.trace_id}", flush=True)
tools, text, tokens = {}, [], [0, 0]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, cwd=work, text=True)
proc.stdin.write(prompt)
proc.stdin.close()
for line in proc.stdout:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    for kind, *args in events(event):
        if kind == "tool_start":
            call_id, name, inputs, *start = args
            tools[call_id] = mlflow.start_span_no_context(
                name, span_type="TOOL", parent_span=trace, inputs=inputs, start_time_ns=(start or [time.time_ns()])[0]
            )
        elif kind == "tool_end" and args[0] in tools:
            call_id, output, *end = args
            tools.pop(call_id).end(outputs=output, end_time_ns=(end or [time.time_ns()])[0])
        elif kind == "text":
            text.append(args[0])
        elif kind == "tokens":
            tokens = [tokens[0] + args[0], tokens[1] + args[1]]
proc.wait()

answer = text[-1] if text else ""
trace.end(
    outputs={"response": answer},
    attributes={"input_tokens": tokens[0], "output_tokens": tokens[1], "exit_code": proc.returncode},
    status="OK" if proc.returncode == 0 else "ERROR",
)
mlflow.flush_trace_async_logging()
print(answer)
if proc.returncode:
    sys.exit(f"{agent['harness']} exited with {proc.returncode}")
