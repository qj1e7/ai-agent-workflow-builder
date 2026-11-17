#!/bin/sh
# Reads a saved plan as JSON on stdin and refuses it when it would destroy or replace anything,
# unless the first argument is true. No second person approves each deploy, so this stops a
# mistaken change from deleting the database or the vault. It prints counts, and when it refuses,
# the addresses of the resources it would destroy or replace, so a person can decide whether to
# allow it. Addresses are names from the public Terraform code; no value of the plan is printed.
# A wait (time_sleep) holds nothing, and modules/workload_identity replaces its wait whenever an
# identity gains a role, as when an app reads one more Key Vault secret. So replacing a wait is
# counted as a change, never as a removal.
# Usage: terraform show -json <plan-file> | plan-guard.sh <allow-destroy: true or false>
set -eu

allow=${1:-false}
plan=$(cat)

counts=$(printf '%s\n' "$plan" | jq -r '
  if .format_version == null then error("plan-guard: stdin is not a Terraform plan in JSON") else . end
  | [.resource_changes[]? | {wait: (.type == "time_sleep"), actions: .change.actions}]
  | [
      (map(select(.actions == ["create"])) | length),
      (map(select(.actions == ["update"] or (.wait and any(.actions[]; . == "delete") and any(.actions[]; . == "create")))) | length),
      (map(select(.actions == ["delete"])) | length),
      (map(select((.wait | not) and any(.actions[]; . == "delete") and any(.actions[]; . == "create"))) | length)
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
printf '%s\n' "$plan" | jq -r '
  .resource_changes[]?
  | select(any(.change.actions[]; . == "delete"))
  | select(.type != "time_sleep" or (any(.change.actions[]; . == "create") | not))
  | "  \(if any(.change.actions[]; . == "create") then "replace" else "destroy" end): \(.address)"' >&2
exit 1
