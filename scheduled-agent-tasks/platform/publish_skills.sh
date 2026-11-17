#!/usr/bin/env bash
# Publish each skills/<name>/ directory as a Unity Catalog skill and let the agents principal read it.
# Usage: ./publish_skills.sh <catalog.schema> <principal>
set -euo pipefail
schema=$1 principal=$2
cd "$(dirname "$0")"
for dir in skills/*/; do
  name=$(basename "$dir")
  path="dbfs:/Skills/${schema/.//}/$name"
  databricks ai-gateway get-skill "skills/$schema.$name" >/dev/null 2>&1 \
    || databricks ai-gateway create-skill "schemas/$schema" "$name" >/dev/null
  databricks fs mkdir "$path"
  databricks fs cp -r "$dir" "$path" --overwrite >/dev/null
  databricks ai-gateway finalize-skill "skills/$schema.$name" >/dev/null
  databricks grants update skill "$schema.$name" \
    --json "{\"changes\":[{\"principal\":\"$principal\",\"add\":[\"READ_VOLUME\"]}]}" >/dev/null
  echo "Published $schema.$name"
done
