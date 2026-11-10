# Databricks notebook source
# MAGIC %pip install -qq --upgrade "mlflow[databricks]>=3.10" databricks-langchain langgraph langgraph-checkpoint-postgres "psycopg[binary]>=3.1"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC # Agent Workshop — Tracing & Observability
# MAGIC
# MAGIC This notebook runs the **exact same agent and checkpointer** as the deployed Agent Workshop API app.
# MAGIC Same code, same Lakebase conversation memory, same MLflow experiment.

# COMMAND ----------

import mlflow
import os

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Shared/agent-workshop-uc")
mlflow.langchain.autolog()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load the production agent
# MAGIC Same code as the deployed app, connected to the same Lakebase checkpointer.

# COMMAND ----------

import sys

# TODO: Update these to match your deployment
AGENT_API_WORKSPACE_PATH = "/Workspace/Users/<YOUR_EMAIL>/agent-workshop-api"
WAREHOUSE_ID = "<YOUR_WAREHOUSE_ID>"

sys.path.insert(0, AGENT_API_WORKSPACE_PATH)
os.environ["MODEL_NAME"] = "databricks-meta-llama-3-3-70b-instruct"
os.environ["DATABRICKS_WAREHOUSE_ID"] = WAREHOUSE_ID

import psycopg
from agent import create_graph
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import HumanMessage

# Connect to the same Lakebase instance as the deployed app
LAKEBASE_CONN_STR = dbutils.secrets.get(scope="agent-workshop-api", key="lakebase-conn-str")
saver_conn = psycopg.connect(LAKEBASE_CONN_STR, autocommit=True)
saver = PostgresSaver(saver_conn)
saver.setup()

graph = create_graph(saver)
print("Agent loaded — same code + same Lakebase checkpointer as production")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Turn 1 — Simple question (no tools)

# COMMAND ----------

result = graph.invoke(
    {"messages": [HumanMessage(content="Hi! What can you help me with?")]},
    config={"configurable": {"thread_id": "notebook-session-1"}},
)
print(result["messages"][-1].content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Turn 2 — Triggers a tool call (SQL query)

# COMMAND ----------

result = graph.invoke(
    {"messages": [HumanMessage(content="What catalogs are available in my workspace?")]},
    config={"configurable": {"thread_id": "notebook-session-1"}},
)
print(result["messages"][-1].content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Turn 3 — Follow-up (tests conversation memory)

# COMMAND ----------

result = graph.invoke(
    {"messages": [HumanMessage(content="How many schemas does the first one have?")]},
    config={"configurable": {"thread_id": "notebook-session-1"}},
)
print(result["messages"][-1].content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## View Traces
# MAGIC
# MAGIC Click the **experiment icon** in the right sidebar, then open the **Traces** tab to see:
# MAGIC - Full span tree (LLM calls, tool executions)
# MAGIC - Token usage per call
# MAGIC - Input/output at every step
# MAGIC - Latency breakdown
# MAGIC
# MAGIC Or navigate to **Experiments > Shared > agent-workshop-uc** in the left sidebar.
# MAGIC
# MAGIC Traces from this notebook and the deployed app all appear in the same experiment.
