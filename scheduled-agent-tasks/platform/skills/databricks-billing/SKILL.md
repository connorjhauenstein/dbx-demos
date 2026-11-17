---
name: databricks-billing
description: Compute and compare Databricks spend week over week from billing data (system.billing.usage or a pre-aggregated copy with list_cost_usd), in one query. Use for any cost, spend, DBU, or week-over-week billing question.
---

# Databricks billing: week-over-week spend

Answer with **one query**: the query below returns everything a week-over-week review needs. Don't explore schemas or
list tables first, and don't split the analysis across many queries. Run a follow-up query only if the result
raises a question the summary can't answer, such as which workspace drives a growing SKU.

## 1. Pick the `costs` source

Use exactly one of these as the first CTE. Both produce one row per usage record with an estimated list `cost`.

From `system.billing.usage`, priced with the list price valid on the usage date:
```sql
WITH costs AS (
  SELECT u.usage_date, u.workspace_id, u.sku_name, u.billing_origin_product, u.usage_quantity * p.pricing.default AS cost
  FROM system.billing.usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.usage_unit = p.usage_unit AND p.currency_code = 'USD'
   AND u.usage_date >= CAST(p.price_start_time AS DATE)
   AND (p.price_end_time IS NULL OR u.usage_date < CAST(p.price_end_time AS DATE))
  WHERE u.usage_date >= current_date() - 21
),
```

From a pre-aggregated table that already has `list_cost_usd` (the task names it):
```sql
WITH costs AS (
  SELECT usage_date, workspace_id, sku_name, billing_origin_product, list_cost_usd AS cost
  FROM <catalog>.<schema>.<table>
),
```

## 2. Append this and run it

The current week is the 7 days ending the day before the latest `usage_date`, because the latest day may be incomplete.
The prior week is the 7 days before that.

```sql
weekly AS (
  SELECT c.*, w.current_to,
         CASE WHEN usage_date > w.current_to - 7 THEN 'current' ELSE 'prior' END AS week
  FROM costs c CROSS JOIN (SELECT max(usage_date) - 1 AS current_to FROM costs) w
  WHERE usage_date BETWEEN w.current_to - 13 AND w.current_to
),
summary AS (
  SELECT
    CASE WHEN grouping(workspace_id) = 0 THEN 'workspace_sku' WHEN grouping(sku_name) = 0 THEN 'sku'
         WHEN grouping(billing_origin_product) = 0 THEN 'product' ELSE 'total' END AS level,
    workspace_id, sku_name, billing_origin_product,
    max(current_to) - 6 AS current_from, max(current_to) AS current_to,
    ROUND(SUM(cost) FILTER (WHERE week = 'current'), 2) AS current_week,
    ROUND(SUM(cost) FILTER (WHERE week = 'prior'), 2) AS prior_week
  FROM weekly
  GROUP BY GROUPING SETS ((), (workspace_id, sku_name), (sku_name), (billing_origin_product))
)
SELECT *, ROUND(100 * (try_divide(current_week, prior_week) - 1), 1) AS change_pct
FROM summary
QUALIFY level IN ('total', 'product')
     OR (level = 'workspace_sku' AND row_number() OVER (PARTITION BY level ORDER BY current_week DESC NULLS LAST) <= 5)
     OR (level = 'sku' AND (prior_week > 0 AND current_week > 1.25 * prior_week OR prior_week IS NULL))
ORDER BY CASE level WHEN 'total' THEN 0 WHEN 'workspace_sku' THEN 1 WHEN 'product' THEN 2 ELSE 3 END, current_week DESC NULLS LAST
```

Result rows, by `level`:
- `total`: both weeks' spend and `change_pct`, with `current_from` and `current_to`.
- `workspace_sku`: the 5 largest `workspace_id` + `sku_name` pairs this week. The first row is the top cost driver.
- `product`: every `billing_origin_product`.
- `sku`: SKUs that grew more than 25% week over week, and new SKUs (`prior_week` is null).

## 3. Report

- State both date ranges, and say "estimated list cost": list prices don't reflect discounts or commitments.
- Report growth only where the prior week had spend. Call out new SKUs separately.
- Keep it short: total and change, top driver and its change, notable growth, one recommended action.
