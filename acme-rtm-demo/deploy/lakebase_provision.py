"""
Provision a Lakebase Provisioned-tier instance and print the env vars needed for .env.

Usage:
    python3 deploy/lakebase_provision.py --profile <databricks-cli-profile> --instance <name>

Example:
    python3 deploy/lakebase_provision.py --profile my-profile --instance acme-rtm-demo
"""

import argparse
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--profile", required=True, help="Databricks CLI profile")
parser.add_argument("--instance", default="acme-rtm-demo", help="Lakebase instance name")
args = parser.parse_args()

PROFILE = args.profile
INSTANCE = args.instance


def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


run(
    f"databricks database create-database-instance {INSTANCE} "
    f"--capacity=CU_1 --enable-pg-native-login --no-wait -p {PROFILE}"
)

print("Waiting for AVAILABLE state...")
while True:
    state = run(
        f"databricks database get-database-instance {INSTANCE} -p {PROFILE} "
        f'| python3 -c "import json,sys; print(json.load(sys.stdin).get(\'state\',\'\'))"'
    )
    if state == "AVAILABLE":
        break
    time.sleep(30)

host = run(
    f"databricks database get-database-instance {INSTANCE} -p {PROFILE} "
    f'| python3 -c "import json,sys; print(json.load(sys.stdin)[\'read_write_dns\'])"'
)

print("\nAdd these to your .env:")
print(f"LAKEBASE_ENDPOINT={INSTANCE}")
print(f"LAKEBASE_HOST={host}")
