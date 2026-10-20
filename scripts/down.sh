#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

docker compose -p wab -f deploy/compose.yaml -f deploy/compose.e2e.yaml --profile e2e down -v --remove-orphans
