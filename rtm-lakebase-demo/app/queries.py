import psycopg2
import psycopg2.extras
from config import LAKEBASE_HOST, LAKEBASE_DB, LAKEBASE_PASSWORD, LAKEBASE_WRITER_PASSWORD

_read = (
    f"host={LAKEBASE_HOST} "
    f"dbname={LAKEBASE_DB} "
    f"user=grafana_reader "
    f"password={LAKEBASE_PASSWORD} "
    f"sslmode=require"
)
_write = (
    f"host={LAKEBASE_HOST} "
    f"dbname={LAKEBASE_DB} "
    f"user=rtm_writer "
    f"password={LAKEBASE_WRITER_PASSWORD} "
    f"sslmode=require"
)

def _rconn(): return psycopg2.connect(_read)
def _wconn(): return psycopg2.connect(_write)

def _row(r):
    d = dict(r)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif type(v).__name__ == "Decimal":
            d[k] = float(v)
    return d

def get_alert(alert_id: int):
    with _rconn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, symbol, venue FROM market.alerts WHERE id = %s", (alert_id,))
        r = cur.fetchone()
        return _row(r) if r else None

def open_alerts():
    with _rconn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, raised_at, symbol, venue, kind,
                   our_spread_bps, best_competitor_bps, detail, linear_issue_id
            FROM market.alerts WHERE status='open'
            ORDER BY raised_at DESC
        """)
        return [_row(r) for r in cur.fetchall()]

def alert_diagnosis(symbol: str, venue: str):
    with _rconn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT spread_bps, best_competitor_bps, delta_bps, window_start
            FROM market.spread_vs_best
            WHERE symbol = %s AND venue = %s
              AND window_start > now() - interval '5 minutes'
            ORDER BY window_start DESC
            LIMIT 15
        """, (symbol, venue))
        return [_row(r) for r in cur.fetchall()]

def last_seen_per_venue(symbol: str):
    with _rconn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT venue,
                   max(window_start) AS last_seen,
                   ROUND(EXTRACT(EPOCH FROM (now() - max(window_start)))::numeric, 1) AS seconds_ago
            FROM market.quote_1s WHERE symbol = %s
            GROUP BY venue ORDER BY venue
        """, (symbol,))
        return [_row(r) for r in cur.fetchall()]

def acknowledge(alert_id: int):
    with _wconn() as c, c.cursor() as cur:
        cur.execute("UPDATE market.alerts SET status='acknowledged' WHERE id=%s", (alert_id,))

def write_linear_id(alert_id: int, issue_id: str):
    with _wconn() as c, c.cursor() as cur:
        cur.execute("UPDATE market.alerts SET linear_issue_id=%s WHERE id=%s", (issue_id, alert_id))
