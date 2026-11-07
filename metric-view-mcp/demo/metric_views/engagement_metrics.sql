CREATE OR REPLACE VIEW {catalog}.{semantic_schema}.engagement_metrics
WITH METRICS
LANGUAGE YAML
AS $$
  version: 1.1
  comment: >
    Official app engagement metrics. Group by Week for WAU,
    by Event Date for DAU, by Month for MAU.
  source: {catalog}.{raw_schema}.app_events
  dimensions:
    - name: Event Date
      expr: event_date
      comment: "Calendar date of the app event"
    - name: Week
      expr: DATE_TRUNC('WEEK', event_date)
      comment: "Week (Monday start) of the app event"
    - name: Month
      expr: DATE_TRUNC('MONTH', event_date)
      comment: "Calendar month of the app event"
    - name: Platform
      expr: platform
      comment: "Device platform: ios or android"
    - name: Country
      expr: country
      comment: "Member country (ISO code)"
    - name: Event Name
      expr: event_name
      comment: "app_open, place_alert_created, crash_detection_enabled, upgrade_viewed, subscription_started"
  measures:
    - name: Active Users
      expr: COUNT(DISTINCT member_id)
      comment: "Distinct members with any event. By Week = WAU, by Event Date = DAU, by Month = MAU."
    - name: Active Circles
      expr: COUNT(DISTINCT circle_id)
      comment: "Distinct circles with any member activity"
    - name: Events
      expr: COUNT(1)
      comment: "Total app events"
    - name: Events per Active User
      expr: COUNT(1) / COUNT(DISTINCT member_id)
      comment: "Average events per active member"
$$
