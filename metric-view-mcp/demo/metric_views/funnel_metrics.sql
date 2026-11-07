CREATE OR REPLACE VIEW {catalog}.{semantic_schema}.funnel_metrics
WITH METRICS
LANGUAGE YAML
AS $$
  version: 1.1
  comment: >
    Top-of-funnel upgrade metrics: members who viewed the upgrade screen
    and members who started a paid subscription.
  source: {catalog}.{raw_schema}.app_events
  joins:
    - name: member
      source: {catalog}.{raw_schema}.dim_member
      on: source.member_id = member.member_id
  dimensions:
    - name: Event Date
      expr: event_date
      comment: "Calendar date of the funnel event"
    - name: Week
      expr: DATE_TRUNC('WEEK', event_date)
      comment: "Week (Monday start) of the funnel event"
    - name: Platform
      expr: platform
      comment: "Device platform: ios or android"
    - name: Country
      expr: country
      comment: "Member country (ISO code)"
    - name: Acquisition Channel
      expr: member.acquisition_channel
      comment: "Marketing channel that acquired the member"
  measures:
    - name: Upgrade Viewers
      expr: COUNT(DISTINCT member_id) FILTER (WHERE event_name = 'upgrade_viewed')
      comment: "Distinct members who viewed the upgrade screen"
    - name: Subscribers Started
      expr: COUNT(DISTINCT member_id) FILTER (WHERE event_name = 'subscription_started')
      comment: "Distinct members who started a paid subscription"
    - name: Upgrade Conversion Rate
      expr: >
        COUNT(DISTINCT member_id) FILTER (WHERE event_name = 'subscription_started')
        / COUNT(DISTINCT member_id) FILTER (WHERE event_name = 'upgrade_viewed')
      comment: "Subscribers Started / Upgrade Viewers"
$$
