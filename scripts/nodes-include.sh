#!/usr/bin/env bash
# Writes n8n's allow list, NODES_INCLUDE, into deploy/compose.yaml and infra/envs/dev/main.tf from
# the class file (ADR 0045): every type the file does not turn off, in the file's order.
#   scripts/nodes-include.sh          writes both
#   scripts/nodes-include.sh --check  changes nothing, and fails when either differs from the file
#   scripts/nodes-include.sh --print  prints the list, as scripts/pack-smoke.sh gives it to n8n
# Needs jq.
set -euo pipefail
cd "$(dirname "$0")/.."

classes=platform-api/src/platform_api/orchestration/node_classes.json
compose=deploy/compose.yaml
terraform=infra/envs/dev/main.tf
on='to_entries[] | select(.value.off == null) | .key'
listed=$(jq -c "[$on]" "$classes")
check=false
case "${1:-}" in
  "") ;;
  --check) check=true ;;
  --print) echo "$listed"; exit 0 ;;
  *) echo "usage: scripts/nodes-include.sh [--check | --print]" >&2; exit 2 ;;
esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# One line in compose, as n8n reads it: a JSON list.
awk -v line="      NODES_INCLUDE: '$listed'" '
  /^ *NODES_INCLUDE:/ { print line; found = 1; next }
  { print }
  END { if (!found) exit 3 }
' "$compose" >"$work/compose.yaml" || { echo "$compose has no NODES_INCLUDE line." >&2; exit 1; }

# One quoted type a line in Terraform's local.n8n_nodes_include, which the n8n app's env encodes.
jq -r "$on" "$classes" | sed 's/.*/    "&",/' >"$work/types.tf"
awk -v types="$work/types.tf" '
  /^ *n8n_nodes_include = \[$/ { print; while ((getline t < types) > 0) print t; skip = 1; found = 1; next }
  skip && /^ *\]$/ { skip = 0 }
  !skip { print }
  END { if (!found) exit 3 }
' "$terraform" >"$work/main.tf" || { echo "$terraform has no n8n_nodes_include list." >&2; exit 1; }

status=0
for pair in "$compose:$work/compose.yaml" "$terraform:$work/main.tf"; do
  file=${pair%%:*}
  made=${pair#*:}
  if cmp -s "$file" "$made"; then
    continue
  fi
  if $check; then
    diff -u "$file" "$made" >&2 || true
    echo "$file does not hold the allow list in $classes. Run scripts/nodes-include.sh and commit." >&2
    status=1
  else
    cp "$made" "$file"
    echo "wrote NODES_INCLUDE into $file"
  fi
done
if [ "$status" = 0 ]; then
  echo "NODES_INCLUDE in $compose and $terraform matches $classes: $(jq length <<<"$listed") types."
fi
exit "$status"
