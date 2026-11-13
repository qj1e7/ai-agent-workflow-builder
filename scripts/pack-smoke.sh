#!/usr/bin/env bash
# Boots our n8n image twice and checks which node types n8n loads:
# - as deployed now, with no allow list: all eight of our blocks;
# - with the allow list ENGINE-PLAN.md names for E11: exactly those types, and nothing else.
# Needs Docker and jq. Publishes no port. PACK_SMOKE_IMAGE names an image already built.
set -euo pipefail
cd "$(dirname "$0")/.."

image=${PACK_SMOKE_IMAGE:-}
if [ -z "$image" ]; then
  image=wab/n8n:pack-smoke
  docker build --quiet --file deploy/n8n/Dockerfile --tag "$image" . >/dev/null
fi

ours=$(jq -c '[.nodes[].type]' n8n-node-pack/node-types.json)
n8n_own='["n8n-nodes-base.scheduleTrigger","n8n-nodes-base.manualTrigger","n8n-nodes-base.errorTrigger","n8n-nodes-base.if","n8n-nodes-base.merge","n8n-nodes-base.noOp","n8n-nodes-base.stickyNote"]'
allow_list=$(jq -cn --argjson a "$ours" --argjson b "$n8n_own" '$a + $b')

# Each check runs in a subshell, so the containers are found by name, not kept in a variable.
cleanup() { docker ps -aq --filter "name=^pack-smoke-$$-" | xargs docker rm -f >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Prints the sorted node types n8n serves to a signed-in owner.
loaded_types() {
  local name="pack-smoke-$$-$1"
  shift
  docker run --detach --name "$name" --env N8N_DIAGNOSTICS_ENABLED=false \
    --env N8N_VERSION_NOTIFICATIONS_ENABLED=false "$@" "$image" >/dev/null
  for _ in $(seq 1 90); do
    if docker exec "$name" wget -Y off -qO- http://localhost:5678/healthz/readiness >/dev/null 2>&1; then break; fi
    sleep 2
  done
  docker exec -i "$name" node --input-type=module - <<'JS'
const base = 'http://localhost:5678';
const setup = await fetch(`${base}/rest/owner/setup`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ email: 'smoke@example.com', firstName: 'Pack', lastName: 'Smoke', password: 'PackSmoke1234' }),
});
if (!setup.ok) throw new Error(`owner setup answered ${setup.status}`);
const cookie = setup.headers.get('set-cookie').split(';')[0];
// Soon after start the file can come back cut short, so a body that does not parse is read again.
let types;
for (let attempt = 1; !types; attempt++) {
  const res = await fetch(`${base}/types/nodes.json`, { headers: { cookie } });
  if (!res.ok) throw new Error(`/types/nodes.json answered ${res.status}`);
  const text = await res.text();
  try {
    types = JSON.parse(text);
  } catch (error) {
    if (attempt === 10) throw error;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}
console.log(JSON.stringify([...new Set(types.map((n) => n.name))].sort()));
JS
  docker logs "$name" 2>&1 | grep -iE 'error.*(load|node)|class could not be found' >&2 || true
}

status=0

off=$(loaded_types off)
missing=$(jq -cn --argjson want "$ours" --argjson got "$off" '$want - $got')
if [ "$missing" = "[]" ]; then
  echo "PASS: with no allow list, n8n loads all $(jq length <<<"$ours") of our blocks ($(jq length <<<"$off") types in all)."
else
  echo "FAIL: with no allow list, n8n did not load $missing." >&2
  status=1
fi

on=$(loaded_types on --env "NODES_INCLUDE=$allow_list")
extra=$(jq -cn --argjson want "$allow_list" --argjson got "$on" '$got - $want')
missing=$(jq -cn --argjson want "$allow_list" --argjson got "$on" '$want - $got')
if [ "$extra" = "[]" ] && [ "$missing" = "[]" ]; then
  echo "PASS: with the allow list, n8n loads exactly its $(jq length <<<"$allow_list") types."
else
  echo "FAIL: with the allow list, n8n also loads $extra and is missing $missing." >&2
  status=1
fi

exit "$status"
