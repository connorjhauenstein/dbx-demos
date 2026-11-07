# Databricks notebook source
# MAGIC %md
# MAGIC # Demo data for the metric-view MCP
# MAGIC Builds synthetic app events in `raw_schema` and two metric views in `semantic_schema`.
# MAGIC Skip this and point the MCP at your own metric views.

# COMMAND ----------

import os

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("raw_schema", "")
dbutils.widgets.text("semantic_schema", "")
values = {k: dbutils.widgets.get(k) for k in ("catalog", "raw_schema", "semantic_schema")}

here = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())
root = "/Workspace" + here


def render(path: str) -> str:
    text = open(path).read()
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


# COMMAND ----------

for statement in render(f"{root}/01_demo_data.sql").split(";\n"):
    body = "\n".join(l for l in statement.splitlines() if not l.strip().startswith("--")).strip()
    if body:
        spark.sql(body)

for name in sorted(os.listdir(f"{root}/metric_views")):
    spark.sql(render(f"{root}/metric_views/{name}"))
    print(f"created metric view from {name}")
