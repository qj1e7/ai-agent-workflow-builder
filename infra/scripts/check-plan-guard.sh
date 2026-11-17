#!/bin/sh
# Checks plan-guard.sh on small made-up plans, so nothing talks to Azure. check.sh runs it.
# Needs sh and jq.
# Usage: check-plan-guard.sh
set -eu

guard="$(cd "$(dirname "$0")" && pwd)/plan-guard.sh"
failures=0

# plan <address type actions...> ... prints a plan in JSON with one change for each argument, as
# "address|type|action,action".
plan() {
  printf '{"format_version":"1.2","resource_changes":['
  first=true
  for change in "$@"; do
    address=$(printf '%s' "${change%%|*}" | sed 's/"/\\"/g')
    rest=${change#*|}
    type=${rest%%|*}
    actions=$(printf '%s' "${rest#*|}" | sed 's/[a-z-][a-z-]*/"&"/g')
    $first || printf ','
    first=false
    printf '{"address":"%s","type":"%s","change":{"actions":[%s]}}' "$address" "$type" "$actions"
  done
  printf ']}\n'
}

# expect <label> <want: go or stop> <allow> <changes...>
expect() {
  label=$1
  want=$2
  allow=$3
  shift 3
  status=0
  plan "$@" | sh "$guard" "$allow" >/dev/null 2>&1 || status=$?
  got=go
  [ "$status" -ne 0 ] && got=stop
  if [ "$got" = "$want" ]; then
    echo "ok    $label: $got"
  else
    echo "FAIL  $label: wanted $want, got $got"
    failures=$((failures + 1))
  fi
}

expect "only new and changed resources" go false \
  'module.n8n_runners.azapi_resource.this|azapi_resource|create' \
  'module.app["n8n"].azurerm_container_app.this|azurerm_container_app|update'
expect "a wait replaced, as when an app reads one more secret" go false \
  'module.app["n8n"].module.identity.time_sleep.rbac_propagation|time_sleep|delete,create' \
  'module.app["n8n"].module.identity.azurerm_role_assignment.secret_reader["N8N_RUNNERS_AUTH_TOKEN"]|azurerm_role_assignment|create'
expect "a wait destroyed and not made again" stop false \
  'module.app["n8n"].module.identity.time_sleep.rbac_propagation|time_sleep|delete'
expect "an app replaced" stop false \
  'module.app["n8n"].azurerm_container_app.this|azurerm_container_app|delete,create'
expect "the vault destroyed" stop false \
  'module.key_vault.azurerm_key_vault.this|azurerm_key_vault|delete'
expect "the vault destroyed with allow_destroy ticked" go true \
  'module.key_vault.azurerm_key_vault.this|azurerm_key_vault|delete'

if [ "$failures" = 0 ]; then
  echo "check-plan-guard.sh: all cases behaved as expected"
else
  echo "check-plan-guard.sh: $failures case(s) failed"
  exit 1
fi
