#!/usr/bin/env bash
# A k6 load test of what a busy team does, against the real stack. Needs Docker and nothing else.
# Prints PASS or FAIL. The k6 log and summary land in load/out/.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# k6 2.3.0, pinned by digest.
K6_IMAGE="${K6_IMAGE:-grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34}"

stack_default_project=wab-load
stack_out="load/out"
# shellcheck source=scripts/lib/stack.sh
source scripts/lib/stack.sh

k6_name="${project}-k6"
sampler_pid=""
cleanup() {
  if [ -n "$sampler_pid" ]; then kill "$sampler_pid" 2>/dev/null || true; fi
  docker rm -fv "$k6_name" >/dev/null 2>&1 || true
  stack_stop
}
trap cleanup EXIT

stack_prepare
rm -f "$stack_out"/*.json "$stack_out"/*.log "$stack_out"/*.txt

echo "Starting the stack as compose project $project (no host ports)."
if ! stack_start; then
  exit 2
fi
seed_ids="$(stack_seed ids)"

# CPU and memory of this project's containers every 5 seconds, to show which service is busiest.
(
  while true; do
    date -u +%H:%M:%S
    docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' $("${compose[@]}" ps -q) || true
    sleep 5
  done
) >"$stack_out/stats.log" 2>&1 &
sampler_pid=$!
disown "$sampler_pid"

# RATE_SCALE multiplies every request rate, to look for the knee. DURATION and SEED_RUNS set the length and the history size.
set +e
docker run --rm --name "$k6_name" --network "$network" \
  --volume "$root/load/team.js:/load/team.js:ro" \
  --volume "$root/$stack_out:/out:rw" \
  --env SEED_IDS="$seed_ids" --env PORTAL_URL=http://portal:8080 \
  --env RATE_SCALE="${RATE_SCALE:-1}" --env DURATION="${DURATION:-60s}" --env SEED_RUNS="${SEED_RUNS:-30}" \
  "$K6_IMAGE" run --quiet --no-color --summary-export /out/summary.json /load/team.js 2>&1 | tee "$stack_out/k6.log"
k6_status="${PIPESTATUS[0]}"
set -e

echo
if [ "$k6_status" -eq 0 ]; then
  echo "PASS load: every threshold held. Summary: $stack_out/summary.json, log: $stack_out/k6.log"
else
  echo "FAIL load (k6 exit $k6_status): a threshold or the run failed. See $stack_out/k6.log"
  exit 1
fi
