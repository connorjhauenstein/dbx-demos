"""Run one prompt from tasks/ headlessly with Claude Code or Codex, as the job's run-as identity.

Arguments: <bundle files root> <task name> <harness: claude | codex>
"""
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from databricks.sdk import WorkspaceClient

NODE_VERSION = "24.22.0"
CLIS = {"claude": "@anthropic-ai/claude-code@2.1.323", "codex": "@openai/codex@0.163.0"}

root, task, harness = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
prompt = (root / "tasks" / f"{task}.md").read_text()
agent_dir = root / "agents" / harness

# The job's run-as identity (the service principal) authenticates every gateway call.
w = WorkspaceClient()
host = w.config.host.rstrip("/")
token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")

# Node.js and the agent CLI, installed into a scratch directory.
work = Path(tempfile.mkdtemp())
arch = {"x86_64": "x64", "aarch64": "arm64"}[platform.machine()]
node = f"node-v{NODE_VERSION}-linux-{arch}"
with urllib.request.urlopen(f"https://nodejs.org/dist/v{NODE_VERSION}/{node}.tar.xz") as r:
    with tarfile.open(fileobj=r, mode="r|xz") as tar:
        tar.extractall(work, filter="data")
env = {
    **os.environ,
    "PATH": f"{work / node / 'bin'}:{os.environ['PATH']}",
    "HOME": str(work),
    "DATABRICKS_HOST": host,
    "DATABRICKS_TOKEN": token,
}
subprocess.run(["npm", "install", "-g", "--silent", CLIS[harness]], env=env, check=True)

if harness == "claude":
    env |= {
        "ANTHROPIC_BASE_URL": f"{host}/ai-gateway/anthropic",
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_CUSTOM_HEADERS": "x-databricks-use-coding-agent-mode: true",
    }
    cmd = [
        "claude", "-p", "--bare",
        "--settings", str(agent_dir / "settings.json"),
        "--mcp-config", str(agent_dir / "mcp.json"), "--strict-mcp-config",
        "--permission-mode", "dontAsk",
    ]
else:
    codex_home = work / ".codex"
    codex_home.mkdir()
    config = (agent_dir / "config.toml").read_text().replace("${DATABRICKS_HOST}", host)
    (codex_home / "config.toml").write_text(config)
    env["CODEX_HOME"] = str(codex_home)
    cmd = [
        "codex", "exec", "--skip-git-repo-check", "--ephemeral",
        "-s", "read-only", "--disable", "shell_tool", "-",
    ]

result = subprocess.run(cmd, input=prompt, env=env, cwd=work, capture_output=True, text=True)
print(result.stdout)
print(result.stderr, file=sys.stderr)
result.check_returncode()
