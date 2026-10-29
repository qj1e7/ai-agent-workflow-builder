#!/usr/bin/env bash
# Checker probes for P1 of docs/design/rebuild-plan.md. Rerun any step on its own.
#
# usage: scripts/checks/p1.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       typecheck, lint, unit tests, kept modules, nginx render, build
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [oidc]
#   down <worktree> <project> [oidc]
#   check <project> [playwright arguments] run portal/e2e/checks in the runner image, in that project's Portal network
#   lane1 <trunk-project> <head-project> <trunk-sha> <head-sha>
#                                          old menu at trunk, new menu at head, one side-by-side shot captioned with the SHAs
#   lane2 <worktree> <oidc-project>        the builder's 06 spec and the checker's own lane 2, real sign-in
#   lane9 <worktree> <project> <api-port>  stop the real platform-api, load the Portal, start it again
#   lane10 <worktree> <project>            retired names in portal/dist and in every page's text
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript that dist/index.html loads
#   perf <trunk-project> <head-project> [samples]  largest contentful paint of Home, interleaved
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p1)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); it is never built here, so build it
#                     first with portal/e2e/runner-image.sh if it is missing
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p1}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}

die() { echo "p1.sh: $*" >&2; exit 2; }

compose() {
  local worktree=$1 project=$2 oidc=$3
  shift 3
  local files=(-f "$worktree/deploy/compose.yaml" -f "$worktree/deploy/compose.e2e.yaml")
  [ "$oidc" = oidc ] && files+=(-f "$worktree/deploy/compose.oidc.yaml")
  docker compose -p "$project" --env-file "$ENV_FILE" "${files[@]}" "$@"
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
  (cd "$worktree/portal" && npx vitest run src/api src/stream) >"$out/vitest-api-stream.log" 2>&1
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  grep -E "Test Files|Tests " "$out/typecheck-lint-test.log" "$out/vitest-api-stream.log"
  echo "nginx render checks ok: $(grep -c '^ok' "$out/nginx-render.log")"
  tail -n 1 "$out/nginx-render.log"
}

up() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 oidc=${7:-dev}
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port \
    compose "$worktree" "$project" "$oidc" up --build --wait --wait-timeout 300 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  if [ "$oidc" = oidc ]; then
    # No host port on the oidc stack, so ask from inside the Portal container.
    local portal
    portal=$(compose "$worktree" "$project" "$oidc" ps -q portal)
    docker exec "$portal" wget -qSO- http://platform-api:8000/healthz/ready 2>&1 | tee "$EVID/stacks/$project-ready.txt"
  else
    curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
    cat "$EVID/stacks/$project-ready.json"; echo
  fi
}

down() {
  local worktree=$1 project=$2 oidc=${3:-dev}
  compose "$worktree" "$project" "$oidc" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" "$oidc" --profile e2e down -v --remove-orphans
}

portal_of() {
  docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=portal" | head -n 1
}

runner_in() {
  local root=$1 project=$2
  shift 2
  local portal
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  docker image inspect "$RUNNER" >/dev/null 2>&1 || die "no runner image $RUNNER; build it with E2E_RUNNER_IMAGE=$RUNNER portal/e2e/runner-image.sh"
  mkdir -p "$EVID/.live-out"
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH="${E2E_AUTH:-dev}" -e EVID=/evidence \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" -e EXPECT_DOWN="${EXPECT_DOWN:-0}" \
    -e TRUNK_SHA="${TRUNK_SHA:-}" -e HEAD_SHA="${HEAD_SHA:-}" \
    -e MOCK_OIDC_URL="${MOCK_OIDC_URL:-http://mock-oidc:8080/default}" \
    -e MOCK_GITHUB_URL=http://mock-github:8200 -e PLAIN_HTTP_URL=http://portal:8080 \
    -v "$root/portal/e2e:/work/e2e:ro" -v "$EVID:/evidence" -v "$EVID/.live-out:/work/e2e/out/live" \
    -w /work "$RUNNER" "$@"
}

check() {
  local project=$1
  shift
  runner_in "$checker_root" "$project" npx playwright test -c e2e/checks/playwright.config.ts "$@"
}

lane1() {
  local trunk=$1 head=$2
  export TRUNK_SHA=${3:?give the trunk SHA for the caption} HEAD_SHA=${4:?give the head SHA for the caption}
  TARGET=trunk check "$trunk" --grep @lane1-capture
  TARGET=head check "$head" --grep @lane1-capture
  TARGET=head check "$head" --grep @lane1-combine
}

lane2() {
  local worktree=$1 project=$2
  mkdir -p "$EVID/lane-2"
  local builder=0 own=0 run=${LANE2_RUN:-1}
  E2E_AUTH=oidc runner_in "$worktree" "$project" npx playwright test -c e2e/live/playwright.config.ts >"$EVID/lane-2/builder-06-oidc-$run.log" 2>&1 || builder=$?
  rm -rf "$EVID/lane-2/builder-06-shots-$run" && cp -R "$EVID/.live-out/shots" "$EVID/lane-2/builder-06-shots-$run" 2>/dev/null || true
  E2E_AUTH=oidc check "$project" --grep @lane2 >"$EVID/lane-2/checker-lane2-$run.log" 2>&1 || own=$?
  grep -E "passed|failed" "$EVID/lane-2/builder-06-oidc-$run.log" "$EVID/lane-2/checker-lane2-$run.log" || true
  echo "builder 06 exit=$builder, checker lane 2 exit=$own"
  [ "$builder" -eq 0 ] && [ "$own" -eq 0 ]
}

lane9() {
  local worktree=$1 project=$2 api_port=$3 out="$EVID/lane-9"
  mkdir -p "$out"
  rm -f "$out/.down-checked" "$out/.api-up"
  compose "$worktree" "$project" dev stop platform-api 2>&1 | tee "$out/stop.log"
  compose "$worktree" "$project" dev ps -a --format '{{.Service}} {{.State}}' | tee "$out/ps-while-down.txt"
  local portal
  portal=$(portal_of "$project")
  docker exec "$portal" wget -qSO- --header "X-Dev-User: alice" http://127.0.0.1:8080/api/v1/me 2>&1 | head -n 5 | tee "$out/me-while-down.txt" || true
  check "$project" --grep @lane9 >"$out/playwright.log" 2>&1 &
  local runner_pid=$!
  # The browser check writes .down-checked once it has seen the message; then the real service comes back.
  for _ in $(seq 1 180); do
    [ -f "$out/.down-checked" ] && break
    kill -0 "$runner_pid" 2>/dev/null || break
    sleep 1
  done
  compose "$worktree" "$project" dev start platform-api 2>&1 | tee "$out/start.log"
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null "http://localhost:$api_port/healthz/ready" && break
    sleep 1
  done
  curl -sS -w " %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$out/ready-after-start.txt"
  touch "$out/.api-up"
  local status=0
  wait "$runner_pid" || status=$?
  cat "$out/playwright.log"
  return "$status"
}

lane10() {
  local worktree=$1 project=$2 out="$EVID/lane-10" dist="$1/portal/dist"
  mkdir -p "$out"
  {
    echo "# Lane 10: retired names in $dist (head $(git -C "$worktree" rev-parse HEAD))"
    echo "## case-insensitive hits per file, with 60 characters either side"
    for pattern in 'room[ _-]?lead' 'release[ _-]?check' 'use[ _-]?case' 'usecase' 'builder' 'flint|forge|striker|spark map|kindling|firebreak|ember'; do
      echo "### /$pattern/"
      grep -rIoiE ".{0,60}($pattern).{0,60}" "$dist" | sed 's/^/  /' || echo "  (none)"
    done
  } >"$out/dist-hits.txt"
  cat "$out/dist-hits.txt"
  local status=0
  check "$project" --grep @lane10 || status=$?
  {
    cat "$out/dist-hits.txt"
    echo
    echo "## page text: every page at 1440 and 390 px, document.title, innerText, aria-label/title/alt/placeholder, with Test controls and Teams open"
    cat "$out/page-hits.txt"
  } >"$out/p1-old-names.txt"
  return "$status"
}

size() {
  local out="$EVID/perf" name dir total
  mkdir -p "$out"
  : >"$out/first-load-js.txt"
  for pair in "trunk:$1" "head:$2"; do
    name=${pair%%:*}
    dir=${pair#*:}/portal/dist
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
  local trunk=$1 head=$2 samples=${3:-5}
  mkdir -p "$EVID/perf"
  rm -f "$EVID"/perf/lcp-*.json
  for i in $(seq 1 "$samples"); do
    TARGET=trunk SAMPLE=$i check "$trunk" --grep @perf
    TARGET=head SAMPLE=$i check "$head" --grep @perf
  done
  node -e '
    const fs = require("fs"), dir = process.argv[1]
    const all = fs.readdirSync(dir).filter((f) => /^lcp-.*\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8")))
    const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)] }
    const lines = []
    for (const target of ["trunk", "head"]) {
      const rows = all.filter((r) => r.target === target).sort((a, b) => a.sample - b.sample)
      lines.push(`${target}: ${rows.map((r) => `#${r.sample} ${r.lcp.toFixed(0)} ms (${r.element})`).join(", ")}`)
      lines.push(`${target} median: ${median(rows.map((r) => r.lcp)).toFixed(0)} ms`)
    }
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
  ' "$EVID/perf"
}

command=${1:-}
[ -n "$command" ] || die "usage: p1.sh <disk|gates|up|down|check|lane1|lane2|lane9|lane10|size|perf> ..."
shift
case "$command" in
  disk | gates | up | down | check | lane1 | lane2 | lane9 | lane10 | size | perf) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
