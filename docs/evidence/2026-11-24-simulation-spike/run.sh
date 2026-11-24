#!/usr/bin/env bash
# Runs the simulation spike (ADR 0054) on a laptop: starts the simspike stack with keys made up
# here, runs drive.py inside it, checks what n8n reaches and holds, runs scripts/pack-smoke.sh on
# the same image, then removes every container, network and volume the stack made.
#   docs/evidence/2026-11-24-simulation-spike/run.sh [out-dir]
# SIM_ONLY=S3,S4 runs only those items. SIM_KEEP=1 leaves the stack up for a look.
# It touches nothing named wab*: its compose project is simspike and its networks are its own.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
out=${1:-$(mktemp -d)}
mkdir -p "$out"
compose=(docker compose -p simspike -f "$here/compose.yaml")

key() { openssl rand -hex 32; }
# Made up for this run only. Never written to a file.
export SIM_POSTGRES_PASSWORD=$(key) SIM_N8N_DB_PASSWORD=$(key) SIM_OWNER_PASSWORD=$(key)
export SIM_OTHER_PASSWORD=$(key) SIM_N8N_ENCRYPTION_KEY=$(key) SIM_RUNNERS_TOKEN=$(key)
export SIM_OWNER_LOGIN="Aa1$(key | head -c 20)" SIM_STEP_KEY=$(key)
export SIM_NODE_KEY=$(key) SIM_START_SECRET=$(key) SIM_OUT="$out"

down() {
  if [ "${SIM_KEEP:-}" = 1 ]; then return; fi
  "${compose[@]}" --profile driver down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap down EXIT

docker system df
"${compose[@]}" up --detach --wait postgres n8n n8n-runners gateway mock-github mock-slack
"${compose[@]}" up --detach bootstrap
echo "bootstrap exited with $(docker wait simspike-bootstrap-1)" | tee "$out/bootstrap.log"
docker logs simspike-bootstrap-1 >>"$out/bootstrap.log" 2>&1
tail -n 4 "$out/bootstrap.log"
"${compose[@]}" ps --all --format '{{.Service}} {{.State}} {{.ExitCode}}' >"$out/ps.txt"
"${compose[@]}" run --rm driver | tee "$out/driver.log"

# A run of only some items skips the checks after the driver.
if [ -z "${SIM_ONLY:-}" ]; then
{
  echo "## n8n's environment: names only, and the addresses"
  docker inspect simspike-n8n-1 --format '{{range .Config.Env}}{{println .}}{{end}}' |
    sed -E 's/^([A-Z0-9_]+)=.*/\1/' | sort | tr '\n' ' '
  echo
  docker inspect simspike-n8n-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(WAB_API_URL|WEBHOOK_URL|NODE_EXTRA_CA_CERTS)='
  echo "## networks of each container"
  for c in $("${compose[@]}" ps --all --quiet); do
    docker inspect "$c" --format '{{.Name}} {{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
  done
  echo "## the networks are internal"
  docker network inspect simspike_sim simspike_sim-runners --format '{{.Name}} internal={{.Internal}}'
  echo "## what n8n itself reaches"
  for url in https://api.github.com/ https://slack.com/api/api.test http://mock-github:8200/healthz http://gateway:8600/healthz http://wab-platform-api-1:8000/healthz http://platform-api:8000/healthz; do
    if docker exec simspike-n8n-1 wget -Y off -T 5 -qO /dev/null "$url" 2>"$out/wget.err"; then
      echo "$url: reached"
    else
      echo "$url: not reached ($(tr '\n' ' ' <"$out/wget.err" | cut -c1-80))"
    fi
  done
} >"$out/isolation.txt" 2>&1
cat "$out/isolation.txt"

echo "## pin check of what the simulation n8n serves" | tee "$out/pin-check.txt"
(cd "$repo/platform-api" && uv run --locked --quiet python -m platform_api.pin_check "$out/served-types.json") 2>&1 | tee -a "$out/pin-check.txt"

echo "## scripts/pack-smoke.sh on the same image" | tee "$out/pack-smoke.txt"
image=$(docker inspect simspike-n8n-1 --format '{{.Config.Image}}')
(cd "$repo" && PACK_SMOKE_IMAGE="$image" scripts/pack-smoke.sh) 2>&1 | tee -a "$out/pack-smoke.txt"
fi

if [ "${SIM_KEEP:-}" = 1 ]; then echo "left up for a look: $out"; exit 0; fi
down
trap - EXIT
echo "## left behind" | tee "$out/left.txt"
{
  docker ps --all --filter label=com.docker.compose.project=simspike --format '{{.Names}}'
  docker network ls --filter label=com.docker.compose.project=simspike --format '{{.Name}}'
  docker volume ls --filter label=com.docker.compose.project=simspike --format '{{.Name}}'
  docker ps --all --filter name=pack-smoke --format '{{.Names}}'
} | tee -a "$out/left.txt"
echo "results in $out"
