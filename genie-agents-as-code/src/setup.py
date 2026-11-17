# Databricks notebook source
# Creates synthetic product-analytics tables and three metric views for the demo.

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
target = f"{catalog}.{schema}"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target}")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {target}.events AS
SELECT
  id % 5000 AS user_id,
  date_add(DATE'2026-01-01', CAST(rand(1) * 90 AS INT)) AS event_date,
  element_at(array('search', 'share', 'export', 'alerts', 'dashboard'), CAST(rand(2) * 5 AS INT) + 1) AS feature,
  element_at(array('ios', 'android', 'web'), CAST(id % 5000 % 3 AS INT) + 1) AS platform,
  element_at(array('US', 'CA', 'UK', 'AU'), CAST(id % 5000 % 4 AS INT) + 1) AS country
FROM range(200000)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {target}.subscriptions AS
SELECT
  user_id,
  start_date,
  plan,
  CASE plan WHEN 'basic' THEN 5 WHEN 'plus' THEN 10 ELSE 20 END AS mrr,
  element_at(array('ios', 'android', 'web'), CAST(user_id % 3 AS INT) + 1) AS platform
FROM (
  SELECT
    id AS user_id,
    date_add(DATE'2026-01-01', CAST(rand(3) * 90 AS INT)) AS start_date,
    element_at(array('basic', 'plus', 'premium'), CAST(rand(4) * 3 AS INT) + 1) AS plan
  FROM range(5000)
  WHERE rand(5) < 0.3
)
""")

# COMMAND ----------

metric_views = {
    "weekly_active_users": f"""
version: 1.1
comment: Weekly active users from product events
source: {target}.events
dimensions:
  - name: week
    expr: DATE_TRUNC('WEEK', event_date)
    comment: Week start (Monday)
  - name: platform
    expr: platform
  - name: country
    expr: country
measures:
  - name: active_users
    expr: COUNT(DISTINCT user_id)
    comment: Distinct users with at least one event
    synonyms: [WAU, weekly active users]
""",
    "feature_adoption": f"""
version: 1.1
comment: Feature usage from product events
source: {target}.events
dimensions:
  - name: week
    expr: DATE_TRUNC('WEEK', event_date)
    comment: Week start (Monday)
  - name: feature
    expr: feature
  - name: platform
    expr: platform
measures:
  - name: feature_users
    expr: COUNT(DISTINCT user_id)
    comment: Distinct users who used the feature
    synonyms: [adopters]
  - name: feature_events
    expr: COUNT(1)
    comment: Number of feature events
""",
    "subscription_metrics": f"""
version: 1.1
comment: New subscriptions and MRR by start month
source: {target}.subscriptions
dimensions:
  - name: start_month
    expr: DATE_TRUNC('MONTH', start_date)
    comment: Month the subscription started
  - name: plan
    expr: plan
  - name: platform
    expr: platform
measures:
  - name: new_subscriptions
    expr: COUNT(1)
    comment: Subscriptions started
  - name: mrr
    expr: SUM(mrr)
    comment: Monthly recurring revenue of new subscriptions (USD)
    synonyms: [revenue, new MRR]
""",
}

for name, body in metric_views.items():
    spark.sql(f"CREATE OR REPLACE VIEW {target}.{name} WITH METRICS LANGUAGE YAML AS $${body}$$")
