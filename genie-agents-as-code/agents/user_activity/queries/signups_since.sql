/*
question: How many users signed up since a given date?
usage_guidance: Use for signup counts over a date range
parameters:
  - keyword: start_date
    type: DATE
    default: "2025-12-01"
    comment: First signup date to count
*/
SELECT COUNT(*) AS signups
FROM {schema}.users
WHERE signup_date >= :start_date
