#!/usr/bin/env bash
# Boots our n8n image twice, with the guards deploy/compose.yaml sets, and checks what n8n allows:
# - as deployed now, with no allow list: all eight of our blocks load, and Execute Command and
#   Local File Trigger do not;
# - with the allow list ENGINE-PLAN.md names for E11: exactly those types load, and a workflow
#   with an HTTP Request node cannot be turned on.
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
never='["n8n-nodes-base.executeCommand","n8n-nodes-base.localFileTrigger"]'

# Each check runs in a subshell, so the containers are found by name, not kept in a variable.
cleanup() { docker ps -aq --filter "name=^pack-smoke-$$-" | xargs docker rm -f >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Prints {"types": [the node types n8n serves to a signed-in owner], "turnOn": what n8n answered
# when asked to turn on a workflow with an HTTP Request node}.
check_n8n() {
  local name="pack-smoke-$$-$1"
  shift
  docker run --detach --name "$name" --env N8N_DIAGNOSTICS_ENABLED=false \
    --env N8N_VERSION_NOTIFICATIONS_ENABLED=false --env N8N_BLOCK_ENV_ACCESS_IN_NODE=true \
    --env "NODES_EXCLUDE=$never" --env N8N_COMMUNITY_PACKAGES_ENABLED=false "$@" "$image" >/dev/null
  for _ in $(seq 1 90); do
    if docker exec "$name" wget -Y off -qO- http://localhost:5678/healthz/readiness >/dev/null 2>&1; then break; fi
    sleep 2
  done
  local out
  out=$(docker exec -i "$name" node --input-type=module - <<'JS'
const base = 'http://localhost:5678';
const setup = await fetch(`${base}/rest/owner/setup`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ email: 'smoke@example.com', firstName: 'Pack', lastName: 'Smoke', password: 'PackSmoke1234' }),
});
if (!setup.ok) throw new Error(`owner setup answered ${setup.status}`);
const cookie = setup.headers.get('set-cookie').split(';')[0];
const rest = async (method, path, body) => {
  const res = await fetch(`${base}/rest${path}`, {
    method,
    headers: { cookie, 'content-type': 'application/json' },
    body: body && JSON.stringify(body),
  });
  return { status: res.status, body: await res.json().catch(() => null) };
};

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

const saved = await rest('POST', '/workflows', {
  name: 'Pack smoke: sends data out',
  nodes: [
    { id: 'when', name: 'Every hour', type: 'n8n-nodes-base.scheduleTrigger', typeVersion: 1.2, position: [0, 0],
      parameters: { rule: { interval: [{ field: 'hours' }] } } },
    { id: 'out', name: 'Send it out', type: 'n8n-nodes-base.httpRequest', typeVersion: 4.2, position: [220, 0],
      parameters: { url: 'http://127.0.0.1:9/', options: {} } },
  ],
  connections: { 'Every hour': { main: [[{ node: 'Send it out', type: 'main', index: 0 }]] } },
  settings: { executionOrder: 'v1' },
});
const turnOn = saved.status === 200
  ? await rest('POST', `/workflows/${saved.body.data.id}/activate`, { versionId: saved.body.data.versionId })
  : saved;

console.log(JSON.stringify({
  types: [...new Set(types.map((n) => n.name))].sort(),
  turnOn: { status: turnOn.status, message: turnOn.body?.message ?? null },
}));
JS
  ) || { docker logs "$name" 2>&1 | tail -n 20 >&2; return 1; }
  docker logs "$name" 2>&1 | grep -iE 'error.*(load|node)|class could not be found' >&2 || true
  echo "$out"
}

status=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; status=1; }

off=$(check_n8n off)
off_types=$(jq -c .types <<<"$off")
missing=$(jq -cn --argjson want "$ours" --argjson got "$off_types" '$want - $got')
present=$(jq -cn --argjson never "$never" --argjson got "$off_types" '$never - ($never - $got)')
if [ "$missing" = "[]" ]; then
  pass "with no allow list, n8n loads all $(jq length <<<"$ours") of our blocks ($(jq length <<<"$off_types") types in all)."
else
  fail "with no allow list, n8n did not load $missing."
fi
if [ "$present" = "[]" ]; then
  pass "with no allow list, n8n does not load $never."
else
  fail "with no allow list, n8n still loads $present."
fi

on=$(check_n8n on --env "NODES_INCLUDE=$allow_list")
on_types=$(jq -c .types <<<"$on")
extra=$(jq -cn --argjson want "$allow_list" --argjson got "$on_types" '$got - $want')
missing=$(jq -cn --argjson want "$allow_list" --argjson got "$on_types" '$want - $got')
if [ "$extra" = "[]" ] && [ "$missing" = "[]" ]; then
  pass "with the allow list, n8n loads exactly its $(jq length <<<"$allow_list") types."
else
  fail "with the allow list, n8n also loads $extra and is missing $missing."
fi
turn_on=$(jq -c .turnOn <<<"$on")
if jq -e '.status == 400 and (.message | test("Unrecognized node type: n8n-nodes-base.httpRequest"))' <<<"$turn_on" >/dev/null; then
  pass "with the allow list, n8n refuses to turn on a workflow with an HTTP Request node: $turn_on."
else
  fail "with the allow list, turning on a workflow with an HTTP Request node answered $turn_on."
fi

exit "$status"
