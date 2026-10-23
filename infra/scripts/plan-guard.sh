#!/bin/sh
# Reads a saved plan as JSON on stdin and refuses it when it would destroy or replace anything,
# unless the first argument is true. No second person approves each deploy, so this stops a
# mistaken change from deleting the database or the vault. It prints only counts, because the
# plan names every resource.
# Usage: terraform show -json <plan-file> | plan-guard.sh <allow-destroy: true or false>
set -eu

allow=${1:-false}

counts=$(jq -r '
  if .format_version == null then error("plan-guard: stdin is not a Terraform plan in JSON") else . end
  | [.resource_changes[]?.change.actions]
  | [
      (map(select(. == ["create"])) | length),
      (map(select(. == ["update"])) | length),
      (map(select(. == ["delete"])) | length),
      (map(select(any(.[]; . == "delete") and any(.[]; . == "create"))) | length)
    ]
  | @tsv')
if [ -z "$counts" ]; then
  echo "plan-guard: no plan on stdin" >&2
  exit 1
fi
read -r add change destroy replace <<EOF
$counts
EOF

echo "The plan would add $add, change $change, destroy $destroy and replace $replace resources."
removed=$((destroy + replace))
if [ "$removed" -eq 0 ]; then
  exit 0
fi
if [ "$allow" = true ]; then
  echo "allow_destroy is on, so the deploy goes ahead."
  exit 0
fi
echo "Stopped before apply: the plan would destroy or replace $removed resources. If that is intended, run the deploy again with allow_destroy ticked." >&2
exit 1
