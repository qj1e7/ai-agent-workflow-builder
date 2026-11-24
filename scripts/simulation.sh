#!/usr/bin/env bash
# Starts, checks and removes the simulation n8n (ADR 0054), deploy/compose.simulation.yaml.
#   scripts/simulation.sh up      makes up every key, starts the stack and waits for bootstrap
#   scripts/simulation.sh check   checks the running stack holds no real key and reaches only the
#                                 mocks (scripts/simulation_isolation.py)
#   scripts/simulation.sh drive   runs our blocks through the simulation gateway, one scenario at
#                                 a time (scripts/simulation_drive.py)
#   scripts/simulation.sh down    removes the stack's containers, networks and volumes. A linked
#                                 platform-api must leave the link first
#   scripts/simulation.sh logs    prints the stack's logs
#   scripts/simulation.sh test    up, drive, check and down, as CI runs it. The check comes after
#                                 the drive, so it also sees the mock keys the copies made
# SIM_PROJECT names the compose project, wab-sim unless set. SIM_BUILD=0 starts from the sim
# images an earlier start built, and builds nothing.
# SIM_LINK names the platform's compose project, such as wab, when platform-api is linked to the
# gateway (deploy/compose.simulation-link.yaml, ADR 0054, "What the link chose"). Then up gives
# the simulation the start secret platform-api signs the gateway's routes with, which
# deploy/make-env.sh made as SIMULATION_START_SECRET in deploy/.env, and check also checks the
# linked platform from inside its containers.
# Every other key is made up here with openssl and lives only in the containers' settings, never in
# a file. The database is in memory, so a new start is a new simulation n8n with new keys.
# It reads deploy/.env only for that start secret, with SIM_LINK set, and never prints it. It
# touches no other compose project. It builds the platform's images under their own tag, sim, so it
# never replaces an image the platform's stack runs.
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

# The start secret platform-api holds, from deploy/.env, for a linked simulation.
shared_start_secret() {
  local value
  value=$(grep -E '^SIMULATION_START_SECRET=' deploy/.env 2>/dev/null | tail -n 1 | cut -d= -f2-)
  if [ -z "$value" ]; then
    echo "FAIL: SIM_LINK needs SIMULATION_START_SECRET in deploy/.env. Run deploy/make-env.sh." >&2
    return 1
  fi
  printf '%s' "$value"
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
  if [ -n "${SIM_LINK:-}" ]; then
    SIM_START_SECRET=$(shared_start_secret)
  fi
  if [ "${SIM_BUILD:-1}" = 1 ]; then
    "${compose[@]}" build --quiet
  fi
  "${compose[@]}" up --detach --wait --wait-timeout "${WAIT_TIMEOUT:-300}" --no-build \
    postgres n8n n8n-runners gateway mock-github mock-slack
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
  python3 -I -B scripts/simulation_isolation.py --project "$project" \
    ${SIM_LINK:+--platform "$SIM_LINK"}
}

# Inside the gateway's own container, which holds the simulation's made-up keys, so none leaves it.
drive() {
  placeholders
  local id
  id=$("${compose[@]}" ps --quiet gateway)
  docker exec -i "$id" python -I - <scripts/simulation_drive.py
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
  drive) drive ;;
  down) down ;;
  logs)
    placeholders
    "${compose[@]}" logs --no-color
    ;;
  test)
    trap 'status=$?; [ "$status" = 0 ] || show_logs; down >/dev/null 2>&1 || true; exit "$status"' EXIT
    up
    drive
    check
    ;;
  *)
    echo "usage: scripts/simulation.sh up|check|drive|down|logs|test" >&2
    exit 2
    ;;
esac
