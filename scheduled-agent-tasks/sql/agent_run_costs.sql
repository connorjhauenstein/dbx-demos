-- Estimated list cost per agent run: one row per job run, with the run's tags.
--   compute_usd: serverless job compute, billed per job run.
--   model_usd:   model usage is billed per hour, model, and caller. It's split across that hour's calls by tokens,
--                using the Unity Gateway request tags that run_task.py adds to every call.
-- List prices, not discounted. Billing and usage tables can lag by a few hours.
WITH priced AS (
  SELECT u.*, u.usage_quantity * p.pricing.default AS usd
  FROM system.billing.usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.usage_unit = p.usage_unit AND p.currency_code = 'USD'
   AND u.usage_start_time >= p.price_start_time
   AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  WHERE u.usage_date >= current_date() - INTERVAL 30 DAYS
),
compute AS (
  SELECT usage_metadata.job_run_id AS job_run_id, SUM(usd) AS compute_usd
  FROM priced
  WHERE billing_origin_product = 'JOBS' AND usage_metadata.job_run_id IS NOT NULL
  GROUP BY 1
),
model_billed AS (
  SELECT date_trunc('HOUR', usage_start_time) AS hour, usage_metadata.ai_gateway.destination_model AS model,
         identity_metadata.run_by AS caller, SUM(usd) AS usd
  FROM priced
  WHERE billing_origin_product = 'MODEL_SERVING' AND usage_metadata.ai_gateway.destination_model IS NOT NULL
  GROUP BY ALL
),
calls AS (
  SELECT date_trunc('HOUR', event_time) AS hour, destination_model AS model, requester AS caller,
         request_tags, total_tokens,
         SUM(total_tokens) OVER (PARTITION BY date_trunc('HOUR', event_time), destination_model, requester) AS hour_tokens
  FROM system.ai_gateway.usage
  WHERE service_type = 'MODEL_SERVICE' AND event_time >= current_date() - INTERVAL 30 DAYS
)
SELECT
  c.request_tags['job_run_id'] AS job_run_id,
  c.request_tags['task'] AS task,
  c.request_tags['harness'] AS harness,
  c.request_tags['model'] AS model,
  any_value(c.request_tags) AS tags,
  SUM(c.total_tokens) AS model_tokens,
  ROUND(SUM(b.usd * c.total_tokens / c.hour_tokens), 4) AS model_usd,
  ROUND(any_value(j.compute_usd), 4) AS compute_usd
FROM calls c
LEFT JOIN model_billed b USING (hour, model, caller)
LEFT JOIN compute j ON j.job_run_id = c.request_tags['job_run_id']
WHERE c.request_tags['job_run_id'] IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY job_run_id DESC;
