# Databricks notebook source
# MAGIC %md
# MAGIC # Agent Workshop — Setup & Walkthrough
# MAGIC
# MAGIC Build an AI agent with **conversation memory**, **tool use**, **token streaming**, and **MLflow tracing** — deployed as two Databricks Apps.
# MAGIC
# MAGIC ## Architecture
# MAGIC
# MAGIC ```
# MAGIC ┌───────────────┐     ┌────────────────────┐     ┌──────────┐
# MAGIC │ Frontend App  │────▶│  Agent API App     │────▶│ Lakebase │
# MAGIC │ (Chat UI)     │     │  (LangGraph +      │     │ (Memory) │
# MAGIC │               │     │   MLflow Tracing)  │     │          │
# MAGIC └───────────────┘     └────────────────────┘     └──────────┘
# MAGIC                                │
# MAGIC                                ▼
# MAGIC                       ┌────────────────────┐
# MAGIC                       │ MLflow Experiment   │
# MAGIC                       │ (Traces in UC      │
# MAGIC                       │  Volume)           │
# MAGIC                       └────────────────────┘
# MAGIC ```
# MAGIC
# MAGIC ## Project Structure
# MAGIC
# MAGIC | Directory | Purpose | Deployed As |
# MAGIC |-----------|---------|-------------|
# MAGIC | `agent-api/` | LangGraph agent REST API + API docs | Databricks App |
# MAGIC | `frontend/` | Chat UI with streaming + tool blocks | Databricks App |
# MAGIC | `notebooks/` | Tracing notebook + this guide | Workspace notebooks |

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 1: Prerequisites
# MAGIC
# MAGIC 1. **Databricks CLI** installed and authenticated
# MAGIC 2. **A SQL Warehouse** — note the warehouse ID
# MAGIC 3. **A Foundation Model endpoint** — e.g., `databricks-meta-llama-3-3-70b-instruct`

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 2: Set Up Lakebase (Conversation Memory)
# MAGIC
# MAGIC ### 2a. Create a Lakebase project
# MAGIC
# MAGIC **Catalog** → **Lakebase** → **Create Project**
# MAGIC - Name: `agent-memory` (or your choice)
# MAGIC - Default `production` branch and `primary` endpoint are created automatically
# MAGIC
# MAGIC ### 2b. Create the agent-api app
# MAGIC
# MAGIC ```bash
# MAGIC # Create secret scope
# MAGIC databricks secrets create-scope agent-workshop-api
# MAGIC databricks secrets put-secret agent-workshop-api lakebase-conn-str --string-value "placeholder"
# MAGIC
# MAGIC # Create app with secret resource
# MAGIC # (Use the UI or REST API — see Databricks Apps docs)
# MAGIC ```
# MAGIC
# MAGIC ### 2c. Grant the app's service principal access to Lakebase
# MAGIC
# MAGIC Get the app's SP client ID from the app details page, then:
# MAGIC
# MAGIC ```python
# MAGIC import psycopg, secrets
# MAGIC from psycopg import sql
# MAGIC from databricks.sdk import WorkspaceClient
# MAGIC
# MAGIC w = WorkspaceClient()
# MAGIC
# MAGIC # Generate a fresh OAuth token to connect as yourself
# MAGIC cred = w.postgres.generate_database_credential(
# MAGIC     endpoint="projects/<PROJECT>/branches/production/endpoints/primary"
# MAGIC )
# MAGIC conn = psycopg.connect(
# MAGIC     f"postgresql://<YOUR_EMAIL>:{cred.token}@<LAKEBASE_HOST>/databricks_postgres?sslmode=require",
# MAGIC     autocommit=True,
# MAGIC )
# MAGIC
# MAGIC SP_ID = "<APP_SERVICE_PRINCIPAL_CLIENT_ID>"
# MAGIC PASSWORD = secrets.token_urlsafe(32)
# MAGIC
# MAGIC cur = conn.cursor()
# MAGIC cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(SP_ID)))
# MAGIC cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(sql.Identifier(SP_ID), sql.Literal(PASSWORD)))
# MAGIC cur.execute(sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(SP_ID)))
# MAGIC cur.execute(sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(SP_ID)))
# MAGIC cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}").format(sql.Identifier(SP_ID)))
# MAGIC conn.close()
# MAGIC
# MAGIC print(f"Password: {PASSWORD}")
# MAGIC ```
# MAGIC
# MAGIC ### 2d. Store the connection string
# MAGIC
# MAGIC ```bash
# MAGIC databricks secrets put-secret agent-workshop-api lakebase-conn-str \
# MAGIC   --string-value "postgresql://<SP_ID>:<PASSWORD>@<LAKEBASE_HOST>/databricks_postgres?sslmode=require"
# MAGIC ```
# MAGIC
# MAGIC > **Note:** Native Postgres passwords don't expire — no token refresh needed.

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 3: Set Up MLflow Tracing
# MAGIC
# MAGIC ### 3a. Create a UC schema and volume for trace artifacts
# MAGIC
# MAGIC ```sql
# MAGIC CREATE SCHEMA IF NOT EXISTS main.agent_workshop;
# MAGIC CREATE VOLUME IF NOT EXISTS main.agent_workshop.mlflow_artifacts;
# MAGIC
# MAGIC -- Grant the agent-api app's SP access
# MAGIC GRANT ALL PRIVILEGES ON SCHEMA main.agent_workshop TO `<SP_CLIENT_ID>`;
# MAGIC GRANT ALL PRIVILEGES ON VOLUME main.agent_workshop.mlflow_artifacts TO `<SP_CLIENT_ID>`;
# MAGIC ```
# MAGIC
# MAGIC ### 3b. Create the MLflow experiment
# MAGIC
# MAGIC ```python
# MAGIC import mlflow
# MAGIC mlflow.set_tracking_uri("databricks")
# MAGIC mlflow.create_experiment(
# MAGIC     name="/Shared/agent-workshop-uc",
# MAGIC     artifact_location="dbfs:/Volumes/main/agent_workshop/mlflow_artifacts",
# MAGIC )
# MAGIC ```
# MAGIC
# MAGIC > **Why UC Volume?** Databricks Apps can't reach cloud storage directly for artifact uploads.
# MAGIC > By pointing the experiment artifact location to a UC Volume, traces upload via the workspace API.
# MAGIC
# MAGIC ### 3c. Add MLflow experiment as an app resource
# MAGIC
# MAGIC In the app settings UI: **Resources** → **Add** → **MLflow Experiment** → select `/Shared/agent-workshop-uc`

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 4: Deploy the Agent API
# MAGIC
# MAGIC **Files in `agent-api/`:**
# MAGIC
# MAGIC | File | Purpose |
# MAGIC |------|---------|
# MAGIC | `agent.py` | LangGraph agent using `create_agent()` — LLM + tools + checkpointer |
# MAGIC | `tools.py` | SQL query tool for Unity Catalog |
# MAGIC | `system_prompt.md` | Agent's system prompt — edit to change behavior, no code changes |
# MAGIC | `main.py` | FastAPI with `/chat`, `/chat/stream` (SSE token streaming), `/history`, `/threads` |
# MAGIC | `index.html` | Interactive API docs with "Try it" buttons |
# MAGIC | `app.yaml` | App config — update `DATABRICKS_WAREHOUSE_ID` with your warehouse |
# MAGIC | `requirements.txt` | Python dependencies |
# MAGIC
# MAGIC ### 4a. Update `agent-api/app.yaml`
# MAGIC
# MAGIC Set `DATABRICKS_WAREHOUSE_ID` to your SQL warehouse ID.
# MAGIC
# MAGIC ### 4b. Deploy
# MAGIC
# MAGIC ```bash
# MAGIC databricks workspace import-dir ./agent-api /Workspace/Users/<YOU>/agent-workshop-api --overwrite
# MAGIC databricks apps deploy agent-workshop-api \
# MAGIC   --source-code-path /Workspace/Users/<YOU>/agent-workshop-api
# MAGIC ```
# MAGIC
# MAGIC ### 4c. Verify
# MAGIC
# MAGIC - Open the app URL → API docs page
# MAGIC - Click "Try it" on `/chat`
# MAGIC - Check **Experiments → Shared → agent-workshop-uc → Traces** for full span tree

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 5: Deploy the Frontend
# MAGIC
# MAGIC **Files in `frontend/`:**
# MAGIC
# MAGIC | File | Purpose |
# MAGIC |------|---------|
# MAGIC | `main.py` | FastAPI — serves static files + `/api-url` config endpoint |
# MAGIC | `static/index.html` | Chat UI structure |
# MAGIC | `static/styles.css` | All CSS |
# MAGIC | `static/app.js` | All JavaScript — streaming, tool blocks, markdown, thread management |
# MAGIC | `app.yaml` | Points `AGENT_API_URL` to the agent-api app |
# MAGIC | `requirements.txt` | Minimal (no AI dependencies) |
# MAGIC
# MAGIC ### 5a. Update `frontend/app.yaml`
# MAGIC
# MAGIC Set `AGENT_API_URL` to your agent-api app's URL from Step 4.
# MAGIC
# MAGIC ### 5b. Deploy
# MAGIC
# MAGIC ```bash
# MAGIC databricks workspace import-dir ./frontend /Workspace/Users/<YOU>/agent-workshop-frontend --overwrite
# MAGIC databricks apps deploy agent-workshop \
# MAGIC   --source-code-path /Workspace/Users/<YOU>/agent-workshop-frontend
# MAGIC ```
# MAGIC
# MAGIC ### 5c. Test
# MAGIC
# MAGIC - Open the frontend URL
# MAGIC - Start a new conversation
# MAGIC - Ask "What catalogs are available?" — watch tokens stream in + tool call blocks expand
# MAGIC - Open an older thread — history loads from Lakebase with tool blocks preserved

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Step 6: Notebooks
# MAGIC
# MAGIC | Notebook | Purpose |
# MAGIC |----------|---------|
# MAGIC | `run_agent.py` | Run the same agent code with full MLflow trace visibility |
# MAGIC | `workshop_guide.py` | This walkthrough |
# MAGIC
# MAGIC The `run_agent` notebook imports the deployed agent code, connects to the same Lakebase, and logs to the same experiment. Update the config variables at the top before running.

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Key Concepts
# MAGIC
# MAGIC ### Agent (`agent.py`)
# MAGIC Uses `langchain.agents.create_agent()` — one function call that wires up the LLM, tools, and ReAct loop. System prompt is loaded from `system_prompt.md` at startup.
# MAGIC
# MAGIC ### Conversation Memory
# MAGIC LangGraph's **checkpointer** persists full message history to Lakebase (PostgreSQL). The `thread_id` groups messages into conversations — same thread = continued conversation.
# MAGIC
# MAGIC ### Token Streaming
# MAGIC `/chat/stream` uses **Server-Sent Events** with LangGraph's `stream_mode="messages"`. Tokens appear one-by-one in the UI. Tool calls show as expandable blocks with live status.
# MAGIC
# MAGIC ### MLflow Tracing
# MAGIC `mlflow.langchain.autolog()` captures every LLM call, tool execution, and token count. Trace artifacts are stored in a **UC Volume** (workaround for Apps networking). View full span trees in the Experiments UI.
# MAGIC
# MAGIC ### Two-App Architecture
# MAGIC Separate apps for the agent API and chat UI:
# MAGIC - Independent deployment and scaling
# MAGIC - Multiple consumers (chat UI, API clients, notebooks) share one agent
# MAGIC - API docs page doubles as documentation and testing tool
# MAGIC
# MAGIC ### System Prompt
# MAGIC Defined in `system_prompt.md` — a plain text file separate from code. Edit it, redeploy, behavior changes. No code changes needed.
