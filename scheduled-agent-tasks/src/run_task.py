"""Run a task with an agent, headless, as the job's run-as identity.

Arguments: <bundle files root> <task name> <agent name> <platform schema>

The task (tasks/<task>.md) names the Unity Gateway MCP services and skills it needs, and the tools it may call.
The agent (agents/<agent>.yml) names a harness and model. This script writes that harness's own config, with only
the task's tools allowed, and runs it. Names without a catalog resolve to the platform schema.
"""
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

NODE_VERSION = "24.22.0"
CLIS = {
    "claude": "@anthropic-ai/claude-code@2.1.323",
    "codex": "@openai/codex@0.163.0",
    "opencode": "opencode-ai@1.19.5",
}


def claude(work, host, model, mcps, env):
    env |= {
        "ANTHROPIC_BASE_URL": f"{host}/ai-gateway/anthropic",
        "ANTHROPIC_AUTH_TOKEN": env["DATABRICKS_TOKEN"],
        "ANTHROPIC_CUSTOM_HEADERS": "x-databricks-use-coding-agent-mode: true",
    }
    servers = {
        name: {"type": "http", "url": m["url"], "headers": {"Authorization": "Bearer ${DATABRICKS_TOKEN}"}}
        for name, m in mcps.items()
    }
    allow = [f"mcp__{name}__{tool}" for name, m in mcps.items() for tool in m["tools"]]
    (work / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
    (work / "settings.json").write_text(json.dumps({"model": model, "permissions": {"allow": allow}}))
    return [
        "claude", "-p", "--bare", "--settings", "settings.json",
        "--mcp-config", "mcp.json", "--strict-mcp-config", "--permission-mode", "dontAsk",
    ]


def codex(work, host, model, mcps, env):
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
    ]
    for name, m in mcps.items():
        lines += [
            f"[mcp_servers.{name}]",
            f"url = {json.dumps(m['url'])}",
            'bearer_token_env_var = "DATABRICKS_TOKEN"',
            f"enabled_tools = {json.dumps(m['tools'])}",
            'default_tools_approval_mode = "approve"',
        ]
    (work / ".codex").mkdir()
    (work / ".codex" / "config.toml").write_text("\n".join(lines) + "\n")
    env["CODEX_HOME"] = str(work / ".codex")
    return ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--disable", "shell_tool", "-"]


def opencode(work, host, model, mcps, env):
    auth = {"Authorization": "Bearer {env:DATABRICKS_TOKEN}"}
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"unity-gateway/{model}",
        "provider": {
            "unity-gateway": {
                "npm": "@ai-sdk/anthropic",
                "options": {"baseURL": f"{host}/ai-gateway/anthropic/v1", "apiKey": "{env:DATABRICKS_TOKEN}", "headers": auth},
                "models": {model: {"options": {"toolStreaming": False}}},
            }
        },
        "mcp": {"servers": {name: {"type": "remote", "url": m["url"], "oauth": False, "headers": auth} for name, m in mcps.items()}},
        "permission": {"*": "deny"} | {f"{name}_{tool}": "allow" for name, m in mcps.items() for tool in m["tools"]},
    }
    (work / "opencode.json").write_text(json.dumps(config))
    env["OPENCODE_CONFIG"] = str(work / "opencode.json")
    return ["opencode", "run"]


def uc_name(name):
    """Names without a catalog resolve to the platform schema."""
    return name if "." in name else f"{platform_schema}.{name}"


HARNESSES = {"claude": claude, "codex": codex, "opencode": opencode}

root, task, agent_name, platform_schema = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
_, meta, prompt = (root / "tasks" / f"{task}.md").read_text().split("---", 2)
meta = yaml.safe_load(meta)
agent = yaml.safe_load((root / "agents" / f"{agent_name}.yml").read_text())

# The job's run-as identity (the service principal) authenticates every gateway call.
w = WorkspaceClient()
host = w.config.host.rstrip("/")
token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")


mcps = {
    uc_name(name).split(".")[-1]: {"url": f"{host}/ai-gateway/mcp-services/{uc_name(name)}", "tools": tools}
    for name, tools in meta.get("mcps", {}).items()
}
skills = [uc_name(name) for name in meta.get("skills", [])]
if skills:
    schemas = "&".join(f"schema={s}" for s in sorted({s.rsplit(".", 1)[0] for s in skills}))
    mcps["skills"] = {"url": f"{host}/ai-gateway/skills/?{schemas}", "tools": ["load_skill", "get_skill_files"]}
    prompt = f"First load these skills with the `skills` MCP tool `load_skill`: {', '.join(skills)}.\n\n{prompt.strip()}"

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
harness = agent["harness"]
subprocess.run(["npm", "install", "-g", "--silent", CLIS[harness]], env=env, check=True)

cmd = HARNESSES[harness](work, host, agent["model"], mcps, env)
print(f"Running {task} with {agent_name} ({harness}, {agent['model']})", flush=True)
result = subprocess.run(cmd, input=prompt.strip(), env=env, cwd=work, capture_output=True, text=True)
print(result.stdout)
print(result.stderr, file=sys.stderr)
result.check_returncode()
