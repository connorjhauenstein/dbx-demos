-- Template: {catalog}, {raw_schema}, {semantic_schema} are substituted by setup_demo.py.
-- Synthetic mobile-app activity (demo only).
-- raw schema: source tables the MCP must NOT be able to reach.
-- semantic schema: metric views the MCP exposes, plus one plain table it must ignore.
CREATE SCHEMA IF NOT EXISTS {catalog}.{raw_schema}
  COMMENT 'Raw synthetic app events. Not exposed through the metric-view MCP.';

CREATE SCHEMA IF NOT EXISTS {catalog}.{semantic_schema}
  COMMENT 'Governed semantic layer: metric views exposed through the metric-view MCP.';

CREATE OR REPLACE TABLE {catalog}.{raw_schema}.dim_member AS
SELECT
  id AS member_id,
  DATE_ADD(DATE'2024-01-01', CAST(id % 640 AS INT)) AS signup_date,
  element_at(array('US','US','US','CA','GB','AU'), CAST(id % 6 AS INT) + 1) AS country,
  element_at(array('organic','paid_social','paid_search','partner'), CAST(id % 4 AS INT) + 1) AS acquisition_channel,
  IF(id % 5 < 3, 'ios', 'android') AS device_os
FROM range(1, 50001);

CREATE OR REPLACE TABLE {catalog}.{raw_schema}.app_events AS
WITH base AS (
  SELECT
    id AS event_id,
    CAST(1 + abs(hash(id, 'member')) % 50000 AS BIGINT) AS member_id,
    DATE_ADD(DATE'2026-05-01', CAST(abs(hash(id, 'day')) % 180 AS INT)) AS event_date,
    abs(hash(id, 'event')) % 100 AS r
  FROM range(0, 2000000)
)
SELECT
  b.event_id,
  b.member_id,
  CAST(b.member_id % 15000 AS BIGINT) AS circle_id,
  b.event_date,
  CASE
    WHEN b.r < 60 THEN 'app_open'
    WHEN b.r < 75 THEN 'place_alert_created'
    WHEN b.r < 85 THEN 'crash_detection_enabled'
    WHEN b.r < 97 THEN 'upgrade_viewed'
    ELSE 'subscription_started'
  END AS event_name,
  m.device_os AS platform,
  m.country
FROM base b JOIN {catalog}.{raw_schema}.dim_member m USING (member_id);

-- A plain table in the semantic schema: the MCP must not list or query it,
-- because it only exposes objects whose type is METRIC_VIEW.
CREATE OR REPLACE TABLE {catalog}.{semantic_schema}.scratch_notes AS
SELECT 'not a metric view' AS note;
