#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

out="e2e/out"
compose=(docker compose -f deploy/compose.yaml -f deploy/compose.e2e.yaml)
mkdir -p "$out"
rm -f "$out/e2e.log" "$out/compose.log"

if [ ! -f deploy/.env ]; then
  echo "FAIL: deploy/.env is missing. Generate the dev secrets first (see deploy/README.md)." >&2
  exit 2
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

summary_line() {
  grep -E "[0-9]+ (passed|failed|error)" "$out/e2e.log" | tail -n 1 || echo "no pytest summary"
}

if ! "${compose[@]}" up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}" >"$out/up.log" 2>&1; then
  tail -n 30 "$out/up.log" >&2
  echo "FAIL: the stack did not become healthy. See $out/up.log and $out/compose.log." >&2
  exit 2
fi

set +e
"${compose[@]}" --profile e2e run --rm --build e2e 2>&1 | tee "$out/e2e.log"
status="${PIPESTATUS[0]}"
set -e

echo
if [ "$status" -eq 0 ]; then
  echo "PASS: $(summary_line)"
else
  echo "FAIL (exit $status): $(summary_line)"
  echo "Details: $out/e2e.log and $out/compose.log"
fi
exit "$status"
