---
agent: claude-sonnet
tags:                                   # cost tags: job tags, gateway request tags, and MLflow trace tags
  team: data-platform
  cost_center: finops
mcps:                                   # Unity Gateway MCP services, and the tools this task may call
  system.ai.dbsql: [execute_sql, poll_sql_result]
skills: [databricks-billing]            # names without a catalog resolve to the platform schema
schedule:
  quartz_cron_expression: "0 0 8 ? * MON"
  timezone_id: America/Los_Angeles
  pause_status: PAUSED
---
Review this account's Databricks spend in `system.billing.usage`, following the `databricks-billing` skill.

1. Total estimated list cost for the current week vs. the prior week, with both date ranges.
2. The single largest cost driver (workspace_id + sku_name) and its week-over-week change.
3. Any SKU or product (billing_origin_product) whose spend grew more than 25% week over week.
4. Reply with a short summary: total spend, top driver, notable growth, and one recommended action.

Run the skill's query with the `dbsql` MCP tool `execute_sql` (poll with `poll_sql_result` if pending).
Do not use a shell or CLI. Only run SELECT queries.
