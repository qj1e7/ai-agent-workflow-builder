#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [ ! -f deploy/.env ]; then
  deploy/make-env.sh
fi

docker compose -p wab -f deploy/compose.yaml up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}"

port=$(grep -E '^PLATFORM_API_HOST_PORT=' deploy/.env | cut -d= -f2)
n8n_port=$(grep -E '^N8N_HOST_PORT=' deploy/.env | cut -d= -f2)
echo
echo "platform-api: http://localhost:${port:-8000}/docs"
echo "n8n:          http://localhost:${n8n_port:-5678}"
echo "Stop it with: scripts/down.sh"
