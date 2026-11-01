#!/bin/sh
# Decides whether this deploy may open n8n's editor to the internet (ADR 0034). Until n8n has an
# owner, its setup page lets the first visitor become the owner. The bootstrap job creates the
# owner, but only after the full apply. So n8n may open only once a bootstrap execution has
# succeeded in this resource group, and on a new environment it stays internal for one deploy.
# Prints true or false. When it holds n8n back, it says why on stderr and in the run summary.
# Any az error stops the deploy instead, so a failed check never closes an open editor.
# Needs an az CLI that is signed in. check-n8n-editor-gate.sh tests it with a fake az.
# Usage: n8n-editor-gate.sh <requested: true or false> <resource-group> [job-name]
set -eu

requested=$1
group=$2
job=${3:-bootstrap}

case $requested in
  true) ;;
  false)
    echo false
    exit 0
    ;;
  *)
    echo "N8N_EDITOR_EXTERNAL must be true or false, not '$requested'." >&2
    exit 1
    ;;
esac

# az prints one number. Anything else, or an error, stops the deploy.
count() {
  value=$(az "$@" --output tsv)
  case $value in
    '' | *[!0-9]*)
      echo "n8n-editor-gate: expected a count from az $1 $2 $3, got '$value'." >&2
      return 1
      ;;
  esac
  echo "$value"
}

jobs=$(count containerapp job list --resource-group "$group" --query "[?name=='$job'] | length(@)")
succeeded=0
if [ "$jobs" -gt 0 ]; then
  succeeded=$(count containerapp job execution list --resource-group "$group" --name "$job" \
    --query "[?properties.status=='Succeeded'] | length(@)")
fi

if [ "$succeeded" -gt 0 ]; then
  echo true
  exit 0
fi

note="n8n stays internal until the first bootstrap has created its owner. Run the deploy again to open the editor."
echo "$note" >&2
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  printf '## n8n editor\n\n%s\n\n' "$note" >>"$GITHUB_STEP_SUMMARY"
fi
echo false
