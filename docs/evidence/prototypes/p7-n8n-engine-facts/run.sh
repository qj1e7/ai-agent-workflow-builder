#!/usr/bin/env bash
# Runs the P7 spike: boots the stack, runs every question, and leaves raw output in raw/.
# Usage: ./run.sh [q01 q02 ...]   (no names runs them all)   ./run.sh down   (removes containers and volumes)
set -euo pipefail
cd "$(dirname "$0")"
dc() { docker compose -f compose.yaml --project-name wab-e2e-p7 --env-file p7.env "$@"; }

if [[ "${1:-}" == "down" ]]; then dc down -v --remove-orphans; exit 0; fi

if [[ ! -f p7.env ]]; then
  {
    echo "P7_DB_PASSWORD=$(openssl rand -hex 16)"
    echo "P7_ENCRYPTION_KEY=$(openssl rand -hex 24)"
    echo "P7_NODE_KEY=$(openssl rand -hex 32)"
    echo "P7_START_SECRET=$(openssl rand -hex 32)"
  } > p7.env
fi

dc up -d --wait
[[ -f p7-secrets.json ]] || python3 setup.py
# q16 and the q11 variants need n8n restarted with other settings: python3 variants.py. q99 runs an hour after the last restart.
for q in ${@:-q01 q02 q03 q04 q05 q06 q07 q08 q10 q11 q12 q13 q17}; do
  echo "== $q"
  python3 "$q"_*.py || echo "$q stopped with an error"
done
