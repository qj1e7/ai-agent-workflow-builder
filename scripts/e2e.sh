#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# E2E_AUTH=oidc runs the stack with real sign-in against a mock identity provider, and only the oidc browser spec.
auth="${E2E_AUTH:-dev}"
case "$auth" in
  dev) default_project=wab-e2e default_suites="api ui" files=() ;;
  oidc) default_project=wab-e2e-oidc default_suites=ui files=(-f deploy/compose.oidc.yaml) ;;
  *) echo "E2E_AUTH takes dev or oidc, not '$auth'." >&2; exit 2 ;;
esac
export E2E_AUTH="$auth"

# Its own project name, so tearing it down never touches a stack that scripts/up.sh started.
project="${E2E_PROJECT:-$default_project}"
suites="${E2E_SUITES:-$default_suites}"
out="e2e/out"
compose=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.e2e.yaml ${files[@]+"${files[@]}"})
mkdir -p "$out"
rm -f "$out/e2e.log" "$out/ui.log" "$out/compose.log"

if [ ! -f deploy/.env ]; then
  deploy/make-env.sh
fi

collect_and_stop() {
  "${compose[@]}" --profile e2e logs --no-color >"$out/compose.log" 2>&1 || true
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: stack left running. Stop it with: ${compose[*]} --profile e2e down -v"
  else
    "${compose[@]}" --profile e2e down -v --remove-orphans >/dev/null 2>&1 || true
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
if [ "$auth" = oidc ] && wanted api; then
  echo "The api suite signs in with X-Dev-User, so it runs only with E2E_AUTH=dev." >&2
  exit 2
fi

if ! "${compose[@]}" up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}" >"$out/up.log" 2>&1; then
  tail -n 30 "$out/up.log" >&2
  echo "FAIL: the stack did not become healthy. See $out/up.log and $out/compose.log." >&2
  exit 2
fi

api_status=0
ui_status=0

if wanted api; then
  set +e
  "${compose[@]}" --profile e2e run --rm --build e2e 2>&1 | tee "$out/e2e.log"
  api_status="${PIPESTATUS[0]}"
  set -e
fi

# The browser suite runs after the API tests, on the same stack. It counts tickets before and after, so earlier tests do not matter.
if wanted ui; then
  portal_container=$("${compose[@]}" ps -q portal)
  set +e
  portal/e2e/live/run.sh "$portal_container" 2>&1 | tee "$out/ui.log"
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
if [ "$status" -ne 0 ]; then
  echo "Details: $out/e2e.log, $out/ui.log and $out/compose.log"
fi
exit "$status"
