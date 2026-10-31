#!/usr/bin/env bash
# Checker probes for P6 of docs/design/rebuild-plan.md: the Software watchlist page. Rerun any step on its own.
#
# usage: scripts/checks/p6.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       portal typecheck, lint, unit tests, nginx render, build
#   pygates <worktree>                     both contract generators with empty porcelain; platform-api ruff, pyright,
#                                          lint-imports and its tests on a throwaway PostgreSQL; agent-runtime ruff, pyright, tests
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--no-build]
#                                          --no-build starts a second stack on the images an earlier up built with that tag;
#                                          it builds the mocks with that tag first, for an earlier up from before they had a tag
#   down <worktree> <project>
#   check <project> [playwright arguments] run portal/e2e/checks/p6.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run the builder's live specs (portal/e2e/live) the same way
#   lane1 <head-project> [trunk-project]   add software and check it at head; trunk has no Software watchlist page
#   lane <n> <project>                     lanes 2, 3, 4, 5, 7, 8, 9, 10 and 11, one at a time on a shared stack; lane 3 also moves
#                                          one removal back a day in the stack's PostgreSQL while the page waits, to try a late Undo
#   lane6 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--no-build]
#                                          the mock GitHub fails during a check, on its own stack, which this brings up and down
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript that dist/index.html loads
#   perf <project> [samples]               largest contentful paint, and the time until all 14 rows are painted, median of the samples
#   video <project>                        the review video of adding software and a check, 30 to 60 seconds, as $EVID/p6-review.webm
#                                          and, with ffmpeg, .mp4
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p6)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
#   PG_PORT           host port of the throwaway PostgreSQL that pygates starts (default 55446)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p6}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
PG_PORT=${PG_PORT:-55446}
PG_NAME=p6-gates-pg
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
LATE_REMOVAL_IDS=lane-3/late-removal.txt
LATE_REMOVAL_MOVED=lane-3/late-removal.moved

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
  [ -d "$worktree/portal/node_modules" ] || (cd "$worktree/portal" && npm ci --no-audit --no-fund) >"$out/npm-ci.log" 2>&1
  (cd "$worktree/portal" && npm run typecheck && npm run lint && npm test) >"$out/typecheck-lint-test.log" 2>&1
  (cd "$worktree/portal" && npx vitest run src/screens/software src/shell src/api) >"$out/vitest-run-shell.log" 2>&1
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  grep -E "Test Files|Tests " "$out/typecheck-lint-test.log" "$out/vitest-run-shell.log"
  echo "nginx render checks ok: $(grep -c '^ok' "$out/nginx-render.log")"
  tail -n 1 "$out/nginx-render.log"
}

pygates() {
  local worktree=$1 out="$EVID/gates" status=0
  mkdir -p "$out"
  step() {
    local name=$1
    shift
    if (cd "$worktree" && eval "$*") >"$out/$name.log" 2>&1; then
      echo "PASS $name: $(tail -n 1 "$out/$name.log")"
    else
      echo "FAIL $name (see $out/$name.log): $(tail -n 3 "$out/$name.log" | tr '\n' ' ')"
      status=1
    fi
  }
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_PASSWORD=test -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
  done
  step contracts-generate "(cd platform-api && uv sync --locked && uv run python -m platform_api.contracts ../contracts) && (cd agent-runtime && uv sync --locked && uv run python -m agent_runtime.contracts ../contracts)"
  git -C "$worktree" status --porcelain -- contracts >"$out/contracts-porcelain.txt"
  if [ -s "$out/contracts-porcelain.txt" ]; then
    echo "FAIL contracts-porcelain: $(tr '\n' ' ' <"$out/contracts-porcelain.txt")"
    status=1
  else
    echo "PASS contracts-porcelain: git status --porcelain -- contracts is empty"
  fi
  step pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  step pa-pyright "cd platform-api && uv run pyright"
  step pa-lint-imports "cd platform-api && uv run lint-imports"
  step pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q"
  step ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  step ar-pyright "cd agent-runtime && uv run pyright"
  step ar-pytest "cd agent-runtime && uv run pytest -q"
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  return "$status"
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
  [ "$build" = --build ] || build_the_mock_images "$worktree" "$project" "$tag"
  WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port \
    compose "$worktree" "$project" up "$build" --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
}

# The mocks carry the stack's tag, so this builds wab/mock-github:<tag> and wab/mock-model:<tag>, never :dev.
build_the_mock_images() {
  local worktree=$1 project=$2 tag=$3
  WAB_IMAGE_TAG=$tag compose "$worktree" "$project" build mock-github mock-model >"$EVID/stacks/$project-build-mocks.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-build-mocks.log" >&2; die "$project could not build its mock images"; }
}

down() {
  local worktree=$1 project=$2
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" --profile e2e down -v --remove-orphans
}

service_of() {
  docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=$2" | head -n 1
}

portal_of() { service_of "$1" portal; }

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
    -e LATE_REMOVAL_IDS="${LATE_REMOVAL_IDS_IN_RUNNER:-}" -e LATE_REMOVAL_MOVED="/evidence/$LATE_REMOVAL_MOVED" \
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
  local n=$1 project=$2 status=0
  case "$n" in
    2 | 3 | 4 | 5 | 7 | 8 | 9 | 10 | 11) ;;
    *) die "lane $n does not run on a shared stack; see lane1 and lane6" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log" || status=$?
  if [ "$n" = 3 ]; then
    undo_after_the_removal_is_moved_back_a_day "$project" || status=$?
  fi
  return "$status"
}

undo_after_the_removal_is_moved_back_a_day() {
  local project=$1 dir="$EVID/lane-3" ids="$EVID/$LATE_REMOVAL_IDS" moved="$EVID/$LATE_REMOVAL_MOVED" pg pid uc sw status=0
  pg=$(service_of "$project" postgres)
  [ -n "$pg" ] || die "no running PostgreSQL in project $project"
  mkdir -p "$dir"
  rm -f "$ids" "$moved"
  LATE_REMOVAL_IDS_IN_RUNNER="/evidence/$LATE_REMOVAL_IDS" check "$project" --grep "@lane3-day " >"$dir/playwright-day.log" 2>&1 &
  pid=$!
  for _ in $(seq 1 180); do
    [ -f "$ids" ] && break
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  uc=$(sed -n 's/^use_case_id=\([A-Za-z0-9_]*\)$/\1/p' "$ids" 2>/dev/null || true)
  sw=$(sed -n 's/^software_id=\([A-Za-z0-9_]*\)$/\1/p' "$ids" 2>/dev/null || true)
  if [ -n "$uc" ] && [ -n "$sw" ]; then
    docker exec -i "$pg" psql -U postgres -d platform -v ON_ERROR_STOP=1 -v uc="$uc" -v sw="$sw" >"$dir/late-removal.sql.log" 2>&1 <<'SQL' || true
UPDATE builder.use_case_versions SET created_at = created_at - interval '25 hours'
WHERE use_case_id = :'uc' AND version = (
  SELECT max(version) + 1 FROM builder.watched_software WHERE use_case_id = :'uc' AND software_id = :'sw'
);
SQL
    if grep -qx 'UPDATE 1' "$dir/late-removal.sql.log"; then
      touch "$moved"
    else
      echo "lane 3: the removal was not moved back; see $dir/late-removal.sql.log" >&2
      status=1
    fi
  else
    echo "lane 3: the page wrote no $LATE_REMOVAL_IDS with a use case and a software" >&2
    status=1
  fi
  wait "$pid" || status=$?
  cat "$dir/playwright-day.log"
  return "$status"
}

lane6() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 status=0
  up "$worktree" "$project" "$tag" "$portal_port" "$api_port" "$n8n_port" "${7:-}"
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
    const medianOf = (values) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]
    const median = medianOf(rows.map((r) => r.lcp))
    const rowsMedian = medianOf(rows.map((r) => r.rowsAt))
    const pass = median < 2500 && rowsMedian < 2500
    const lines = [
      `head: ${rows.map((r) => `#${r.sample} ${r.lcp.toFixed(0)} ms (${r.element}), all rows ${r.rowsAt.toFixed(0)} ms`).join(", ")}`,
      `head median: ${median.toFixed(0)} ms; all 14 rows painted, median: ${rowsMedian.toFixed(0)} ms`,
      `rule: both under 2500 ms: ${pass ? "PASS" : "FAIL"}`,
    ]
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    process.exit(pass ? 0 : 1)
  ' "$EVID/perf"
}

video() {
  local project=$1 seconds
  check "$project" --grep @review-video
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p6-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p6-review.mp4"
  fi
  if command -v ffprobe >/dev/null 2>&1 && [ -f "$EVID/p6-review.mp4" ]; then
    seconds=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$EVID/p6-review.mp4")
    echo "p6-review.mp4 runs $seconds s"
    awk -v s="$seconds" 'BEGIN { exit !(s >= 30 && s <= 60) }' || die "the review video runs $seconds s, not 30 to 60"
  fi
  ls -la "$EVID"/p6-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p6.sh <disk|gates|pygates|up|down|check|live|lane1|lane|lane6|size|perf|video> ..."
shift
case "$command" in
  disk | gates | pygates | up | down | check | live | lane1 | lane | lane6 | size | perf | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
