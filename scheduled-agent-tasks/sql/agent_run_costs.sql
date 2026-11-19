-- Estimated list cost per agent run: one row per job run, with the run's tags.
--   job_compute_usd: serverless job compute, billed per job run. Exact.
--   model_usd:       model usage is billed per hour, model, and caller. It's split across that hour's calls by tokens,
--                    using the Unity Gateway request tags that run_task.py adds to every call.
--   sql_usd:         the SQL warehouse behind the DBSQL MCP. Each hour of warehouse cost (idle time included) is split
--                    across that hour's queries by duration, and the agent's queries are matched to the run by the run's
--                    service principal and time window. For an exact figure, give agents their own warehouse.
--   status:          "pending" until billing covers the run. Billing tables lag by a few hours.
-- List prices, not discounted.
WITH priced AS (
  SELECT u.*, u.usage_quantity * p.pricing.default AS usd
  FROM system.billing.usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.usage_unit = p.usage_unit AND p.currency_code = 'USD'
   AND u.usage_start_time >= p.price_start_time
   AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  WHERE u.usage_date >= current_date() - INTERVAL 30 DAYS
),
billed_until AS (
  SELECT max(usage_end_time) AS t FROM system.billing.usage WHERE usage_date >= current_date() - INTERVAL 2 DAYS
),
calls AS (
  SELECT event_time, date_trunc('HOUR', event_time) AS hour, service_type, destination_model AS model, requester AS caller,
         request_tags, total_tokens,
         SUM(total_tokens) OVER (PARTITION BY service_type, date_trunc('HOUR', event_time), destination_model, requester) AS hour_tokens
  FROM system.ai_gateway.usage
  WHERE event_time >= current_date() - INTERVAL 30 DAYS
),
runs AS (
  SELECT request_tags['job_run_id'] AS job_run_id, any_value(request_tags) AS tags, any_value(caller) AS caller,
         min(event_time) AS started, max(event_time) AS ended
  FROM calls
  WHERE request_tags['job_run_id'] IS NOT NULL
  GROUP BY 1
),
model AS (
  SELECT c.request_tags['job_run_id'] AS job_run_id, SUM(c.total_tokens) AS model_tokens, SUM(b.usd * c.total_tokens / c.hour_tokens) AS model_usd
  FROM calls c
  LEFT JOIN (
    SELECT date_trunc('HOUR', usage_start_time) AS hour, usage_metadata.ai_gateway.destination_model AS model,
           identity_metadata.run_by AS caller, SUM(usd) AS usd
    FROM priced
    WHERE billing_origin_product = 'MODEL_SERVING' AND usage_metadata.ai_gateway.destination_model IS NOT NULL
    GROUP BY ALL
  ) b USING (hour, model, caller)
  WHERE c.service_type = 'MODEL_SERVICE' AND c.request_tags['job_run_id'] IS NOT NULL
  GROUP BY 1
),
job_compute AS (
  SELECT usage_metadata.job_run_id AS job_run_id, SUM(usd) AS job_compute_usd
  FROM priced
  WHERE billing_origin_product = 'JOBS' AND usage_metadata.job_run_id IS NOT NULL
  GROUP BY 1
),
queries AS (
  SELECT compute.warehouse_id AS warehouse_id, executed_by, client_application, start_time,
         date_trunc('HOUR', start_time) AS hour, total_duration_ms,
         SUM(total_duration_ms) OVER (PARTITION BY compute.warehouse_id, date_trunc('HOUR', start_time)) AS hour_ms
  FROM system.query.history
  WHERE start_time >= current_date() - INTERVAL 30 DAYS AND compute.warehouse_id IS NOT NULL
),
sql AS (
  SELECT r.job_run_id, SUM(w.usd * q.total_duration_ms / q.hour_ms) AS sql_usd
  FROM runs r
  JOIN queries q
    ON q.executed_by = r.caller AND q.client_application = 'Databricks SQL MCP'
   AND q.start_time BETWEEN r.started - INTERVAL 1 MINUTE AND r.ended + INTERVAL 1 MINUTE
  LEFT JOIN (
    SELECT usage_metadata.warehouse_id AS warehouse_id, date_trunc('HOUR', usage_start_time) AS hour, SUM(usd) AS usd
    FROM priced
    WHERE billing_origin_product = 'SQL' AND usage_metadata.warehouse_id IS NOT NULL
    GROUP BY ALL
  ) w USING (warehouse_id, hour)
  GROUP BY 1
)
SELECT
  r.job_run_id,
  r.tags['task'] AS task,
  r.tags['harness'] AS harness,
  r.tags['model'] AS model,
  r.started,
  m.model_tokens,
  ROUND(j.job_compute_usd, 4) AS job_compute_usd,
  ROUND(m.model_usd, 4) AS model_usd,
  ROUND(s.sql_usd, 4) AS sql_usd,
  CASE WHEN r.ended <= (SELECT t FROM billed_until)
       THEN ROUND(coalesce(j.job_compute_usd, 0) + coalesce(m.model_usd, 0) + coalesce(s.sql_usd, 0), 4) END AS total_usd,
  CASE WHEN r.ended > (SELECT t FROM billed_until) THEN 'pending' ELSE 'billed' END AS status,
  r.tags
FROM runs r
LEFT JOIN model m USING (job_run_id)
LEFT JOIN job_compute j USING (job_run_id)
LEFT JOIN sql s USING (job_run_id)
ORDER BY r.started DESC;
