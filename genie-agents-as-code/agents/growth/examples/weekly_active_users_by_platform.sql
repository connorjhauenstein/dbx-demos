-- question: Weekly active users by platform for the last 4 weeks
SELECT week, platform, MEASURE(active_users) AS weekly_active_users
FROM {schema}.weekly_active_users
WHERE week >= DATE_TRUNC('WEEK', current_date()) - INTERVAL 4 WEEKS
GROUP BY ALL
ORDER BY week, platform
