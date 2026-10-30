#!/usr/bin/env bash
# Checker probes for P7 of docs/design/rebuild-plan.md. Rerun any step on its own.
#
# usage: scripts/checks/p7.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       typecheck, lint, unit tests, build, first-load size
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--no-build]
#                                          --no-build starts a second stack on images an earlier up built with that tag
#   down <worktree> <project>
#   check <project> [playwright arguments] run portal/e2e/checks/p7.check.ts in the runner image, in that project's Portal network
#   lane1 <trunk-project> <head-project>   trunk has no Agent library: record it; then lane 1 at head
#   lanes <project>                        lanes 2 to 9 at head, one browser run per lane
#   lane10 <worktree> <project>            stop the agent runtime, open the Tools tab, start the runtime again
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript that each built dist/index.html loads; fails past +30 KB
#   perf <head-project> [samples]          largest contentful paint of /agents; fails at a median of 2.5 s or more
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p7)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); it is never rebuilt here
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p7}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
GROWTH_LIMIT=30720

die() { echo "p7.sh: $*" >&2; exit 2; }

compose() {
  local worktree=$1 project=$2
  shift 2
  docker compose -p "$project" --env-file "$ENV_FILE" -f "$worktree/deploy/compose.yaml" -f "$worktree/deploy/compose.e2e.yaml" "$@"
}

disk() {
  local line avail
  line=$(docker exec "$DISK_CONTAINER" df -h / 2>/dev/null | tail -n 1 || docker run --rm alpine:3.20 df -h / | tail -n 1)
  echo "$line"
  avail=$(docker exec "$DISK_CONTAINER" df -k / 2>/dev/null | awk 'NR==2 {print $4}' || docker run --rm alpine:3.20 df -k / | awk 'NR==2 {print $4}')
  if [ "$avail" -lt $((1536 * 1024)) ]; then
    echo "BLOCKED: less than 1.5 GB free on the Docker disk" >&2
    exit 3
  fi
}

gates() {
  local worktree=$1 out="$EVID/gates"
  mkdir -p "$out"
  (cd "$worktree/portal" && npm run typecheck && npm run lint && npm test) >"$out/typecheck-lint-test.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  /usr/bin/grep -E "Test Files|Tests " "$out/typecheck-lint-test.log"
  tail -n 6 "$out/build-head.log"
}

up() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 build=--build
  case "${7:-}" in
    '') ;;
    --no-build) build=--no-build ;;
    *) die "unknown up option $7" ;;
  esac
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port \
    compose "$worktree" "$project" up "$build" --wait --wait-timeout 300 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
}

down() {
  local worktree=$1 project=$2
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" --profile e2e down -v --remove-orphans
}

portal_of() {
  docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=portal" | head -n 1
}

# Each folder is mounted on its own, so a fresh clone works without a gitignored portal/e2e/out folder.
check() {
  local project=$1
  shift
  local portal
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  mkdir -p "$EVID"
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH="${E2E_AUTH:-dev}" -e EVID=/evidence \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" -e EXPECT_DOWN="${EXPECT_DOWN:-0}" \
    -v "$checker_root/portal/e2e/checks:/work/e2e/checks:ro" \
    -v "$checker_root/portal/e2e/live:/work/e2e/live:ro" \
    -v "$checker_root/portal/e2e/support:/work/e2e/support:ro" \
    -v "$EVID:/evidence" \
    -w /work "$RUNNER" \
    npx playwright test -c e2e/checks/playwright.config.ts p7.check.ts "$@"
}

lane1() {
  local trunk=$1 head=$2 status=0
  TARGET=trunk check "$trunk" --grep "@lane1\b" || status=$?
  TARGET=head check "$head" --grep "@lane1\b" || status=$?
  return "$status"
}

lanes() {
  local project=$1 status=0 lane
  for lane in 2 3 4 5 6 7 8 9; do
    check "$project" --grep "@lane$lane\b" || status=$?
  done
  return "$status"
}

lane10() {
  local worktree=$1 project=$2 out="$EVID/lane-10" status=0
  mkdir -p "$out"
  compose "$worktree" "$project" stop agent-runtime 2>&1 | tee "$out/stop.log"
  compose "$worktree" "$project" ps -a --format '{{.Service}} {{.State}}' | tee "$out/ps-while-down.txt"
  EXPECT_DOWN=1 check "$project" --grep "@lane10" || status=$?
  compose "$worktree" "$project" start agent-runtime 2>&1 | tee "$out/start.log"
  return "$status"
}

size() {
  local out="$EVID/perf" name dir total trunk_total=0 head_total=0
  mkdir -p "$out"
  : >"$out/first-load-js.txt"
  for pair in "trunk:$1" "head:$2"; do
    name=${pair%%:*}
    dir=${pair#*:}/portal/dist
    [ -f "$dir/index.html" ] || die "no $dir/index.html; build the $name Portal first"
    total=0
    for src in $(/usr/bin/grep -oE '<script[^>]*src="[^"]+"' "$dir/index.html" | sed -E 's/.*src="([^"]+)".*/\1/'); do
      bytes=$(gzip -c "$dir$src" | wc -c | tr -d ' ')
      echo "$name $src gzip=$bytes" | tee -a "$out/first-load-js.txt"
      total=$((total + bytes))
    done
    echo "$name total gzip=$total" | tee -a "$out/first-load-js.txt"
    if [ "$name" = trunk ]; then trunk_total=$total; else head_total=$total; fi
  done
  echo "growth=$((head_total - trunk_total)) bytes (limit $GROWTH_LIMIT; trunk baseline measured from $1)" | tee -a "$out/first-load-js.txt"
  [ $((head_total - trunk_total)) -le "$GROWTH_LIMIT" ]
}

perf() {
  local head=$1 samples=${2:-5}
  mkdir -p "$EVID/perf"
  rm -f "$EVID"/perf/lcp-head-*.json
  for i in $(seq 1 "$samples"); do
    TARGET=head SAMPLE=$i check "$head" --grep @perf
  done
  node -e '
    const fs = require("fs"), dir = process.argv[1]
    const rows = fs.readdirSync(dir).filter((f) => /^lcp-head-.*\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8"))).sort((a, b) => a.sample - b.sample)
    const sorted = rows.map((r) => r.lcp).sort((a, b) => a - b)
    const median = sorted[Math.floor(sorted.length / 2)]
    const lines = [`head: ${rows.map((r) => `#${r.sample} ${r.lcp.toFixed(0)} ms (${r.element})`).join(", ")}`, `head median: ${median.toFixed(0)} ms (limit 2500)`]
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    if (!(median < 2500)) process.exit(1)
  ' "$EVID/perf"
}

command=${1:-}
[ -n "$command" ] || die "usage: p7.sh <disk|gates|up|down|check|lane1|lanes|lane10|size|perf> ..."
shift
case "$command" in
  disk | gates | up | down | check | lane1 | lanes | lane10 | size | perf) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
