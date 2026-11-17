#!/usr/bin/env bash
# Checks n8n's guards in deploy/compose.yaml (ADR 0051, spike P9, build step 12), as compose
# renders the file:
# - bootstrap gets each guard n8n gets, with the same value, so its check is a check of n8n;
# - NODES_EXCLUDE leaves out every block in platform-api's n8n_blocks.LEFT_OUT, each of which
#   reaches n8n's own secrets, disk or host;
# - n8n has no allow list (NODES_INCLUDE) and none of the settings that must stay unset;
# - n8n publishes its port on the laptop only, and its task runner's broker listens only on its
#   address on the runners network;
# - n8n-runners runs the runner pin in infra/public-images.json, holds none of n8n's secrets, and
#   sits only on the runners network, which has no way out.
# infra/envs/dev/tests/n8n.tftest.hcl checks the same of Terraform. Needs Docker, jq and python3.
set -euo pipefail
cd "$(dirname "$0")/.."

# platform-api's settings.N8N_GUARDED, which bootstrap reads.
guards='["NODES_EXCLUDE","N8N_BLOCK_ENV_ACCESS_IN_NODE","N8N_RUNNERS_MODE","N8N_DEPRECATED_NODES_BLOCK","N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES","N8N_RESTRICT_FILE_ACCESS_TO"]'
unset_on_n8n='["NODES_INCLUDE","NODE_FUNCTION_ALLOW_BUILTIN","NODE_FUNCTION_ALLOW_EXTERNAL","N8N_RUNNERS_INSECURE_MODE"]'
runner_may_hold='["N8N_RUNNERS_TASK_BROKER_URI","N8N_RUNNERS_AUTH_TOKEN","N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT","GENERIC_TIMEZONE"]'
# n8n_blocks.py reads in nothing but the standard library, so it loads without platform-api's
# packages.
left_out=$(python3 -I -c '
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("n8n_blocks", sys.argv[1])
blocks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blocks)
print(json.dumps(sorted(blocks.LEFT_OUT)))
' platform-api/src/platform_api/orchestration/n8n_blocks.py)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# Each setting compose insists on gets a made-up value, so the file renders without deploy/.env.
grep -oE '\$\{[A-Z0-9_]+:\?' deploy/compose.yaml | sort -u | sed -E 's/^\$\{([A-Z0-9_]+):\?$/\1=made-up/' >"$work/env"
docker compose --env-file "$work/env" -f deploy/compose.yaml config --format json >"$work/config.json"

status=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; status=1; }

differ=$(jq -c --argjson g "$guards" '[$g[] as $name | select(.services.n8n.environment[$name] == null or .services.n8n.environment[$name] != .services.bootstrap.environment[$name]) | $name]' "$work/config.json")
if [ "$differ" = "[]" ]; then
  pass "n8n and bootstrap get the same $(jq length <<<"$guards") guards."
else
  fail "n8n and bootstrap differ on, or n8n lacks, $differ."
fi

missing=$(jq -c --argjson want "$left_out" '$want - (.services.n8n.environment.NODES_EXCLUDE // "[]" | fromjson)' "$work/config.json")
if [ "$missing" = "[]" ]; then
  pass "NODES_EXCLUDE leaves out all $(jq length <<<"$left_out") blocks that reach n8n's own secrets, disk or host."
else
  fail "NODES_EXCLUDE leaves in $missing."
fi

present=$(jq -c --argjson u "$unset_on_n8n" '[$u[] as $name | select(.services.n8n.environment[$name] != null) | $name]' "$work/config.json")
if [ "$present" = "[]" ]; then
  pass "n8n has none of $unset_on_n8n."
else
  fail "n8n sets $present."
fi

hosts=$(jq -c '[.services.n8n.ports[]?.host_ip] | unique' "$work/config.json")
if [ "$hosts" = '["127.0.0.1"]' ]; then
  pass "n8n publishes its port on the laptop only."
else
  fail "n8n publishes its port on $hosts."
fi

broker=$(jq -r '[(.services.n8n.environment.N8N_RUNNERS_BROKER_LISTEN_ADDRESS // "unset"), (.services.n8n.entrypoint // [] | join(" ") | test("lookup\\(.n8n-broker.")), (.services.n8n.networks.runners.aliases // [] | index("n8n-broker") != null), .services["n8n-runners"].environment.N8N_RUNNERS_TASK_BROKER_URI] | @tsv' "$work/config.json")
if [ "$broker" = "$(printf 'unset\ttrue\ttrue\thttp://n8n-broker:5679')" ]; then
  pass "n8n's broker listens only on its address on the runners network, where n8n-runners calls it."
else
  fail "n8n's broker: listen address, its own lookup, its alias and the runner's address are $broker."
fi

pin=$(jq -r '."n8n-runners" | "\(.repository | sub("^library/"; "")):\(.tag)@\(.digest)"' infra/public-images.json)
image=$(jq -r '.services["n8n-runners"].image' "$work/config.json")
if [ "$image" = "$pin" ]; then
  pass "n8n-runners runs the pin $pin."
else
  fail "n8n-runners runs $image, not the pin $pin."
fi

extra=$(jq -c --argjson may "$runner_may_hold" '(.services["n8n-runners"].environment // {} | keys) - $may' "$work/config.json")
if [ "$extra" = "[]" ]; then
  pass "n8n-runners holds only its broker's address, its token and its runners' own settings."
else
  fail "n8n-runners also holds $extra."
fi

networks=$(jq -c '(.services["n8n-runners"].networks // {}) | keys' "$work/config.json")
internal=$(jq -r '.networks.runners.internal // false' "$work/config.json")
if [ "$networks" = '["runners"]' ] && [ "$internal" = true ]; then
  pass "n8n-runners sits only on the runners network, which has no way out."
else
  fail "n8n-runners sits on $networks, and the runners network is internal: $internal."
fi

exit "$status"
