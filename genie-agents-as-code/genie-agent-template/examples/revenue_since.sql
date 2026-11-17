/*
question: What was revenue since a given date?
usage: Use for revenue over a date range
parameters:
  - name: start_date
    type: DATE        # STRING, INTEGER, DECIMAL, DOUBLE, BOOLEAN, DATE, or DATETIME
    default: "2026-01-01"
    description: First day to include
*/
SELECT MEASURE(revenue) AS revenue
FROM {schema}.my_metric_view
WHERE order_date >= :start_date
