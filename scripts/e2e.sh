#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

auth="${E2E_AUTH:-dev}"
case "$auth" in
  dev) default_project=wab-e2e default_suites="api ui" files=() ;;
  oidc) default_project=wab-e2e-oidc default_suites=ui files=(-f deploy/compose.oidc.yaml) ;;
  *) echo "E2E_AUTH takes dev or oidc, not '$auth'." >&2; exit 2 ;;
esac
export E2E_AUTH="$auth"

# E2E_SEED=old-engine starts the stack from a database made before ENGINE-PLAN E10 and runs only the
# test of the move, on a project of its own.
seed="${E2E_SEED:-}"
case "$seed" in
  "") ;;
  old-engine) default_project=wab-e2e-seed default_suites=api files+=(-f deploy/compose.seed.yaml) ;;
  *) echo "E2E_SEED takes old-engine, not '$seed'." >&2; exit 2 ;;
esac
export E2E_SEED="$seed"

# E2E_SIMULATION=on starts the simulation stack first, links platform-api to its gateway
# (deploy/compose.simulation-link.yaml, ADR 0054), runs only the test of the link, then the
# isolation check on both stacks.
simulation="${E2E_SIMULATION:-}"
case "$simulation" in
  "") ;;
  on) default_project=wab-e2e-sim default_suites=api files+=(-f deploy/compose.simulation-link.yaml) ;;
  *) echo "E2E_SIMULATION takes on, not '$simulation'." >&2; exit 2 ;;
esac
export E2E_SIMULATION="$simulation"

# Its own project name, so tearing it down never touches a stack that scripts/up.sh started.
project="${E2E_PROJECT:-$default_project}"
# A part of the browser suite starts on an empty stack, as it does in CI, so it leaves the API tests out unless asked.
[ -z "${LIVE_PART:-}" ] || default_suites=ui
suites="${E2E_SUITES:-$default_suites}"
out="e2e/out"
compose=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.e2e.yaml ${files[@]+"${files[@]}"})
sim=(env SIM_PROJECT="$project-sim" SIM_LINK="$project" scripts/simulation.sh)
if [ -n "$simulation" ]; then
  export SIMULATION_LINK_NETWORK="$project-sim_link"
  API_K="${API_K:-practice_systems}"
fi
mkdir -p "$out"
rm -f "$out/e2e.log" "$out/ui.log" "$out/compose.log" "$out/simulation.log"

if [ ! -f deploy/.env ]; then
  deploy/make-env.sh
elif [ -n "$simulation" ]; then
  # An older deploy/.env gains the simulation's start secret.
  deploy/make-env.sh >/dev/null
fi

collect_and_stop() {
  "${compose[@]}" --profile e2e logs --no-color >"$out/compose.log" 2>&1 || true
  [ -z "$simulation" ] || "${sim[@]}" logs >"$out/simulation.log" 2>&1 || true
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: stack left running. Stop it with: ${compose[*]} --profile e2e down -v"
    [ -z "$simulation" ] || echo "Then stop the simulation with: ${sim[*]} down"
  else
    "${compose[@]}" --profile e2e down -v --remove-orphans >/dev/null 2>&1 || true
    # After the platform, which leaves the link the simulation made.
    [ -z "$simulation" ] || "${sim[@]}" down >/dev/null 2>&1 || true
  fi
}
trap collect_and_stop EXIT

wanted() {
  case " $suites " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

summary_line() {
  grep -E "[0-9]+ (passed|failed|error)" "$1" | tail -n 1 || echo "no summary"
}

for suite in $suites; do
  case "$suite" in
    api | ui) ;;
    *) echo "E2E_SUITES takes api and ui, not '$suite'." >&2; exit 2 ;;
  esac
done

# LIVE_PART runs one of the four parts CI splits the browser suite into, each on its own runner and stack.
# Playwright's --shard splits by the count of tests, but fit.live.ts held 70 of the 298 tests and took 15.8 of
# the 36.8 minutes in run 45977915310. So fit-1 and fit-2 split fit.live.ts test by test, and rest-1 and
# rest-2 split the other files file by file. One pattern picks fit.live.ts in or out, so every test runs in
# exactly one part. Playwright matches it against the file's path and the test's title, joined by spaces, so
# the spaces keep a file such as profit.live.ts out.
part="${LIVE_PART:-}"
fit_pattern='(^|\s)fit\.live\.ts\s'
ui_args=()
case "$part" in
  "") ;;
  rest-1 | rest-2) ui_args=(--grep-invert "$fit_pattern" --shard="${part#rest-}/2") ;;
  fit-1 | fit-2) ui_args=(--grep "$fit_pattern" --fully-parallel --shard="${part#fit-}/2") ;;
  *) echo "LIVE_PART takes rest-1, rest-2, fit-1 or fit-2, not '$part'." >&2; exit 2 ;;
esac
if [ -n "$part" ] && ! wanted ui; then
  echo "LIVE_PART picks part of the browser suite, so E2E_SUITES must hold ui." >&2
  exit 2
fi
if [ -n "${LIVE_GREP:-}" ]; then
  if [ -n "$part" ]; then
    echo "LIVE_GREP picks its own tests, so it runs without LIVE_PART." >&2
    exit 2
  fi
  ui_args=(--grep "$LIVE_GREP")
fi
if [ "$auth" = oidc ] && wanted api; then
  echo "The api suite signs in with X-Dev-User, so it runs only with E2E_AUTH=dev." >&2
  exit 2
fi

# The seeded stack's own logs, in the job's log, when it fails.
show_seed_logs() {
  [ -n "$seed" ] || return 0
  echo "--- seed, bootstrap and platform-api logs ---" >&2
  "${compose[@]}" logs --no-color --tail 200 seed bootstrap platform-api >&2 || true
}

if [ -n "$simulation" ] && ! "${sim[@]}" up >"$out/simulation-up.log" 2>&1; then
  tail -n 30 "$out/simulation-up.log" >&2
  echo "FAIL: the simulation stack did not start. See $out/simulation-up.log." >&2
  exit 2
fi

if ! "${compose[@]}" up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}" >"$out/up.log" 2>&1; then
  tail -n 30 "$out/up.log" >&2
  show_seed_logs
  echo "FAIL: the stack did not become healthy. See $out/up.log and $out/compose.log." >&2
  exit 2
fi

api_status=0
ui_status=0

if wanted api; then
  set +e
  api_args=()
  [ -z "${API_K:-}" ] || api_args=(-e "PYTEST_ADDOPTS=-k '$API_K'")
  "${compose[@]}" --profile e2e run --rm --build ${api_args[@]+"${api_args[@]}"} e2e 2>&1 | tee "$out/e2e.log"
  api_status="${PIPESTATUS[0]}"
  [ "$api_status" -eq 0 ] || show_seed_logs
  set -e
fi

# The isolation check on the running stacks, from inside their containers: the simulation holds no
# real key, its n8n reaches nothing of the platform's, and its gateway only platform-api.
simulation_status=0
if [ -n "$simulation" ]; then
  set +e
  "${sim[@]}" check 2>&1 | tee -a "$out/e2e.log"
  simulation_status="${PIPESTATUS[0]}"
  set -e
fi

# The browser suite runs after the API tests, on the same stack. It counts tickets before and after, so earlier tests do not matter.
if wanted ui; then
  portal_container=$("${compose[@]}" ps -q portal)
  set +e
  portal/e2e/live/run.sh "$portal_container" ${ui_args[@]+"${ui_args[@]}"} 2>&1 | tee "$out/ui.log"
  ui_status="${PIPESTATUS[0]}"
  set -e
fi

echo
status=0
if wanted api; then
  if [ "$api_status" -eq 0 ]; then echo "PASS api: $(summary_line "$out/e2e.log")"; else echo "FAIL api (exit $api_status): $(summary_line "$out/e2e.log")"; status=$api_status; fi
fi
if wanted ui; then
  if [ "$ui_status" -eq 0 ]; then echo "PASS ui:  $(summary_line "$out/ui.log")"; else echo "FAIL ui (exit $ui_status): $(summary_line "$out/ui.log")"; [ "$status" -ne 0 ] || status=$ui_status; fi
  echo "Browser evidence: portal/e2e/out/live (shots and video)"
fi
if [ -n "$simulation" ]; then
  if [ "$simulation_status" -eq 0 ]; then echo "PASS simulation isolation"; else echo "FAIL simulation isolation (exit $simulation_status)"; [ "$status" -ne 0 ] || status=$simulation_status; fi
fi
if [ "$status" -ne 0 ]; then
  echo "Details: $out/e2e.log, $out/ui.log, $out/compose.log and $out/simulation.log"
fi
exit "$status"
