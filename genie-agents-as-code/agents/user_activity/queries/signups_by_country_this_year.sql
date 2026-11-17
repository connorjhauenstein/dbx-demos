/*
question: Signups by country this year
usage_guidance: Use for current-year signup breakdowns by country
*/
SELECT country, COUNT(*) AS signups FROM {schema}.users WHERE YEAR(signup_date) = YEAR(current_date()) GROUP BY country
