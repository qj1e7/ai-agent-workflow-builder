#!/usr/bin/env bash
# The lock-down test from docs/design/devnet-move.md. Starts the stack with deploy/compose.lockdown.yaml,
# probes the way out from inside, runs a Software watchlist check to Done, and saves what happened
# in docs/evidence/devnet/out/. Needs Docker and the internet (for the proxy and the image builds).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$root"
here=docs/evidence/devnet
out="$here/out"
project="${LOCKDOWN_PROJECT:-wab-lockdown}"
compose=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.lockdown.yaml)
mkdir -p "$out"

if [ ! -f deploy/.env ]; then
  deploy/make-env.sh
fi

# The proxy logs a tunnel when it closes, and the agent runtime keeps its GitHub connection open,
# so the callers stop first and the proxy's log is read after them.
stop() {
  "${compose[@]}" logs --no-color >"$out/compose.log" 2>&1 || true
  "${compose[@]}" stop agent-runtime platform-api n8n >/dev/null 2>&1 || true
  "${compose[@]}" exec -T egress-proxy cat /var/log/squid/access.log >"$out/proxy-access.log" 2>&1 || true
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: stack left running. Stop it with: ${compose[*]} down -v"
  else
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap stop EXIT

echo "Starting the locked stack as compose project $project."
"${compose[@]}" up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}" >"$out/up.log" 2>&1

# The proxy's log names each caller by its address.
for service in agent-runtime platform-api n8n cosmos portal egress-proxy; do
  echo "$service $(docker inspect -f '{{range $name, $net := .NetworkSettings.Networks}}{{$name}}={{$net.IPAddress}} {{end}}' "$("${compose[@]}" ps -q "$service")")"
done | tee "$out/addresses.txt"

{
  echo "== agent-runtime"
  "${compose[@]}" exec -T agent-runtime python - <"$here/lockdown-probe.py"
  echo
  echo "== platform-api"
  "${compose[@]}" exec -T platform-api python - <"$here/lockdown-probe.py"
  echo
  echo "== n8n, straight out with node"
  "${compose[@]}" exec -T n8n node -e "
    require('https').get('https://api.github.com/zen', {timeout: 5000}, (r) => console.log('straight out: HTTP ' + r.statusCode))
      .on('error', (e) => console.log('straight out: ' + e.code + ' ' + e.message))
      .on('timeout', function () { console.log('straight out: no answer in 5 s'); this.destroy() })"
} 2>&1 | tee "$out/probe.txt"

echo
"${compose[@]}" exec -T platform-api python - <"$here/lockdown-check.py" 2>&1 | tee "$out/check.txt"
