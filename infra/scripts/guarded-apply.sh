#!/bin/sh
# Plans, checks the plan with plan-guard.sh, then applies exactly that plan. Each terraform command
# prints only its summary line (terraform-quiet.sh). When GITHUB_STEP_SUMMARY is set, the plan's
# counts also go to the run summary. ALLOW_DESTROY=true lets a plan destroy or replace resources.
# Run it from the environment's folder, such as infra/envs/dev.
# Usage: guarded-apply.sh <name> [terraform plan arguments, such as -target=module.registry]
set -eu

name=$1
shift
scripts=$(cd "$(dirname "$0")" && pwd)

counts=$("$scripts/terraform-quiet.sh" "plan-$name.txt" plan -out="$name.tfplan" "$@")
echo "$counts"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  printf '## Terraform plan: %s\n\n%s\n\n' "$name" "$counts" >>"$GITHUB_STEP_SUMMARY"
fi

plan_json=$(terraform show -json "$name.tfplan")
printf '%s\n' "$plan_json" | "$scripts/plan-guard.sh" "${ALLOW_DESTROY:-false}"

"$scripts/terraform-quiet.sh" "apply-$name.txt" apply "$name.tfplan"
