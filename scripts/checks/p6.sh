#!/usr/bin/env bash
# Checker probes for P6 of docs/design/rebuild-plan.md: the Software watchlist page. Rerun any step on its own.
#
# usage: scripts/checks/p6.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       typecheck, lint, unit tests, nginx render, build
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port>
#   down <worktree> <project>
#   check <project> [playwright arguments] run portal/e2e/checks/p6.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run the builder's live specs (portal/e2e/live) the same way
#   lane1 <head-project> [trunk-project]   add software and check it at head; trunk has no Software watchlist page
#   lane <n> <project>                     lanes 2, 3, 4, 5, 7, 8, 9 and 10, one at a time on a shared stack
#   lane6 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port>
#                                          the mock GitHub fails during a check, on its own stack, which this brings up and down
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript that dist/index.html loads
#   perf <project> [samples]               largest contentful paint of the page with 14 watched software, median of the samples
#   video <project>                        the review video of adding software and a check, as $EVID/p6-review.webm and, with ffmpeg, .mp4
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p6)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p6}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}

die() { echo "p6.sh: $*" >&2; exit 2; }

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
  (cd "$worktree/portal" && npx vitest run src/screens/software src/shell src/api) >"$out/vitest-run-shell.log" 2>&1
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  grep -E "Test Files|Tests " "$out/typecheck-lint-test.log" "$out/vitest-run-shell.log"
  echo "nginx render checks ok: $(grep -c '^ok' "$out/nginx-render.log")"
  tail -n 1 "$out/nginx-render.log"
}

up() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port \
    compose "$worktree" "$project" up --build --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
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

runner_in() {
  local project=$1
  shift
  local portal
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  docker image inspect "$RUNNER" >/dev/null 2>&1 || die "no runner image $RUNNER; build it with E2E_RUNNER_IMAGE=$RUNNER portal/e2e/runner-image.sh"
  mkdir -p "$EVID/.live-out"
  # Each e2e folder is mounted on its own, so the live output can be mounted beside them. A fresh clone has no
  # portal/e2e/out, and docker can't make a mount point inside a read-only mount.
  local e2e_mounts=() folder
  for folder in checks live support; do
    e2e_mounts+=(-v "$checker_root/portal/e2e/$folder:/work/e2e/$folder:ro")
  done
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH=dev -e EVID=/evidence \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" -e MOCK_GITHUB_URL=http://mock-github:8200 \
    -e PLAIN_HTTP_URL=http://portal:8080 \
    "${e2e_mounts[@]}" -v "$EVID:/evidence" -v "$EVID/.live-out:/work/e2e/out/live" \
    -w /work "$RUNNER" "$@"
}

check() {
  local project=$1
  shift
  runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p6.check.ts "$@"
}

live() {
  local project=$1
  shift
  runner_in "$project" npx playwright test -c e2e/live/playwright.config.ts "$@"
}

lane1() {
  local head=$1 trunk=${2:-}
  mkdir -p "$EVID/lane-1"
  if [ -n "$trunk" ]; then
    TARGET=trunk check "$trunk" --grep @lane1-trunk
  else
    echo "no trunk stack given: trunk has no Software watchlist page after P1, its page says This page is not built yet." | tee "$EVID/lane-1/p6-trunk.txt"
  fi
  TARGET=head check "$head" --grep '@lane1 '
}

lane() {
  local n=$1 project=$2
  case "$n" in
    2 | 3 | 4 | 5 | 7 | 8 | 9 | 10) ;;
    *) die "lane $n does not run on a shared stack; see lane1 and lane6" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log"
  return "${PIPESTATUS[0]}"
}

lane6() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 status=0
  up "$worktree" "$project" "$tag" "$portal_port" "$api_port" "$n8n_port"
  mkdir -p "$EVID/lane-6"
  check "$project" --grep '@lane6 ' 2>&1 | tee "$EVID/lane-6/playwright.log" || status=$?
  down "$worktree" "$project"
  return "$status"
}

size() {
  local out="$EVID/perf" name dir total
  mkdir -p "$out"
  : >"$out/first-load-js.txt"
  for pair in "trunk:$1" "head:$2"; do
    name=${pair%%:*}
    dir=${pair#*:}/portal/dist
    [ -f "$dir/index.html" ] || die "no $dir/index.html; run gates on that worktree first, which builds it"
    total=0
    for src in $(grep -oE '<script[^>]*src="[^"]+"' "$dir/index.html" | sed -E 's/.*src="([^"]+)".*/\1/'); do
      bytes=$(gzip -c "$dir$src" | wc -c | tr -d ' ')
      echo "$name $src gzip=$bytes" | tee -a "$out/first-load-js.txt"
      total=$((total + bytes))
    done
    echo "$name total gzip=$total" | tee -a "$out/first-load-js.txt"
  done
}

perf() {
  local project=$1 samples=${2:-5}
  mkdir -p "$EVID/perf"
  rm -f "$EVID"/perf/lcp-*.json
  for i in $(seq 1 "$samples"); do
    TARGET=head SAMPLE=$i check "$project" --grep @perf
  done
  node -e '
    const fs = require("fs"), dir = process.argv[1]
    const rows = fs.readdirSync(dir).filter((f) => /^lcp-head-.*\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8"))).sort((a, b) => a.sample - b.sample)
    const sorted = rows.map((r) => r.lcp).sort((a, b) => a - b)
    const median = sorted[Math.floor(sorted.length / 2)]
    const lines = [`head: ${rows.map((r) => `#${r.sample} ${r.lcp.toFixed(0)} ms (${r.element})`).join(", ")}`, `head median: ${median.toFixed(0)} ms`, `rule: under 2500 ms: ${median < 2500 ? "PASS" : "FAIL"}`]
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    process.exit(median < 2500 ? 0 : 1)
  ' "$EVID/perf"
}

video() {
  local project=$1
  check "$project" --grep @review-video
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p6-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p6-review.mp4"
  fi
  ls -la "$EVID"/p6-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p6.sh <disk|gates|up|down|check|live|lane1|lane|lane6|size|perf|video> ..."
shift
case "$command" in
  disk | gates | up | down | check | live | lane1 | lane | lane6 | size | perf | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
