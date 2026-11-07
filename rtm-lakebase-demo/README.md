# RTM to Lakebase Demo

End-to-end real-time market data pipeline: `Kafka → Spark RTM → Lakebase → {Grafana OSS, Databricks App}`

## Architecture

```
[Tick Generator] → [Kafka] → [Spark RTM] → [Lakebase (Postgres)]
                                                 ↓              ↓
                                           [Grafana OSS]  [Triage App]
                                            (observe)       (act)
```

| Layer | Component | Notes |
|---|---|---|
| **Ingest** | Apache Kafka (KRaft) | Single broker on EC2, Docker |
| **Processing** | Spark RTM (`realTimeMode.enabled=true`) | Classic compute, DBR 18.x, ~300ms e2e latency |
| **Store** | Lakebase (Provisioned Postgres) | Native Postgres wire protocol |
| **Observe** | Grafana OSS | Native `postgres` datasource, no Enterprise plugin |
| **Act** | Databricks App (FastAPI + React) | 2s polling, alert triage + ticketing |

## Prerequisites

- Databricks workspace with Unity Catalog and Lakebase
- AWS EC2 instance (same region as workspace) — `t3.medium` or larger
- Databricks CLI ≥ 0.229.0
- AWS CLI with a configured profile

## Setup

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your values — see comments in the file
```

### 2. Provision EC2

```bash
# Bootstrap: install Docker, docker-compose
scp -i ~/.ssh/<your-key>.pem deploy/ec2_bootstrap.sh ubuntu@<EC2_HOST>:~
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> 'bash ec2_bootstrap.sh'

# Copy Kafka and Grafana configs
scp -i ~/.ssh/<your-key>.pem -r kafka ubuntu@<EC2_HOST>:~/kafka
scp -i ~/.ssh/<your-key>.pem -r grafana ubuntu@<EC2_HOST>:~/grafana
scp -i ~/.ssh/<your-key>.pem -r generator ubuntu@<EC2_HOST>:~/generator

# Install tick generator Python deps
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  'pip3 install -r ~/generator/requirements.txt'

# Start Kafka (EC2_HOST must be set in env or .env on the instance)
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  'cd ~/kafka && EC2_HOST=<EC2_HOST> docker-compose up -d'

# Create the Kafka topic
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  'docker exec kafka_kafka_1 /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --create --topic md.quotes.normalized \
    --partitions 3 --replication-factor 1'

# Add hairpin NAT fix so the tick generator can reach Kafka via the public hostname
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  "echo '127.0.0.1 <EC2_HOST>' | sudo tee -a /etc/hosts"

# Start Grafana
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  'cd ~/grafana && LAKEBASE_HOST=<LAKEBASE_HOST> LAKEBASE_PASSWORD=<LAKEBASE_PASSWORD> docker-compose up -d'
```

### 3. Provision Lakebase

```bash
python3 deploy/lakebase_provision.py --profile <your-profile> --instance rtm-lakebase-demo
# Prints LAKEBASE_HOST and LAKEBASE_ENDPOINT — add these to .env
```

### 4. Apply Lakebase schema

```bash
source .env
PGPASSWORD=$LAKEBASE_PASSWORD psql "host=$LAKEBASE_HOST dbname=$LAKEBASE_DB user=$LAKEBASE_ADMIN_EMAIL sslmode=require" \
  -f lakebase/01_schema.sql
PGPASSWORD=$LAKEBASE_PASSWORD psql "host=$LAKEBASE_HOST dbname=$LAKEBASE_DB user=$LAKEBASE_ADMIN_EMAIL sslmode=require" \
  -f lakebase/02_roles.sql
```

### 5. Deploy Databricks jobs and app

```bash
databricks bundle deploy \
  --var ec2_host=$EC2_HOST \
  --var lakebase_endpoint=$LAKEBASE_ENDPOINT \
  --var lakebase_host=$LAKEBASE_HOST \
  --var lakebase_password=$LAKEBASE_PASSWORD \
  --var lakebase_writer_password=$LAKEBASE_WRITER_PASSWORD \
  --profile <your-profile>

databricks bundle run rtm-job --profile <your-profile>
databricks bundle run rtm-alert-poller --profile <your-profile>
```

### 6. Start tick generator (EC2)

The generator runs as a systemd service. Install the unit file on EC2:

```bash
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_HOST> \
  'sudo cp ~/generator/tick-generator.service /etc/systemd/system/ && \
   sudo systemctl daemon-reload && \
   sudo systemctl enable --now tick-generator'
```

## Running the demo

### Day-of pre-flight

```bash
./demo_preflight.sh
```

Opens the Grafana SSH tunnel, checks your IP against the EC2 security group and updates it if needed, and verifies the tick generator is running.

Then open [Demo_Runbook](Demo_Runbook.py) in the Databricks workspace and run the pre-flight SQL cell — `lag_ms` should be below 2000.

### Demo narrative

**Beat 1 — Live feed (~3 min)**  
Grafana → Market Monitor. Walk through the four panels: Ticks/sec, Spread by Venue, Primary Venue vs Best Competitor, RTM E2E Latency.

**Beat 2 — Show the code (~1.5 min)**  
Open `rtm/rtm_job.py` in the workspace. ~40 lines. `trigger(realTime="5 minutes")` is the checkpoint interval, not the latency target.

**Beat 3 — Trigger an alert (~1.5 min)**  
```bash
# On EC2
python3 ~/generator/scenario.py widen --symbol=BTC-USD --bps=10
```
Watch `delta_bps` climb in Grafana Panel 2. Alert fires within ~5s in the Triage App.

> **Use `widen`, NOT `drop`.** `drop` removes a venue but doesn't cross the alert threshold.

**Beat 4 — Triage App (~2 min)**  
Select the alert → diagnosis panel → Create Ticket → Acknowledge.

**Beat 5 — Lakebase data layer (~1 min)**  
Grafana uses the native Postgres datasource — no Enterprise plugin. REPLICA IDENTITY FULL is configured; CDF replicates every upsert to Delta in Unity Catalog.

**Reset:**
```bash
python3 ~/generator/scenario.py reset
```

## Key talking points

| Question | Answer |
|---|---|
| **Latency?** | ~300ms typical, <1s at p99. RTM is not micro-batch with a short interval — it upserts continuously. |
| **Why classic compute?** | `spark.databricks.streaming.realTimeMode.enabled` requires classic compute. The sub-second latency is the payoff. |
| **Grafana without Enterprise?** | Native `postgres` datasource. No Databricks plugin required. |
| **Raw ticks in Delta?** | Add a parallel Structured Streaming job from the same Kafka topic — one extra job alongside this one. Or enable Lakebase CDF: every upsert replicated as change records. |
| **Production Kafka?** | Swap the bootstrap server and topic name. If you have a real schema, the pipeline reshapes in a day. |
