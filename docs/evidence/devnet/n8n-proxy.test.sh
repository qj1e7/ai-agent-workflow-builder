#!/usr/bin/env bash
# Issue #86, items 2 and 3, checked without starting the stack. For deploy/compose.yaml alone, and with
# deploy/compose.lockdown.yaml over it, it reads n8n's settings from docker compose config and starts one
# throwaway n8n container from them, with SQLite, no network at all, and a proxy that never answers:
#   - n8n starts and makes no call of its own to api.n8n.io (its list of MCP servers);
#   - n8n's health check, as compose runs it, passes.
# Needs Docker and the pinned n8n image on this machine. It pulls nothing and removes its container.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
work="$(mktemp -d)"
name="n8n-proxy-test-$$"
proxy=http://egress-proxy:3128
failures=0

cleanup() {
  docker rm -fv "$name" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

ok() { echo "ok    $1"; }
bad() {
  echo "FAIL  $1"
  failures=$((failures + 1))
}

# compose needs every secret set before it renders. Their values do not matter here.
sed 's/^\([A-Z0-9_]*\)=$/\1=unused/' "$root/deploy/.env.example" >"$work/compose.env"

check() {
  local label=$1 file waited
  shift
  local files=()
  for file in "$@"; do files+=(-f "$root/deploy/$file"); done
  docker compose "${files[@]}" --env-file "$work/compose.env" config --format json | jq '.services.n8n' >"$work/n8n.json"

  # n8n's own settings, with SQLite in place of PostgreSQL, and a proxy wherever compose sets none.
  jq -r --arg p "$proxy" '
    {HTTP_PROXY: $p, HTTPS_PROXY: $p, http_proxy: $p, https_proxy: $p,
     NO_PROXY: "localhost,127.0.0.1", no_proxy: "localhost,127.0.0.1"} + .environment
    | to_entries[] | select(.key | startswith("DB_") | not) | "\(.key)=\(.value)"' "$work/n8n.json" >"$work/n8n.env"
  local health
  health=$(jq -r 'if .healthcheck.test[0] == "CMD-SHELL" then .healthcheck.test[1] else "echo n8n health check is not CMD-SHELL; exit 1" end' "$work/n8n.json")

  docker run -d --pull never --name "$name" --network none --env-file "$work/n8n.env" "$(jq -r .image "$work/n8n.json")" >/dev/null
  waited=0
  until docker logs "$name" 2>&1 | grep -q 'Editor is now accessible'; do
    if [ "$waited" -ge 120 ] || [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
      bad "$label: n8n did not start"
      docker logs "$name" 2>&1 | tail -n 20
      docker rm -fv "$name" >/dev/null
      return
    fi
    sleep 1
    waited=$((waited + 1))
  done

  # n8n asks for the list as soon as it starts, so 20 seconds of quiet means it did not ask.
  local asked=""
  for _ in $(seq 20); do
    if docker logs "$name" 2>&1 | grep -q 'api\.n8n\.io'; then
      asked=1
      break
    fi
    sleep 1
  done
  if [ -z "$asked" ]; then
    ok "$label: n8n starts and makes no call of its own to api.n8n.io"
  else
    bad "$label: n8n called api.n8n.io on its own:" && docker logs "$name" 2>&1 | grep 'api\.n8n\.io'
  fi

  if docker exec "$name" sh -c "$health" >"$work/health.out" 2>&1; then
    ok "$label: the health check passes with a proxy set ($health)"
  else
    bad "$label: the health check fails with a proxy set ($health):" && cat "$work/health.out"
  fi
  docker rm -fv "$name" >/dev/null
}

check "compose.yaml" compose.yaml
check "compose.yaml + compose.lockdown.yaml" compose.yaml compose.lockdown.yaml

if [ "$failures" = 0 ]; then
  echo "n8n-proxy.test.sh: all checks passed"
else
  echo "n8n-proxy.test.sh: $failures check(s) failed"
  exit 1
fi
