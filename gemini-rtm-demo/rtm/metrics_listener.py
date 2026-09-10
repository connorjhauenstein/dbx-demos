import os, time, json as json_lib, psycopg2
from pyspark.sql.streaming import StreamingQueryListener

_conn_str = (
    f"host={os.environ['LAKEBASE_HOST']} "
    f"dbname={os.environ['LAKEBASE_DB']} "
    f"user=rtm_writer "
    f"password={os.environ['LAKEBASE_WRITER_PASSWORD']} "
    f"sslmode=require"
)

class MetricsListener(StreamingQueryListener):
    def onQueryStarted(self, event): pass
    def onQueryTerminated(self, event): pass

    def onQueryProgress(self, event):
        p = json_lib.loads(event.progress.json())
        e2e = p.get("e2eLatencyMs", {})
        with psycopg2.connect(_conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO market.stream_metrics
                      (batch_id, e2e_latency_p99_ms, e2e_latency_p50_ms,
                       input_rows_per_sec, num_input_rows)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (batch_id) DO NOTHING
                """, (
                    p.get("batchId") or int(time.time() * 1000),
                    e2e.get("p99"),
                    e2e.get("p50"),
                    p.get("inputRowsPerSecond"),
                    p.get("numInputRows"),
                ))
