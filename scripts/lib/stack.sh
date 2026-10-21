# Sourced by scripts/dast.sh and scripts/load.sh. Brings up the whole stack as its own compose project,
# with GitHub mocked and no host ports, and tears it down when the calling script exits.
#
# Before sourcing, set:  stack_default_project  stack_out
# After stack_start:     $project  $network  $compose  (a bash array)

project="${E2E_PROJECT:-$stack_default_project}"
network="${project}_default"
compose=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.e2e.yaml -f deploy/compose.scan.yaml)

stack_prepare() {
  mkdir -p "$stack_out"
  # The scanner and the load generator run as non-root users in their images and write here.
  chmod a+rwx "$stack_out"
  rm -f "$stack_out/up.log" "$stack_out/compose.log"
  if [ ! -f deploy/.env ]; then
    deploy/make-env.sh
  fi
}

stack_start() {
  if ! "${compose[@]}" up --build --wait --wait-timeout "${WAIT_TIMEOUT:-300}" >"$stack_out/up.log" 2>&1; then
    tail -n 30 "$stack_out/up.log" >&2
    echo "FAIL: the stack did not become healthy. See $stack_out/up.log and $stack_out/compose.log." >&2
    return 2
  fi
}

# Prints the ids of a use case and a run that waits at the approval gate. Argument: ids or openapi.
stack_seed() {
  "${compose[@]}" exec -T platform-api python - "$1" <scripts/lib/seed.py
}

stack_stop() {
  "${compose[@]}" logs --no-color >"$stack_out/compose.log" 2>&1 || true
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: stack left running. Stop it with: ${compose[*]} down -v"
  else
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
