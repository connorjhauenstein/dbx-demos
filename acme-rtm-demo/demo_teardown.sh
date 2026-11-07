#!/usr/bin/env bash
# Shut down all running demo resources to stop incurring cost.
# Lakebase is always-on (Provisioned tier) — nothing to stop there.
#
# Usage: ./demo_teardown.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

DB_PROFILE="${DATABRICKS_PROFILE:?DATABRICKS_PROFILE not set — check .env}"
AWS_PROFILE="${AWS_PROFILE:?AWS_PROFILE not set — check .env}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EC2_INSTANCE_ID="${EC2_INSTANCE_ID:?EC2_INSTANCE_ID not set — check .env}"
RTM_JOB_ID="${RTM_JOB_ID:?RTM_JOB_ID not set — check .env}"
POLLER_JOB_ID="${POLLER_JOB_ID:?POLLER_JOB_ID not set — check .env}"

echo "=== Acme RTM Demo Teardown ==="

# ---- 1. Cancel Databricks job runs ----
echo ""
echo "[1/3] Stopping Databricks jobs..."

for JOB_ID in $RTM_JOB_ID $POLLER_JOB_ID; do
  RUN_ID=$(databricks jobs list-runs --job-id "$JOB_ID" \
    --profile "$DB_PROFILE" --output json 2>/dev/null | \
    python3 -c "
import sys,json
data=json.load(sys.stdin)
runs=data if isinstance(data,list) else data.get('runs',[])
active=[r for r in runs if r['state']['life_cycle_state'] in ('RUNNING','PENDING')]
print(active[0]['run_id'] if active else '')
" 2>/dev/null)

  if [[ -n "$RUN_ID" ]]; then
    databricks jobs cancel-run "$RUN_ID" --profile "$DB_PROFILE" --no-wait 2>/dev/null || true
    echo "      Job $JOB_ID — cancelled run $RUN_ID"
  else
    echo "      Job $JOB_ID — no active run"
  fi
done

# ---- 2. Close SSH tunnel ----
echo ""
echo "[2/3] Closing Grafana SSH tunnel..."
lsof -ti tcp:3000 | xargs kill -9 2>/dev/null && echo "      Tunnel closed." || echo "      No tunnel open."

# ---- 3. Stop EC2 instance ----
echo ""
echo "[3/3] Stopping EC2 instance..."
aws ec2 stop-instances \
  --instance-ids "$EC2_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --output text --query "StoppingInstances[0].CurrentState.Name" 2>&1
echo "      EC2 stopping — Elastic IP stays assigned, hostname unchanged."

echo ""
echo "=== Teardown complete ==="
echo ""
echo "Cost still running: Lakebase (Provisioned, always-on)."
echo "To restart:         ./demo_preflight.sh  (handles EC2 start + tunnel + IP check)"
