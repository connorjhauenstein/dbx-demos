"""
Configuration — single source of truth for all environment variables.

To run locally:
    cp .env.example .env    # fill in your values
    python3 <script>        # config.py loads .env automatically

In deployed contexts (Databricks jobs, EC2 systemd) environment variables are
injected directly — .env is not used and python-dotenv is not required.

Required variables raise a clear error if missing.
Optional variables fall back to the documented default.
"""

import os
from pathlib import Path

def _load_dotenv(path: Path) -> None:
    """Load a .env file without external dependencies. No-op if file is absent."""
    if path.exists():
        for line in path.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())

_load_dotenv(Path(__file__).parent / ".env")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(
            f"Required environment variable {name!r} is not set.\n"
            f"Copy .env.example to .env and fill in your values."
        )
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ── EC2 ───────────────────────────────────────────────────────────────────────
EC2_HOST    = _optional("EC2_HOST")      # public DNS of the EC2 instance
EC2_SG_ID   = _optional("EC2_SG_ID")    # security group ID (used by demo_preflight.sh)
AWS_PROFILE = _optional("AWS_PROFILE")  # AWS CLI profile name

# ── Kafka ──────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP = _require("KAFKA_BOOTSTRAP")                          # host:port
KAFKA_TOPIC     = _optional("KAFKA_TOPIC", "md.quotes.normalized")

# ── Lakebase ──────────────────────────────────────────────────────────────────
LAKEBASE_ENDPOINT = _optional("LAKEBASE_ENDPOINT")   # Provisioned instance name
LAKEBASE_HOST     = _require("LAKEBASE_HOST")         # ep-xxxx.databricks.com
LAKEBASE_DB       = _optional("LAKEBASE_DB", "databricks_postgres")
LAKEBASE_PASSWORD = _require("LAKEBASE_PASSWORD")           # grafana_reader role
LAKEBASE_WRITER_PASSWORD = _require("LAKEBASE_WRITER_PASSWORD")  # rtm_writer role

# ── Databricks ────────────────────────────────────────────────────────────────
UC_CATALOG = _optional("UC_CATALOG", "my_catalog")
UC_SCHEMA  = _optional("UC_SCHEMA",  "rtm_demo")

# ── Spark / RTM ───────────────────────────────────────────────────────────────
# Defaults to the UC Volume path derived from UC_CATALOG/UC_SCHEMA.
# Databricks job overrides this via spark_env_vars in databricks.yml.
CHECKPOINT_LOCATION = _optional(
    "CHECKPOINT_LOCATION",
    f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/checkpoints/rtm4",
)

# ── Generator ─────────────────────────────────────────────────────────────────
GEN_RATE_PER_SYMBOL = int(_optional("GEN_RATE_PER_SYMBOL", "500"))  # ticks/sec per symbol per venue

# ── Alerting ──────────────────────────────────────────────────────────────────
ALERT_THRESHOLD_BPS = float(_optional("ALERT_THRESHOLD_BPS", "8"))  # fire when delta_bps exceeds this

# ── Linear (optional) ─────────────────────────────────────────────────────────
LINEAR_API_KEY = _optional("LINEAR_API_KEY")  # leave blank to use stub mode (returns STUB-XXXXXX)
LINEAR_TEAM_ID = _optional("LINEAR_TEAM_ID")
