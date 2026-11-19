"""Check that an agent app speaks the Agent Bricks invocation API the playground uses.

Usage: uv run --with databricks-sdk python check_agent.py <agent app URL> [--profile <profile>]

Checks, as the signed-in CLI user (Databricks Apps accept OAuth tokens, not PATs):
1. A streamed turn starts with run.started, ends with run.completed, and returns an assistant message.
2. A second turn in the same session remembers the first.
Message items may use either shape the playground accepts: {"role": "assistant", "content": "..."}
or LangChain's {"type": "ai", "content": [{"type": "text", "text": "..."}]}.
"""

import argparse
import json
import secrets
import sys
import urllib.request
import uuid

from databricks.sdk import WorkspaceClient

parser = argparse.ArgumentParser()
parser.add_argument("url")
parser.add_argument("--profile")
args = parser.parse_args()
url = args.url.rstrip("/") + "/api/invocations"
headers = WorkspaceClient(profile=args.profile).config.authenticate() | {"Content-Type": "application/json"}


def post(body: dict):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    return urllib.request.urlopen(request, timeout=300)


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def turn(session_id: str, text: str) -> tuple[list[dict], str]:
    """Send one streamed turn; return its events and the last assistant text."""
    body = {"id": str(uuid.uuid4()), "session_id": session_id, "input": {"messages": [{"role": "user", "content": text}]}, "stream": True}
    with post(body) as response:
        events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
    messages = [e["message"] for e in events if e.get("type") == "message"]
    texts = [text_of(m.get("content")) for m in messages if (m.get("role") or m.get("type")) in ("assistant", "ai")]
    texts = [t for t in texts if t]
    return events, texts[-1] if texts else ""


failures = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


session, word = str(uuid.uuid4()), f"word-{secrets.token_hex(3)}"
events, answer = turn(session, f"Remember this word: {word}. Reply with just OK.")
types = [e.get("type") for e in events]
check("stream starts with run.started", types[:1] == ["run.started"], f"first event {types[:1]}")
check("stream ends with run.completed", types[-1:] == ["run.completed"], f"last event {types[-1:]}")
check("events use known types", set(types) <= {"run.started", "delta", "message", "interrupt", "run.completed", "run.failed"}, f"{sorted(set(types))}")
check("returns an assistant message", bool(answer), "no assistant message with content")

_, answer = turn(session, "What word did I ask you to remember? Reply with just the word.")
check("remembers the session", word in answer, f"answer was {answer[:80]!r}")

sys.exit(1 if failures else 0)
