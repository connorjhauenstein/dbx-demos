#!/usr/bin/env bash
# Demo pre-flight: starts EC2, fixes SSH IP lock, starts Databricks jobs if needed,
# and opens the Grafana tunnel. Run from the repo root on demo morning.
#
# Usage: ./demo_preflight.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

EC2_HOST="${EC2_HOST:?EC2_HOST not set — check .env}"
EC2_INSTANCE_ID="${EC2_INSTANCE_ID:?EC2_INSTANCE_ID not set — check .env}"
SG_ID="${EC2_SG_ID:?EC2_SG_ID not set — check .env}"
AWS_PROFILE="${AWS_PROFILE:?AWS_PROFILE not set — check .env}"
AWS_REGION="${AWS_REGION:-us-east-1}"
KEY="${EC2_KEY_PATH:-$HOME/.ssh/rtm-lakebase-demo-key.pem}"
DB_PROFILE="${DATABRICKS_PROFILE:?DATABRICKS_PROFILE not set — check .env}"
RTM_JOB_ID="${RTM_JOB_ID:?RTM_JOB_ID not set — check .env}"
POLLER_JOB_ID="${POLLER_JOB_ID:?POLLER_JOB_ID not set — check .env}"

echo "=== RTM to Lakebase Demo Pre-flight ==="

# ---- 1. Start EC2 if stopped ----
echo ""
echo "[1/4] Checking EC2 instance..."
EC2_STATE=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --instance-ids "$EC2_INSTANCE_ID" \
  --query "Reservations[0].Instances[0].State.Name" \
  --profile "$AWS_PROFILE" \
  --output text 2>/dev/null)
echo "      State: $EC2_STATE"

if [[ "$EC2_STATE" == "stopped" ]]; then
  echo "      Starting EC2..."
  aws ec2 start-instances --instance-ids "$EC2_INSTANCE_ID" \
    --region "$AWS_REGION" --profile "$AWS_PROFILE" --output text \
    --query "StartingInstances[0].CurrentState.Name" 2>/dev/null
  echo "      Waiting for running state (~30s)..."
  aws ec2 wait instance-running \
    --instance-ids "$EC2_INSTANCE_ID" \
    --region "$AWS_REGION" --profile "$AWS_PROFILE"
  echo "      EC2 running."
elif [[ "$EC2_STATE" != "running" ]]; then
  echo "      ⚠ Unexpected state: $EC2_STATE. Check AWS console."
  exit 1
fi

# ---- 2. Fix SSH IP lock ----
echo ""
echo "[2/4] Checking SSH access..."
MY_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org)
echo "      Your current IP: $MY_IP"

CURRENT_CIDR=$(aws ec2 describe-security-groups \
  --region "$AWS_REGION" --group-ids "$SG_ID" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`22\`].IpRanges[0].CidrIp" \
  --profile "$AWS_PROFILE" --output text 2>/dev/null || echo "unknown")

if [[ "$CURRENT_CIDR" == "${MY_IP}/32" ]]; then
  echo "      SSH rule already set to your IP."
else
  echo "      Updating SSH rule: $CURRENT_CIDR → ${MY_IP}/32"
  if [[ "$CURRENT_CIDR" != "unknown" && "$CURRENT_CIDR" != "None" ]]; then
    aws ec2 revoke-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
      --protocol tcp --port 22 --cidr "$CURRENT_CIDR" --profile "$AWS_PROFILE" >/dev/null
  fi
  aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "${MY_IP}/32" --profile "$AWS_PROFILE" >/dev/null
  echo "      Done — SSH open to $MY_IP"
fi

# Wait for SSH to be ready (needed if EC2 just started)
echo "      Waiting for SSH..."
for i in $(seq 1 12); do
  ssh -i "$KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
    ubuntu@"$EC2_HOST" 'echo ok' 2>/dev/null | grep -q ok && break
  sleep 5
done

ssh -i "$KEY" -o ConnectTimeout=6 -o StrictHostKeyChecking=no -o BatchMode=yes \
  ubuntu@"$EC2_HOST" 'echo ok' 2>/dev/null | grep -q ok || { echo "⚠ Cannot reach EC2."; exit 1; }
echo "      EC2 reachable."

# Ensure Kafka topic exists and tick-generator is running
ssh -i "$KEY" -o StrictHostKeyChecking=no ubuntu@"$EC2_HOST" '
  # Recreate Kafka topic if missing (after instance stop/start Kafka data is lost)
  docker exec kafka_kafka_1 /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --list 2>/dev/null | grep -q "md.quotes" || \
  docker exec kafka_kafka_1 /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --create --topic md.quotes.normalized \
    --partitions 3 --replication-factor 1 2>/dev/null
  # Start tick-generator if not running
  pgrep -f tick_generator >/dev/null 2>&1 || sudo systemctl start tick-generator
  echo "      Kafka topic: ok  |  Tick generator: ok"
' 2>/dev/null

# ---- 3. Start Databricks jobs if not running ----
echo ""
echo "[3/4] Checking Databricks jobs..."
for JOB_ID in $RTM_JOB_ID $POLLER_JOB_ID; do
  JOB_NAME=$(databricks jobs get "$JOB_ID" --profile "$DB_PROFILE" --output json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['settings']['name'])" 2>/dev/null || echo "job-$JOB_ID")
  IS_RUNNING=$(databricks jobs list-runs --job-id "$JOB_ID" \
    --profile "$DB_PROFILE" --output json 2>/dev/null | \
    python3 -c "
import sys,json
data=json.load(sys.stdin)
runs=data if isinstance(data,list) else data.get('runs',[])
active=[r for r in runs if r['state']['life_cycle_state'] in ('RUNNING','PENDING')]
print('yes' if active else 'no')
" 2>/dev/null)

  if [[ "$IS_RUNNING" == "yes" ]]; then
    echo "      $JOB_NAME: already running"
  else
    databricks jobs run-now "$JOB_ID" --no-wait --profile "$DB_PROFILE" >/dev/null 2>&1
    echo "      $JOB_NAME: started"
    # New run needs a clean checkpoint if Kafka was reset
    if [[ "$JOB_ID" == "$RTM_JOB_ID" && "$EC2_STATE" == "stopped" ]]; then
      echo "      (EC2 was stopped — clearing stale RTM checkpoint to avoid offset errors)"
      databricks fs rm -r "dbfs:/Volumes/${UC_CATALOG:-my_catalog}/${UC_SCHEMA:-rtm_demo}/checkpoints/rtm4" \
        --profile "$DB_PROFILE" 2>/dev/null || true
      databricks jobs run-now "$JOB_ID" --no-wait --profile "$DB_PROFILE" >/dev/null 2>&1
    fi
  fi
done

# ---- 4. Open Grafana SSH tunnel ----
echo ""
echo "[4/4] Opening Grafana SSH tunnel on localhost:3000..."
lsof -ti tcp:3000 | xargs kill -9 2>/dev/null || true
sleep 1

ssh -i "$KEY" -N -f \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=5 \
  -L 3000:localhost:3000 ubuntu@"$EC2_HOST"

sleep 1
if lsof -ti tcp:3000 >/dev/null 2>&1; then
  echo "      Tunnel open — Grafana: http://localhost:3000"
else
  echo "      ⚠ Tunnel failed. Try: ssh -i $KEY -N -L 3000:localhost:3000 ubuntu@$EC2_HOST"
fi

echo ""
echo "=== Pre-flight complete ==="
echo ""
echo "  Grafana:    http://localhost:3000  (admin / admin)"
echo "  Triage app: Databricks Apps → rtm-triage-app"
echo ""
echo "  Run the pre-flight SQL cell in Demo_Runbook — lag_ms should be < 5000"
echo "  (allow ~5 min for clusters to start if jobs were just launched)"
