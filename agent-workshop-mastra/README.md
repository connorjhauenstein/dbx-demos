# Learning Guide Agent — Databricks Agent Workshop (TypeScript/Mastra)

A skills-first learning guide agent built on Databricks, demonstrating the full MLflow observability, governance, and evaluation stack against a production-realistic TypeScript agent.

## What this demonstrates

| Capability | How it's implemented |
|---|---|
| **Agent deployment** | TypeScript/[Mastra](https://mastra.ai) agent running as a Databricks App |
| **OTel tracing → Unity Catalog** | Raw OTLP proto exporter → UC Delta tables, queryable with SQL |
| **MLflow experiment + Sessions** | Every conversation turn is a structured span; sessions group turns by thread |
| **Prompt Registry** | System prompt versioned in UC; loaded by alias — no code deploy to change behavior |
| **Custom LLM judges** | `make_judge` / `Guidelines` scorers defined as code, registered to the experiment |
| **Production monitoring** | Judges run continuously on sampled live traces; quality scores appear on every trace |
| **Offline evaluation** | Golden dataset in UC; `mlflow.genai.evaluate()` runs scorers against it on demand |
| **CI eval gate** | Eval job can be triggered pre-merge to catch quality regressions before they ship |

---

## Architecture

```
Browser → Databricks App (Node.js/Mastra) → Foundation Model API (Claude Sonnet)
                │
                ▼ OTLP proto
          /api/2.0/otel/v1/traces
                │
                ▼
     Unity Catalog Delta tables          MLflow Experiment
     agent_traces_otel_spans    ←→      (Traces + Sessions + Evaluations + Judges)
```

**Auth:** Dual — Databricks CLI token locally, OAuth M2M (injected `DATABRICKS_CLIENT_ID/SECRET`) when deployed as a Databricks App.

**Prompt Registry:** `src/prompt.ts` fetches the system prompt by alias at startup and polls every 5 min. Moving the `production` alias to a new prompt version updates every running instance without redeployment.

---

## Prerequisites

- Databricks workspace with:
  - **OpenTelemetry on Databricks** preview enabled (workspace settings)
  - **Managed MLflow Prompt Registry** enabled (workspace settings)
  - **Production Monitoring for MLflow** enabled (workspace settings)
  - A Foundation Model API endpoint (e.g. `databricks-claude-sonnet-4-6`)
  - A SQL warehouse (for monitoring and eval)
- Node.js 18+ and Python 3.10+
- Databricks CLI (`databricks` ≥ 0.200)

---

## Setup

### 1. Install dependencies

```bash
npm install
pip install "mlflow[databricks]>=3.9" openai databricks-sdk
```

> **Corporate network:** if your org proxies npm, point `.npmrc` at your internal registry
> and set `NODE_EXTRA_CA_CERTS` to your corp CA bundle.

### 2. Configure

```bash
cp .env.example .env
# Fill in DATABRICKS_HOST, DATABRICKS_TOKEN, MLFLOW_EXPERIMENT_ID,
# MLFLOW_UC_TRACE_TABLE, MLFLOW_PROMPT_NAME
```

See `.env.example` for all variables.

### 3. Create the MLflow experiment with UC trace backing

Run this once in a Databricks notebook (replace `<catalog>` and `<schema>`):

```python
import mlflow
from mlflow.tracing.destination import UnityCatalog

mlflow.set_tracking_uri("databricks")
exp = mlflow.set_experiment(
    experiment_name="/Users/<your-email>/agent-workshop-mastra",
    trace_location=UnityCatalog(
        catalog_name="<catalog>",
        schema_name="<schema>",
        table_prefix="agent_traces",
    ),
)
print(exp.experiment_id)   # set as MLFLOW_EXPERIMENT_ID in .env / app.yaml
```

### 4. Register the system prompt

```python
import mlflow
mlflow.set_tracking_uri("databricks")
client = mlflow.MlflowClient()
with open("prompts/system_prompt.md") as f:
    template = f.read()
client.create_prompt(name="<catalog>.<schema>.system_prompt")
v = client.create_prompt_version(name="<catalog>.<schema>.system_prompt", template=template)
client.set_prompt_alias(name="<catalog>.<schema>.system_prompt", alias="production", version=v.version)
```

### 5. Run locally

```bash
npm run chat -- "I want to move from data analyst to ML engineer. Where do I start?"
```

### 6. Deploy as a Databricks App

Update `app.yaml` with your workspace URL and UC paths, then:

```bash
databricks apps deploy agent-workshop-mastra --source-code-path .
```

---

## Eval layer

All eval code lives in `eval/`. Run each notebook in order to set up a new workspace.

### Register judges

```
eval/register_judges.py
```

Registers `learning_quality`, `helpful_on_topic`, and `conversation_consistency` to the MLflow experiment. Uses delete-then-register so re-running always applies the latest judge definition from git.

**Sync the repo first:**
```bash
databricks sync . /Workspace/Users/<your-email>/agent-workshop-mastra
```
Then update the `sys.path.insert` line in `register_judges.py` with your email.

### Start production monitoring

```
eval/start_monitoring.py
```

Turns on continuous scoring of live traces at `sample_rate=1.0`. Dial down for high-volume production.

### Run offline eval

```
eval/run_eval_dataset.py
```

Creates (or updates) a golden dataset in UC, runs the agent against every record, and scores with all registered judges + built-in `Correctness` and `RelevanceToQuery`. Results appear in the experiment's **Evaluations** tab.

This notebook is also wired as a **Databricks Job** — trigger it from the Jobs UI or call `databricks jobs run-now` from CI to gate merges on quality regression.

---

## Judge definitions

```
eval/judges/
  __init__.py                 # exports llm_judges(model)
  learning_quality.py         # custom make_judge: 1-5, learner usefulness
  helpful_on_topic.py         # Guidelines: concise, grounded, on-topic
  conversation_consistency.py # custom make_judge: multi-turn, reads {{ trace }}
```

Judges are code-managed (git is the source of truth). Never edit them in the UI — re-run `register_judges.py` after any change.

---

## Querying traces with SQL

Traces land in Unity Catalog and are queryable like any Delta table:

```sql
SELECT trace_id, session_id, request_time, status, token_count, assessments
FROM <catalog>.<schema>.agent_traces_trace_unified
ORDER BY request_time DESC
LIMIT 50;
```

---

## Cost notes

- **Trace storage:** cloud storage (S3/GCS) at standard rates — negligible.
- **Production monitoring judges:** each judge = one LLM FM API call per scored trace. `sample_rate` is the control knob.
- **Offline eval:** serverless notebook compute + FM API calls, on-demand only.
- **No per-trace Databricks surcharge** — MLflow tracing runs on the platform you already pay for.
