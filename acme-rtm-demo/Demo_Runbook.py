# Databricks notebook source

# MAGIC %md
# MAGIC # Acme RTM Demo
# MAGIC ## `Kafka → Spark RTM → Lakebase → {Grafana OSS, Databricks App}`
# MAGIC
# MAGIC | Resource | Link |
# MAGIC |---|---|
# MAGIC | Grafana | `http://localhost:3000` (SSH tunnel — see Pre-flight) |
# MAGIC | Triage App | *Your app URL — see Databricks Apps in sidebar* |
# MAGIC | RTM Job | *Search "acme-rtm-job" in Workflows* |
# MAGIC | Alert Poller | *Search "acme-alert-poller" in Workflows* |
# MAGIC | EC2 (Kafka + Grafana) | *Set in `.env` as `EC2_HOST`* |

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Pre-flight Checklist
# MAGIC
# MAGIC **1. Run the pre-flight script** (from your local terminal — handles IP lock + tunnel automatically):
# MAGIC ```
# MAGIC cd ~/code/acme-rtm-demo && ./demo_preflight.sh
# MAGIC ```
# MAGIC > This checks your current IP, updates the EC2 SSH security group if needed, and opens the Grafana tunnel on localhost:3000 in one step.
# MAGIC
# MAGIC **2. Verify jobs are RUNNING** — open Workflows and confirm both jobs show an active run:
# MAGIC - `acme-rtm-job`
# MAGIC - `acme-alert-poller`
# MAGIC
# MAGIC **3. Reset the scenario** (run in EC2 terminal):
# MAGIC ```
# MAGIC ssh -i ~/.ssh/acme-rtm-demo-key.pem ubuntu@$EC2_HOST
# MAGIC python3 ~/generator/scenario.py reset
# MAGIC ```
# MAGIC
# MAGIC **4. Confirm data is flowing** — run the next cell.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Pre-flight: confirm pipeline is live (lag_ms should be < 2000)
# MAGIC SELECT
# MAGIC   count(*)                                                             AS total_rows,
# MAGIC   max(window_start)                                                    AS latest_window,
# MAGIC   ROUND(EXTRACT(EPOCH FROM (now() - max(window_start))) * 1000)        AS lag_ms
# MAGIC FROM acme_rtm_lakebase.market.quote_1s

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Beat 1 — Show the Live Feed (~3 min)
# MAGIC
# MAGIC **→ Switch to Grafana: http://localhost:3000**
# MAGIC
# MAGIC | Panel | What to say |
# MAGIC |---|---|
# MAGIC | **Ticks/sec** | "~3,100 raw quote messages per second through RTM." |
# MAGIC | **Rows in Lakebase** | "Climbing by ~12 per second — one row per symbol+venue per 1s window." |
# MAGIC | **Spread by Venue** | "Four venues quoting simultaneously. Bid-ask spread in basis points — at $78k BTC, 3 bps is a ~$23 gap." |
# MAGIC | **Acme vs Best Competitor** | "The competitive signal. Our spread vs the tightest market maker. When delta crosses 8 bps, the alert fires." |
# MAGIC | **RTM E2E Latency** | "~250ms from event generation to Lakebase write — that flat line is the RTM claim, live." |

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Live: snapshot across all venues right now
# MAGIC SELECT
# MAGIC   symbol, venue,
# MAGIC   ROUND(spread_bps, 2)   AS spread_bps,
# MAGIC   ROUND(depth_bid, 2)    AS depth_bid_btc,
# MAGIC   ROUND(depth_ask, 2)    AS depth_ask_btc,
# MAGIC   ticks,
# MAGIC   window_start
# MAGIC FROM acme_rtm_lakebase.market.quote_1s
# MAGIC WHERE window_start = (SELECT max(window_start) FROM acme_rtm_lakebase.market.quote_1s)
# MAGIC ORDER BY symbol, venue

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Live: competitive delta for BTC-USD
# MAGIC SELECT
# MAGIC   window_start,
# MAGIC   venue,
# MAGIC   ROUND(spread_bps, 2)             AS spread_bps,
# MAGIC   ROUND(best_competitor_bps, 2)    AS best_competitor_bps,
# MAGIC   ROUND(delta_bps, 2)              AS delta_bps
# MAGIC FROM acme_rtm_lakebase.market.spread_vs_best
# MAGIC WHERE symbol = 'BTC-USD'
# MAGIC   AND window_start > now() - interval '15 seconds'
# MAGIC ORDER BY window_start DESC, venue

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Beat 2 — Show the Code (~1.5 min)
# MAGIC
# MAGIC **→ Open the RTM job source in the sidebar file browser:**
# MAGIC
# MAGIC `Workspace → Users → <your-username> → .bundle → acme-rtm-demo → dev → files → rtm → rtm_job.py`
# MAGIC
# MAGIC **Key talking points:**
# MAGIC - ~40 lines — the entire streaming job
# MAGIC - `trigger(realTime="5 minutes")` is the **checkpoint interval**, not the latency target
# MAGIC - `.toTable()` writes to a Unity Catalog table backed by Lakebase
# MAGIC - No Photon, no serverless, classic compute only
# MAGIC - Grafana connects via the native `postgres` data source — no Enterprise plugin required

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Beat 3 — Trigger an Alert (~1.5 min)
# MAGIC
# MAGIC > ⚠️ **Use `widen`, NOT `drop`.**
# MAGIC > `drop` removes a venue from the feed but doesn't cross the 8 bps alert threshold.
# MAGIC
# MAGIC **Run in EC2 terminal:**
# MAGIC ```
# MAGIC python3 ~/generator/scenario.py widen --symbol=BTC-USD --bps=10
# MAGIC ```
# MAGIC
# MAGIC **Watch Grafana Panel 2** — `delta_bps` climbs above 8 bps.
# MAGIC
# MAGIC **Then switch to the Triage App** (find the URL in Databricks Apps → acme-triage-app).

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Verify the spread widened (run after triggering)
# MAGIC SELECT
# MAGIC   window_start,
# MAGIC   ROUND(spread_bps, 2)           AS acme_spread_bps,
# MAGIC   ROUND(best_competitor_bps, 2)  AS best_competitor_bps,
# MAGIC   ROUND(delta_bps, 2)            AS delta_bps
# MAGIC FROM acme_rtm_lakebase.market.spread_vs_best
# MAGIC WHERE symbol = 'BTC-USD' AND venue = 'acme'
# MAGIC   AND window_start > now() - interval '15 seconds'
# MAGIC ORDER BY window_start DESC
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Beat 4 — Triage App (~2 min)
# MAGIC
# MAGIC **→ Switch to Triage App tab**
# MAGIC
# MAGIC 1. Alert queue shows `BTC-USD / spread_widening` — click **Select**
# MAGIC 2. Diagnosis panel: spread history + last-seen timestamp per venue
# MAGIC 3. Click **Create Ticket** → returns `STUB-XXXXXX` — "real Linear API, scratch project here"
# MAGIC 4. Click **Acknowledge** → alert leaves queue

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Verify the alert was created
# MAGIC SELECT
# MAGIC   id, symbol, kind,
# MAGIC   ROUND(our_spread_bps, 2)       AS our_spread_bps,
# MAGIC   ROUND(best_competitor_bps, 2)  AS best_competitor_bps,
# MAGIC   status, linear_issue_id, raised_at
# MAGIC FROM acme_rtm_lakebase.market.alerts
# MAGIC ORDER BY raised_at DESC
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Beat 5 — The Data Layer (~1 min)
# MAGIC
# MAGIC **Talking points:**
# MAGIC
# MAGIC - Grafana uses the **native PostgreSQL data source** — no Databricks plugin, no Enterprise license
# MAGIC - Same Lakebase instance that RTM writes to is what Grafana and the App read from
# MAGIC - **CDF (Change Data Feed):** we have `REPLICA IDENTITY FULL` configured. One UI click starts replicating every upsert to Delta in Unity Catalog — full tick-by-tick audit trail. Activate in the Lakebase project UI: Branch overview → Lakebase CDF → Start.

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Reset After Demo

# COMMAND ----------

# MAGIC %md
# MAGIC Run in EC2 terminal:
# MAGIC ```
# MAGIC python3 ~/generator/scenario.py reset
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Q&A Reference
# MAGIC
# MAGIC | Question | Answer |
# MAGIC |---|---|
# MAGIC | **"What's the latency in production?"** | Documented ~300ms typical, under 1s at p99. RTM is built for sub-second market data — not micro-batch with a short interval. |
# MAGIC | **"Can this connect to our Kafka?"** | Yes — standard Kafka consumer. Swap the bootstrap server and topic name. If you have a real schema we can reshape the pipeline in a day. |
# MAGIC | **"Grafana in production — self-hosted or Cloud?"** | Either. Grafana Cloud supports the postgres data source natively. No Enterprise license needed — that's the point. |
# MAGIC | **"What about raw ticks in Delta?"** | Aggregates via CDF cover the common case. For raw ticks, we add a parallel Structured Streaming job from the same Kafka topic — one extra job alongside this one. |
# MAGIC | **"Why classic compute, not serverless?"** | RTM requires `spark.databricks.streaming.realTimeMode.enabled = true` — serverless doesn't support this flag. The sub-second latency is the payoff. |

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Live Exploration

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Latency distribution over the last 60 seconds
# MAGIC SELECT
# MAGIC   CASE
# MAGIC     WHEN write_latency_ms < 100  THEN '< 100ms'
# MAGIC     WHEN write_latency_ms < 300  THEN '100–300ms'
# MAGIC     WHEN write_latency_ms < 500  THEN '300–500ms'
# MAGIC     WHEN write_latency_ms < 1000 THEN '500ms–1s'
# MAGIC     ELSE '> 1s'
# MAGIC   END                                                      AS bucket,
# MAGIC   count(*)                                                  AS windows,
# MAGIC   ROUND(100.0 * count(*) / sum(count(*)) OVER (), 1)       AS pct
# MAGIC FROM acme_rtm_lakebase.market.quote_1s
# MAGIC WHERE write_latency_ms IS NOT NULL
# MAGIC   AND window_start > now() - interval '60 seconds'
# MAGIC GROUP BY 1
# MAGIC ORDER BY CASE
# MAGIC   WHEN bucket = '< 100ms'    THEN 1
# MAGIC   WHEN bucket = '100–300ms'  THEN 2
# MAGIC   WHEN bucket = '300–500ms'  THEN 3
# MAGIC   WHEN bucket = '500ms–1s'   THEN 4
# MAGIC   ELSE 5
# MAGIC END

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Throughput: ticks per window over the last 2 minutes
# MAGIC SELECT
# MAGIC   window_start,
# MAGIC   SUM(ticks)             AS total_ticks_per_second,
# MAGIC   COUNT(DISTINCT venue)  AS active_venues
# MAGIC FROM acme_rtm_lakebase.market.quote_1s
# MAGIC WHERE symbol = 'BTC-USD'
# MAGIC   AND window_start > now() - interval '2 minutes'
# MAGIC GROUP BY window_start
# MAGIC ORDER BY window_start DESC
# MAGIC LIMIT 20

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Full alert history
# MAGIC SELECT
# MAGIC   id, symbol, kind,
# MAGIC   ROUND(our_spread_bps, 2)       AS spread_bps,
# MAGIC   ROUND(best_competitor_bps, 2)  AS best_bps,
# MAGIC   status, linear_issue_id, raised_at
# MAGIC FROM acme_rtm_lakebase.market.alerts
# MAGIC ORDER BY raised_at DESC
