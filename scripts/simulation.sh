#!/usr/bin/env bash
# Starts, checks and removes the simulation n8n (ADR 0054), deploy/compose.simulation.yaml.
#   scripts/simulation.sh up      makes up every key, starts the stack and waits for bootstrap
#   scripts/simulation.sh check   checks the running stack holds no real key and reaches only the
#                                 mocks (scripts/simulation_isolation.py)
#   scripts/simulation.sh down    removes the stack's containers, networks and volumes
#   scripts/simulation.sh test    up, check and down, as CI runs it
# SIM_PROJECT names the compose project, wab-sim unless set. SIM_BUILD=0 starts from the sim
# images an earlier start built, and builds nothing.
# Each key is made up here with openssl and lives only in the containers' settings, never in a
# file. The database is in memory, so a new start is a new simulation n8n with new keys.
# It never reads deploy/.env, and it touches no other compose project. It builds the platform's
# images under their own tag, sim, so it never replaces an image the platform's stack runs.
set -euo pipefail
cd "$(dirname "$0")/.."

project=${SIM_PROJECT:-wab-sim}
file=deploy/compose.simulation.yaml
# Its own env file stands in for deploy/.env, which compose would otherwise read.
compose=(docker compose -p "$project" --env-file /dev/null -f "$file")
settings=$(grep -oE '\$\{SIM_[A-Z0-9_]+' "$file" | cut -c3- | sort -u)

made_up_keys() {
  local name
  for name in $settings; do
    export "$name=$(openssl rand -hex 32)"
  done
  # n8n wants an owner password with a capital letter and a digit.
  export SIM_N8N_OWNER_PASSWORD="Aa1$(openssl rand -hex 20)"
}

# compose renders the whole file for every command, so down needs a value for each setting.
placeholders() {
  local name
  for name in $settings; do
    export "$name=${!name:-unused}"
  done
}

up() {
  made_up_keys
  if [ "${SIM_BUILD:-1}" = 1 ]; then
    "${compose[@]}" build --quiet
  fi
  "${compose[@]}" up --detach --wait --wait-timeout "${WAIT_TIMEOUT:-300}" --no-build \
    postgres n8n n8n-runners mock-github mock-slack
  "${compose[@]}" up --detach --no-build bootstrap
  local id status
  id=$("${compose[@]}" ps --all --quiet bootstrap)
  status=$(docker wait "$id")
  docker logs "$id" 2>&1 | tail -n 3
  if [ "$status" != 0 ]; then
    echo "FAIL: bootstrap of the simulation n8n exited with $status." >&2
    return 1
  fi
}

check() {
  python3 -I -B scripts/simulation_isolation.py --project "$project"
}

down() {
  placeholders
  "${compose[@]}" down --volumes --remove-orphans
}

show_logs() {
  placeholders
  "${compose[@]}" logs --no-color --tail 80 >&2 || true
}

case "${1:-}" in
  up) up ;;
  check) check ;;
  down) down ;;
  test)
    trap 'status=$?; [ "$status" = 0 ] || show_logs; down >/dev/null 2>&1 || true; exit "$status"' EXIT
    up
    check
    ;;
  *)
    echo "usage: scripts/simulation.sh up|check|down|test" >&2
    exit 2
    ;;
esac
