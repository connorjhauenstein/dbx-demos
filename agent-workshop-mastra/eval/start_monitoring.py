# Databricks notebook source
# MAGIC %pip install -U "mlflow[databricks]>=3.9"
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
# Flip the registered judges to ON: run them continuously on sampled production traces.
import json, mlflow
from mlflow.genai.scorers import get_scorer, list_scorers, ScorerSamplingConfig
from mlflow.tracing import set_databricks_monitoring_sql_warehouse_id

# ── Configure for your workspace ──────────────────────────────────────────────
EXP = "<your-mlflow-experiment-id>"
WH  = "<your-sql-warehouse-id>"
# ──────────────────────────────────────────────────────────────────────────────
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=EXP)
set_databricks_monitoring_sql_warehouse_id(WH)  # positional: sets the monitoring SQL warehouse

out = {}
# sample_rate 1.0 for the demo (low traffic); dial down for high-volume prod.
for name, rate in [("learning_quality", 1.0), ("helpful_on_topic", 1.0), ("conversation_consistency", 1.0)]:
    try:
        s = get_scorer(name=name, experiment_id=EXP)
        s.start(sampling_config=ScorerSamplingConfig(sample_rate=rate))
        out[name] = f"monitoring ON @ sample_rate={rate}"
    except Exception as e:
        out[name] = f"ERR: {e!r}"

try:
    out["status"] = [(sc.name, getattr(getattr(sc, "sampling_config", None), "sample_rate", None)) for sc in list_scorers(experiment_id=EXP)]
except Exception as e:
    out["list_err"] = repr(e)

dbutils.notebook.exit(json.dumps(out, default=str)[:2000])
