#!/bin/sh
# Checks, from outside n8n's address list, that each path where a published n8n workflow answers
# is refused (ADR 0051, ADR 0034). n8n loads every built-in block, so a Webhook, a Form, a Wait or
# an MCP Server Trigger a member published answers anyone who reaches n8n, and Container Apps'
# address list is the only guard on Azure. With n8n internal there is no public address, so
# nothing is checked. Prints one line a path, and fails on any path that answers anything but
# "RBAC: access denied".
# Needs curl. check-n8n-paths-closed.sh tests it with a fake curl.
# Usage: n8n-paths-closed.sh <n8n's editor URL, or empty while n8n is internal>
set -eu

base=${1:-}
if [ -z "$base" ]; then
  echo "n8n is internal, so it has no public path to check."
  exit 0
fi
base=${base%/}

# A made-up id under each path. The address list refuses the request before n8n reads it.
paths="webhook webhook-test webhook-waiting form form-test form-waiting mcp mcp-test"
body=$(mktemp)
trap 'rm -f "$body"' EXIT
open=0
for path in $paths; do
  status=$(curl --silent --show-error --max-time 20 --output "$body" --write-out '%{http_code}' \
    "$base/$path/wab-check-0000" 2>/dev/null) || status=unreachable
  if [ "$status" = 403 ] && grep -q "RBAC: access denied" "$body"; then
    echo "closed: /$path answers 403 RBAC: access denied"
  else
    echo "OPEN:   /$path answers $status" >&2
    open=$((open + 1))
  fi
done

if [ "$open" -ne 0 ]; then
  echo "$open of n8n's public paths answer from outside its address list. Set N8N_EDITOR_ALLOWED_IPS, or keep N8N_EDITOR_EXTERNAL false." >&2
  exit 1
fi
echo "Every public path of n8n refuses this address."
