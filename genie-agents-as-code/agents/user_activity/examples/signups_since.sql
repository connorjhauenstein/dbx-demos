/*
question: How many users signed up since a given date?
usage: Use for signup counts over a date range
parameters:
  - name: start_date
    type: DATE
    default: "2025-12-01"
    description: First signup date to count
*/
SELECT COUNT(*) AS signups
FROM {schema}.users
WHERE signup_date >= :start_date
