/*
question: Signups by fiscal quarter
*/
SELECT {schema}.fiscal_quarter(signup_date) AS fiscal_quarter, COUNT(*) AS signups
FROM {schema}.users
GROUP BY ALL
ORDER BY fiscal_quarter
