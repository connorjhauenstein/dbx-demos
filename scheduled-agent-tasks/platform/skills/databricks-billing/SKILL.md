---
name: databricks-billing
description: How to compute and compare Databricks spend from billing tables (system.billing.usage and list prices). Use for any cost, spend, DBU, or week-over-week billing question.
---

# Databricks billing

## Tables
- `system.billing.usage`: one row per usage record. Key columns: `usage_date`, `workspace_id`, `sku_name`,
  `billing_origin_product`, `usage_unit`, `usage_quantity`.
- `system.billing.list_prices`: `sku_name`, `usage_unit`, `currency_code`, `price_start_time`, `price_end_time`, `pricing.default`.
- Some teams keep a pre-aggregated copy with a `list_cost_usd` column. If a task names such a table, use `list_cost_usd` directly.

## Estimated list cost
Join usage to the price that was valid on the usage date:

```sql
SELECT u.*, u.usage_quantity * p.pricing.default AS list_cost_usd
FROM system.billing.usage u
JOIN system.billing.list_prices p
  ON u.sku_name = p.sku_name AND u.usage_unit = p.usage_unit AND p.currency_code = 'USD'
 AND u.usage_date >= CAST(p.price_start_time AS DATE)
 AND (p.price_end_time IS NULL OR u.usage_date < CAST(p.price_end_time AS DATE))
```
This is list price. It doesn't reflect discounts or commitments, so say "estimated list cost".

## Comparing weeks
- Anchor windows to the data, not the clock: the current week is the 7 days ending the day before the latest `usage_date`
  (the latest day may be incomplete), and the prior week is the 7 days before that. State both date ranges.
- Compute totals, the top `workspace_id` + `sku_name`, and growth by `sku_name` and `billing_origin_product` from the same window.
- Report growth only where the prior week had spend; call out new SKUs separately.
