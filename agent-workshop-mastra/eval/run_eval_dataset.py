# Databricks notebook source
# MAGIC %pip install -U "mlflow[databricks]>=3.9" openai
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
# Canonical offline eval: runs FROM the registered UC dataset, using the REGISTERED
# judges (single source of truth = eval/judges/, registered via register_judges.py).
import os, json, mlflow
import mlflow.genai.datasets
from mlflow.genai.scorers import get_scorer, Correctness, RelevanceToQuery
from databricks.sdk import WorkspaceClient

# ── Configure for your workspace ──────────────────────────────────────────────
EXP   = "<your-mlflow-experiment-id>"
WH    = "<your-sql-warehouse-id>"
MODEL = "databricks-claude-sonnet-4-6"
JUDGE = "databricks:/databricks-claude-sonnet-4-6"
PROMPT = "<catalog>.<schema>.system_prompt"   # registered in the MLflow Prompt Registry
DS    = "<catalog>.<schema>.eval_golden"       # registered UC eval dataset
# ──────────────────────────────────────────────────────────────────────────────

os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = WH
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=EXP)
client = WorkspaceClient().serving_endpoints.get_open_ai_client()
SYS = mlflow.genai.load_prompt(f"prompts:/{PROMPT}@production").template

def agent(message):
    r = client.chat.completions.create(model=MODEL,
        messages=[{"role": "system", "content": SYS}, {"role": "user", "content": message}], max_tokens=512)
    return {"response": r.choices[0].message.content}

records = [
    {"inputs": {"message": "I want to move from data analyst to ML engineer. Where do I start?"},
     "expectations": {"expected_facts": ["identify the skill gap between data analyst and ML engineer", "recommend foundational skills such as machine learning fundamentals or Python for ML", "suggest a sequenced learning path", "be concrete about effort or pacing"]}},
    {"inputs": {"message": "What skills do I need to become a backend developer?"},
     "expectations": {"expected_facts": ["name specific technical skills such as APIs, databases, or a backend language", "explain why those skills matter for the role", "suggest a logical learning order"]}},
    {"inputs": {"message": "I have 3 hours a week. Can I learn data engineering in 6 months?"},
     "expectations": {"expected_facts": ["acknowledge the time constraint", "give an honest assessment of what is achievable in that timeframe", "suggest a realistic scope or adjusted goal"]}},
    {"inputs": {"message": "What is the difference between data science and machine learning engineering?"},
     "expectations": {"expected_facts": ["distinguish the roles by responsibility or skill focus", "mention that data scientists focus on analysis and modeling while ML engineers focus on productionizing models", "be concrete and concise"]}},
]
try:
    ds = mlflow.genai.datasets.get_dataset(DS)
except Exception:
    ds = mlflow.genai.datasets.create_dataset(uc_table_name=DS)
ds.merge_records(records)

scorers = [
    get_scorer(name="learning_quality", experiment_id=EXP),   # registered custom judge
    get_scorer(name="helpful_on_topic", experiment_id=EXP),   # registered Guidelines judge
    Correctness(model=JUDGE),                                  # accuracy vs expected_facts
    RelevanceToQuery(model=JUDGE),                             # reference-free relevance
]
res = mlflow.genai.evaluate(data=ds, predict_fn=agent, scorers=scorers)
dbutils.notebook.exit(json.dumps({"dataset": DS, "records": len(ds.to_df()), "run_id": res.run_id, "metrics": res.metrics}, default=str)[:2500])
