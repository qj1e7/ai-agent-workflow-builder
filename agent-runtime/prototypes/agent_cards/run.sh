#!/usr/bin/env bash
# PROTOTYPE, throwaway. Drafts agent cards with the AI model saved in the local Portal.
# Usage: agent-runtime/prototypes/agent_cards/run.sh ["a task of your own" ...]
# Needs the local stack running (scripts/up.sh) with an AI model connected in Settings.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/out"
mkdir -p "$out"

COPYFILE_DISABLE=1 tar --no-mac-metadata -C "$here" -cf - cards.py runner.py tasks.json |
  docker exec -i wab-platform-api-1 sh -c 'rm -rf /tmp/agent-cards-proto && mkdir -p /tmp/agent-cards-proto && tar -C /tmp/agent-cards-proto -xf -'

args=()
for task in "$@"; do args+=(--try "$task"); done
docker exec wab-platform-api-1 python /tmp/agent-cards-proto/runner.py /tmp/agent-cards-proto/tasks.json \
  ${args[@]+"${args[@]}"} > "$out/results.json"

python3 "$here/render.py" "$out/results.json" "$out/agent-cards.html"
echo "Open $out/agent-cards.html"
