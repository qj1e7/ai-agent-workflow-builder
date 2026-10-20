#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [ ! -f deploy/.env ]; then
  deploy/make-env.sh
fi

docker compose -p wab -f deploy/compose.yaml up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}"

env_value() {
  if [ -n "${!1-}" ]; then echo "${!1}"; else grep -E "^$1=" deploy/.env | cut -d= -f2 || true; fi
}

portal_port=$(env_value PORTAL_HOST_PORT)
port=$(env_value PLATFORM_API_HOST_PORT)
n8n_port=$(env_value N8N_HOST_PORT)
echo
echo "Portal:       http://localhost:${portal_port:-8080}"
echo "platform-api: http://localhost:${port:-8000}/docs"
echo "n8n:          http://localhost:${n8n_port:-5678}"
echo "Stop it with: scripts/down.sh"
