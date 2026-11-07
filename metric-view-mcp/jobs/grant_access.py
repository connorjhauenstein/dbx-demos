# Databricks notebook source
# Grants USE CATALOG, USE SCHEMA, and SELECT on each metric view in config.yml's scope to the
# app's service principal and the consumer group. Nothing on source tables: metric views run
# with their owner's rights. Safe to rerun.

import os
import sys

sys.path.append(os.path.dirname(os.getcwd()))  # bundle root, so the app's scope module imports

from databricks.sdk import WorkspaceClient
from metric_view_mcp.scope import in_scope, load_include

include = load_include()
app_sp = WorkspaceClient().apps.get(dbutils.widgets.get("app_name")).service_principal_client_id
principals = [app_sp, dbutils.widgets.get("consumer_group")]

views = [r[0] for r in spark.sql(
    "SELECT lower(concat_ws('.', table_catalog, table_schema, table_name)) "
    "FROM system.information_schema.tables WHERE table_type = 'METRIC_VIEW'"
).collect() if in_scope(r[0], include)]


def q(name):
    return ".".join(f"`{p}`" for p in name.split("."))


for p in principals:
    for catalog in {v.split(".")[0] for v in views}:
        spark.sql(f"GRANT USE CATALOG ON CATALOG {q(catalog)} TO `{p}`")
    for schema in {v.rsplit(".", 1)[0] for v in views}:
        spark.sql(f"GRANT USE SCHEMA ON SCHEMA {q(schema)} TO `{p}`")
    for v in views:
        spark.sql(f"GRANT SELECT ON TABLE {q(v)} TO `{p}`")

print(f"Granted SELECT on {len(views)} metric views {views} to {principals}")
