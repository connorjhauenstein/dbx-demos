/*
# Configure > Examples > Queries. The file name is yours; the question is the example's title.
question: What was revenue since a given date?
usage_guidance: Use for revenue over a date range   # Usage Guidance
parameters:                                          # Parameters
  - keyword: start_date                              # Keyword (use as :start_date in the SQL)
    type: DATE                                       # Data type: STRING, INTEGER, DECIMAL, DATE, DATETIME (API also: DOUBLE, BOOLEAN)
    default: "2026-01-01"
    comment: First day to include                    # Comment
*/
SELECT MEASURE(revenue) AS revenue
FROM {schema}.my_metric_view
WHERE order_date >= :start_date
