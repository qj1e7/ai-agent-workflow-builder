#!/usr/bin/env bash
# Saves every layout the platform writes as n8n's editor does, with n8n's own code, and writes
# what each save changed to editor_save.txt. Needs uv and the n8nio/n8n image. Rerun it when n8n
# or a layout changes, and keep PARAMETER_FILLS in platform-api's builder/versions.py in step.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
image="${N8N_IMAGE:-n8nio/n8n:2.42.6}"

(cd "$root/platform-api" && uv run python "$here/layouts.py") |
  docker run --rm -i --entrypoint node -e NODE_PATH=/usr/local/lib/node_modules/n8n/node_modules \
    -v "$here/editor_save.js:/editor_save.js:ro" -v "$root/n8n-node-pack/src:/pack:ro" \
    "$image" /editor_save.js >"$here/editor_save.txt"
cat "$here/editor_save.txt"
