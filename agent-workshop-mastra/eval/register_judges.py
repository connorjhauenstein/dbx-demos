# Databricks notebook source
# MAGIC %pip install -U "mlflow[databricks]>=3.9"
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import sys, json, mlflow
# After `databricks sync . /Workspace/Users/<your-email>/agent-workshop-mastra`,
# insert the synced eval directory so the judges package is importable:
sys.path.insert(0, "/Workspace/Users/<your-email>/agent-workshop-mastra/eval")
from judges import llm_judges
from mlflow.genai.scorers import list_scorers, delete_scorer

# ── Configure for your workspace ──────────────────────────────────────────────
EXP   = "<your-mlflow-experiment-id>"
JUDGE = "databricks:/databricks-claude-sonnet-4-6"
# ──────────────────────────────────────────────────────────────────────────────
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=EXP)

out = {}
for j in llm_judges(JUDGE):
    # delete-then-register so the latest definition (e.g. updated instructions) is applied
    try:
        delete_scorer(name=j.name, experiment_id=EXP)
    except Exception:
        pass
    try:
        j.register(experiment_id=EXP)
        out[j.name] = "registered"
    except Exception as e:
        out[j.name] = f"ERR: {e!r}"

try:
    out["registered_now"] = [s.name for s in list_scorers(experiment_id=EXP)]
except Exception as e:
    out["list_error"] = repr(e)

dbutils.notebook.exit(json.dumps(out, default=str)[:2000])
