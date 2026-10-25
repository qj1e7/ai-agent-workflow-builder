#!/usr/bin/env bash
# PROTOTYPE 2, throwaway. Runs two saved agent cards with the AI model saved in the local Portal.
# Usage: agent-runtime/prototypes/agent_cards/run_cards.sh
# Needs the local stack running (scripts/up.sh) with an AI model connected in Settings.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/out"
mkdir -p "$out"

COPYFILE_DISABLE=1 tar --no-mac-metadata -C "$here" -cf - cards.py runner.py run_cards.py saved_cards.json tasks.json |
  docker exec -i wab-platform-api-1 sh -c 'rm -rf /tmp/agent-cards-proto && mkdir -p /tmp/agent-cards-proto && tar -C /tmp/agent-cards-proto -xf -'

docker exec wab-platform-api-1 python /tmp/agent-cards-proto/run_cards.py > "$out/card-runs.json"
python3 "$here/render_runs.py" "$out/card-runs.json" "$out/card-runs.html"
echo "Open $out/card-runs.html"
