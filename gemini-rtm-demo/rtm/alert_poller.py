import os, sys, time, psycopg2

try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import inspect
    _script_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0, os.path.dirname(_script_dir))  # repo root — for config.py

import config as cfg

conn = psycopg2.connect(
    host=cfg.LAKEBASE_HOST,
    dbname=cfg.LAKEBASE_DB,
    user="rtm_writer",
    password=cfg.LAKEBASE_WRITER_PASSWORD,
    sslmode="require",
)
conn.autocommit = True

INSERT_SQL = """
INSERT INTO market.alerts (symbol, venue, kind, our_spread_bps, best_competitor_bps, detail)
SELECT symbol, venue, 'spread_widening', spread_bps, best_competitor_bps,
       jsonb_build_object('delta_bps', delta_bps, 'window_start', window_start)
FROM market.spread_vs_best
WHERE venue = 'gemini'
  AND delta_bps > %(threshold)s
  AND window_start > now() - interval '5 seconds'
  AND NOT EXISTS (
    SELECT 1 FROM market.alerts a
    WHERE a.symbol = spread_vs_best.symbol
      AND a.status = 'open'
      AND a.kind = 'spread_widening'
  )
"""

while True:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {"threshold": cfg.ALERT_THRESHOLD_BPS})
    time.sleep(2)
