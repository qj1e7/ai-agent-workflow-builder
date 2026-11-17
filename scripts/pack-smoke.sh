#!/usr/bin/env bash
# Boots our n8n image once, with the exclusions deploy/compose.yaml sets but n8n's own defaults for
# the other guards bootstrap checks, and checks what n8n allows (ADR 0051):
# - all eight of our blocks load, none of the blocks in n8n_blocks.LEFT_OUT does, and no allow list
#   limits the rest;
# - n8n refuses a workflow with Function, Function Item or LangChain Code, which run code in its
#   own process, and with its defaults keeps the file blocks out of its own folders and lets code
#   load no module of its own choosing (spike P9);
# - the pin check finds each row of node_classes.json still true to what n8n serves (ADR 0045);
# - contracts/n8n/catalogue.json is what n8n serves, and the pin checks of the blocks' code and of
#   the defaults and the runner's config hold (scripts/n8n-catalogue.sh).
# Needs Docker, jq and uv. Publishes no port. PACK_SMOKE_IMAGE names an image already built.
# PACK_SMOKE_CATALOGUE=write writes the catalogue instead of checking it.
set -euo pipefail
cd "$(dirname "$0")/.."

image=${PACK_SMOKE_IMAGE:-}
if [ -z "$image" ]; then
  image=wab/n8n:pack-smoke
  docker build --quiet --file deploy/n8n/Dockerfile --tag "$image" . >/dev/null
fi

ours=$(jq -c '[.nodes[].type]' n8n-node-pack/node-types.json)
# The blocks n8n never loads, as deploy/compose.yaml and Terraform leave them out. n8n_blocks.py
# reads in nothing but the standard library.
never=$(python3 -I -c '
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("n8n_blocks", sys.argv[1])
blocks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blocks)
print(json.dumps(sorted(blocks.LEFT_OUT), separators=(",", ":")))
' platform-api/src/platform_api/orchestration/n8n_blocks.py)
deprecated='["n8n-nodes-base.function","n8n-nodes-base.functionItem","@n8n/n8n-nodes-langchain.code"]'
served=$(mktemp -d)
name="pack-smoke-$$"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$served"
}
trap cleanup EXIT

docker run --detach --name "$name" --env N8N_DIAGNOSTICS_ENABLED=false \
  --env N8N_VERSION_NOTIFICATIONS_ENABLED=false --env N8N_BLOCK_ENV_ACCESS_IN_NODE=true \
  --env N8N_DISABLED_MODULES=mcp-registry \
  --env "NODES_EXCLUDE=$never" --env N8N_COMMUNITY_PACKAGES_ENABLED=false "$image" >/dev/null
for _ in $(seq 1 90); do
  if docker exec "$name" wget -Y off -qO- http://localhost:5678/healthz/readiness >/dev/null 2>&1; then break; fi
  sleep 2
done

# Prints {"types": [the node types n8n serves to a signed-in owner], "deprecated": what n8n
# answered to each workflow with a deprecated block, "settings": what n8n's settings show of the
# guards}, and copies what n8n serves at /types/nodes.json to $served/served.json.
out=$(docker exec -i --env "DEPRECATED=$deprecated" "$name" node --input-type=module - <<'JS'
import { writeFileSync } from 'node:fs';
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
    writeFileSync('/tmp/served-types.json', text);
  } catch (error) {
    if (attempt === 10) throw error;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

// n8n saves a workflow with a block it doesn't load, so each one is also run by hand, as the
// editor's Execute does, and n8n must refuse one or the other.
const deprecated = {};
for (const type of JSON.parse(process.env.DEPRECATED)) {
  const saved = await rest('POST', '/workflows', {
    name: `Pack smoke: ${type}`,
    nodes: [
      { id: 'start', name: 'Run by hand', type: 'n8n-nodes-base.manualTrigger', typeVersion: 1, position: [0, 0], parameters: {} },
      { id: 'old', name: 'Old', type, typeVersion: 1, position: [220, 0], parameters: {} },
    ],
    connections: { 'Run by hand': { main: [[{ node: 'Old', type: 'main', index: 0 }]] } },
    settings: { executionOrder: 'v1' },
  });
  const ran = saved.status === 200
    ? await rest('POST', `/workflows/${saved.body.data.id}/run`, { destinationNode: { nodeName: 'Old', mode: 'inclusive' } })
    : saved;
  deprecated[type] = { saved: saved.status, ran: ran.status, message: ran.body?.message ?? null };
}

const settings = (await rest('GET', '/settings')).body?.data ?? {};
console.log(JSON.stringify({
  types: [...new Set(types.map((n) => n.name))].sort(),
  deprecated,
  settings: {
    blockFileAccessToN8nFiles: settings.security?.blockFileAccessToN8nFiles ?? null,
    allowedModules: settings.allowedModules ?? null,
  },
}));
JS
) || { docker logs "$name" 2>&1 | tail -n 20 >&2; exit 1; }
docker logs "$name" 2>&1 | grep -iE 'error.*(load|node)|class could not be found' >&2 || true
docker cp "$name:/tmp/served-types.json" "$served/served.json" >/dev/null

status=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; status=1; }

types=$(jq -c .types <<<"$out")
missing=$(jq -cn --argjson want "$ours" --argjson got "$types" '$want - $got')
present=$(jq -cn --argjson never "$never" --argjson got "$types" '$never - ($never - $got)')
if [ "$missing" = "[]" ]; then
  pass "n8n loads all $(jq length <<<"$ours") of our blocks ($(jq length <<<"$types") types in all)."
else
  fail "n8n did not load $missing."
fi
if [ "$present" = "[]" ]; then
  pass "n8n does not load $never."
else
  fail "n8n still loads $present."
fi
for sentinel in n8n-nodes-base.httpRequest n8n-nodes-base.code @n8n/n8n-nodes-langchain.agent; do
  if jq -e --arg t "$sentinel" 'index($t) != null' <<<"$types" >/dev/null; then
    pass "n8n loads $sentinel, as it loads every built-in block."
  else
    fail "n8n does not load $sentinel, so something limits the built-in blocks."
  fi
done

refused=$(jq -c '.deprecated | to_entries | map(select(.value.saved == 200 and .value.ran == 200)) | map(.key)' <<<"$out")
if [ "$refused" = "[]" ]; then
  pass "n8n refuses to run a workflow with any of $deprecated."
else
  fail "n8n ran a workflow with $refused: $(jq -c .deprecated <<<"$out")."
fi
if jq -e '.settings.blockFileAccessToN8nFiles == true and (.settings.allowedModules | (.builtIn == null and .external == null))' <<<"$out" >/dev/null; then
  pass "with its defaults, n8n keeps the file blocks out of its own folders and lets code load no module it picks."
else
  fail "n8n's settings show $(jq -c .settings <<<"$out")."
fi

if (cd platform-api && uv run --locked --quiet python -m platform_api.pin_check "$served/served.json"); then
  pass "each row of node_classes.json still matches what n8n serves."
else
  fail "the pin check found node_classes.json and what n8n serves disagree, as above."
fi

check=--check
if [ "${PACK_SMOKE_CATALOGUE:-check}" = write ]; then check=; fi
if scripts/n8n-catalogue.sh ${check:+"$check"} "$served/served.json" "$image"; then
  pass "the catalogue is what n8n serves, and the pin checks of its code, defaults and runner hold."
else
  fail "the catalogue or a pin check failed, as above."
fi

exit "$status"
