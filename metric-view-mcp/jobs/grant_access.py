# Databricks notebook source
# Grants USE CATALOG, USE SCHEMA, and SELECT on each metric view in allowed_schemas to the
# app's service principal and the consumer group. Nothing on source tables: metric views run
# with their owner's rights. Safe to rerun.

from databricks.sdk import WorkspaceClient

app_sp = WorkspaceClient().apps.get(dbutils.widgets.get("app_name")).service_principal_client_id
principals = [app_sp, dbutils.widgets.get("consumer_group")]
schemas = [s.strip().lower() for s in dbutils.widgets.get("allowed_schemas").split(",")]

views = [r[0] for r in spark.sql(
    "SELECT concat_ws('.', table_catalog, table_schema, table_name) FROM system.information_schema.tables "
    "WHERE table_type = 'METRIC_VIEW' AND array_contains(:schemas, lower(concat_ws('.', table_catalog, table_schema)))",
    args={"schemas": schemas},
).collect()]


def q(name):
    return ".".join(f"`{p}`" for p in name.split("."))


for p in principals:
    for s in schemas:
        spark.sql(f"GRANT USE CATALOG ON CATALOG {q(s.split('.')[0])} TO `{p}`")
        spark.sql(f"GRANT USE SCHEMA ON SCHEMA {q(s)} TO `{p}`")
    for v in views:
        spark.sql(f"GRANT SELECT ON TABLE {q(v)} TO `{p}`")

print(f"Granted SELECT on {views} to {principals}")
