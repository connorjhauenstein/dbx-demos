CREATE SCHEMA IF NOT EXISTS market;

CREATE TABLE IF NOT EXISTS market.quote_1s (
  symbol        text        NOT NULL,
  venue         text        NOT NULL,
  window_start  timestamptz NOT NULL,
  bid           double precision,
  ask           double precision,
  spread_bps    double precision,
  depth_bid     double precision,
  depth_ask     double precision,
  ticks         integer,
  last_event_ts timestamptz,
  last_kafka_ts timestamptz,
  updated_at    timestamptz DEFAULT now(),
  PRIMARY KEY (symbol, venue, window_start)
);

CREATE OR REPLACE FUNCTION market.refresh_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS quote_1s_updated_at ON market.quote_1s;
CREATE TRIGGER quote_1s_updated_at
  BEFORE UPDATE ON market.quote_1s
  FOR EACH ROW EXECUTE FUNCTION market.refresh_updated_at();

CREATE INDEX IF NOT EXISTS quote_1s_window_idx
  ON market.quote_1s (window_start DESC);

CREATE OR REPLACE VIEW market.spread_vs_best AS
SELECT
  symbol,
  window_start,
  venue,
  spread_bps,
  MIN(spread_bps) FILTER (WHERE venue <> 'gemini')
    OVER (PARTITION BY symbol, window_start) AS best_competitor_bps,
  spread_bps - MIN(spread_bps) FILTER (WHERE venue <> 'gemini')
    OVER (PARTITION BY symbol, window_start) AS delta_bps
FROM market.quote_1s;

CREATE TABLE IF NOT EXISTS market.stream_metrics (
  batch_id            bigint      PRIMARY KEY,
  observed_at         timestamptz NOT NULL DEFAULT now(),
  e2e_latency_p99_ms  double precision,
  e2e_latency_p50_ms  double precision,
  input_rows_per_sec  double precision,
  num_input_rows      bigint
);

CREATE TABLE IF NOT EXISTS market.alerts (
  id                  bigserial   PRIMARY KEY,
  raised_at           timestamptz NOT NULL DEFAULT now(),
  symbol              text        NOT NULL,
  venue               text        NOT NULL,
  kind                text        NOT NULL,
  our_spread_bps      double precision,
  best_competitor_bps double precision,
  detail              jsonb,
  status              text        NOT NULL DEFAULT 'open',
  linear_issue_id     text
);
