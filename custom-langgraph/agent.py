"""LangGraph agent: a Unity AI Gateway model, one in-code SQL tool, Lakebase memory, MLflow traces."""

import asyncio
import os
import queue
import threading

import mlflow
from databricks_langchain import ChatDatabricks
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from tools import TOOLS

MODEL_NAME = os.environ.get("MODEL_NAME", "system.ai.claude-sonnet-5-5")
SYSTEM_PROMPT = open(os.path.join(os.path.dirname(__file__), "system_prompt.md")).read().strip()

# Traces go to the UC trace tables behind this experiment (set by the bundle's uc_trace_location).
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])
mlflow.langchain.autolog()


def create_graph(checkpointer):
    """Build the agent. The model is served through Unity AI Gateway."""
    # Claude's between-tool updates come back as thinking blocks, which databricks_langchain would
    # stream as JSON text. "between_tools" turns those blocks off so the text stream stays clean.
    llm = ChatDatabricks(
        model=MODEL_NAME,
        use_ai_gateway=True,
        extra_params={"extra_body": {"thinking": {"type": "between_tools"}}},
    )
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def _text(content) -> str:
    """Message text, whether the model returned a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")


def _message_item(message) -> dict | None:
    """A completed LangChain message as an Agent Bricks message item, or None to skip it."""
    if message.type == "ai":
        item = {"role": "assistant", "content": _text(message.content)}
        if message.tool_calls:
            item["tool_calls"] = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in message.tool_calls]
        return item if item["content"] or message.tool_calls else None
    if message.type == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "name": message.name, "content": _text(message.content)}
    return None


async def run_turn(graph, session_id: str, message: str):
    """Run one turn and yield Agent Bricks invocation events.

    run.started, then "delta" text chunks and completed "message" items (assistant text, tool calls,
    tool results), then run.completed or run.failed. The session ID is the LangGraph thread.
    """
    q = queue.Queue()

    def _stream():
        try:
            q.put({"type": "run.started"})
            with mlflow.start_span(name="agent_turn", span_type="AGENT") as span:
                span.set_inputs({"message": message})
                mlflow.update_current_trace(tags={"mlflow.trace.session": session_id})
                answer = ""
                for mode, payload in graph.stream(
                    {"messages": [HumanMessage(content=message)]},
                    config={"configurable": {"thread_id": session_id}},
                    stream_mode=["messages", "updates"],
                ):
                    if mode == "messages":
                        chunk = payload[0]
                        if chunk.type == "AIMessageChunk" and (text := _text(chunk.content)):
                            q.put({"type": "delta", "content": text})
                    else:
                        for node in payload.values():
                            for msg in (node or {}).get("messages", []):
                                if item := _message_item(msg):
                                    answer = item["content"] if item["role"] == "assistant" and item["content"] else answer
                                    q.put({"type": "message", "message": item})
                span.set_outputs({"response": answer})
            q.put({"type": "run.completed"})
        except Exception as e:
            q.put({"type": "run.failed", "error": str(e)})
        q.put(None)

    threading.Thread(target=_stream, daemon=True).start()
    while (event := await asyncio.to_thread(q.get)) is not None:
        yield event
