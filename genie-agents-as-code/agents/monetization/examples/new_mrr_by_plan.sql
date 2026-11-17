-- question: New MRR by plan per month
SELECT start_month, plan, MEASURE(mrr) AS new_mrr
FROM {schema}.subscription_metrics
GROUP BY ALL
ORDER BY start_month, plan
