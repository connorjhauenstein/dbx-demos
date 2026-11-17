Review Databricks spend for the last 7 complete days using `system.billing.usage` joined to `system.billing.list_prices`
(estimated list cost = usage_quantity * pricing.default, matched on sku_name, usage_unit, and the price's valid time range).

1. Define the current week as the 7 days ending the day before the latest `usage_date` in the table (the latest day may be incomplete),
   and the prior week as the 7 days before that. State both date ranges. Total spend for each week and the change.
2. The single largest cost driver (workspace_id + sku_name) and its week-over-week change.
3. Any SKU or product (billing_origin_product) whose spend grew more than 25% week over week.
4. Reply with a short summary: total spend, top driver, notable growth, and one recommended action.

Run queries with the `dbsql` MCP tool `execute_sql` (poll with `poll_sql_result` if pending). Do not use a shell or CLI.
Use fully qualified table names. Only run SELECT queries.
