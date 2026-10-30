#!/usr/bin/env bash
# Checker probes for P13 of docs/design/rebuild-plan.md: New workflow in four steps. Rerun any step on its own.
# Works from a fresh `git archive` export: nothing here needs git, and each e2e folder is mounted on its own.
#
# usage: scripts/checks/p13.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       portal: npm ci when needed, typecheck, lint, unit tests, nginx render, build
#   pygates <worktree>                     both contract generators with empty porcelain; platform-api ruff, pyright,
#                                          lint-imports and its tests on a throwaway PostgreSQL; agent-runtime ruff, pyright,
#                                          tests; the e2e mock model's ruff, pyright and tests
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          --reuse starts a second stack on the images an earlier up built with that tag, and
#                                          builds only this project's own mock images
#   down <worktree> <project>              stops the stack, deletes its volumes and the images it built for itself (down -v --rmi local)
#   check <project> [playwright arguments] run portal/e2e/checks/p13.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run portal/e2e/live, such as 07-new-workflow.live.ts, the same way
#   lane1 <head-project> [trunk-project]   trunk has no New workflow: record it; then alice sets up the follow-up ticket
#                                          workflow at head and finds it on Workflows, on, every weekday at 15:00
#   lane <n> <project>                     lanes 2 to 10, one at a time on the shared stack; each makes its own workflows
#   perf <project>                         ten Plan it presses with the mock model: step 2's rows within 1 s at the median
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript each built dist/index.html loads; fails past +30 KB
#   video <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own stack: the review video of alice setting up a workflow and its test run,
#                                          which bob approves, 30 to 60 s, as $EVID/p13-review.webm and, with ffmpeg, .mp4; down
#
# Every lane but the video runs on one shared dev stack. The first check connects the mock model as the AI model, with
# bob's confirmation, unless it is already the model.
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p13)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
#   PG_PORT           host port of the throwaway PostgreSQL that pygates starts (default 56971)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p13}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
PG_PORT=${PG_PORT:-56971}
PG_NAME=p13-gates-pg
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
GROWTH_LIMIT=30720
PLAN_LIMIT_MS=1000

die() { echo "p13.sh: $*" >&2; exit 2; }

compose() {
  local worktree=$1 project=$2 mode=$3
  shift 3
  local files=(-f "$worktree/deploy/compose.yaml" -f "$worktree/deploy/compose.e2e.yaml")
  [ "$mode" = oidc ] && files+=(-f "$worktree/deploy/compose.oidc.yaml")
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
  [ -d "$worktree/portal/node_modules" ] || (cd "$worktree/portal" && npm ci --no-audit --no-fund) >"$out/npm-ci.log" 2>&1
  (cd "$worktree/portal" && npm run typecheck && npm run lint && npm test) >"$out/typecheck-lint-test.log" 2>&1
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  /usr/bin/grep -E "Test Files|Tests " "$out/typecheck-lint-test.log"
  echo "nginx render checks ok: $(/usr/bin/grep -c '^ok' "$out/nginx-render.log")"
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
  if [ -d "$worktree/.git" ] || [ -f "$worktree/.git" ]; then
    git -C "$worktree" status --porcelain -- contracts >"$out/contracts-porcelain.txt"
    if [ -s "$out/contracts-porcelain.txt" ]; then
      echo "FAIL contracts-porcelain: $(tr '\n' ' ' <"$out/contracts-porcelain.txt")"
      status=1
    else
      echo "PASS contracts-porcelain: git status --porcelain -- contracts is empty"
    fi
  else
    echo "SKIP contracts-porcelain: $worktree is not a git checkout; compare its contracts/ with the export by hand"
  fi
  step pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  step pa-pyright "cd platform-api && uv run pyright"
  step pa-lint-imports "cd platform-api && uv run lint-imports"
  step pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q"
  step pa-new-workflow "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest tests/test_builder_card_service.py tests/test_schedule.py tests/test_migrations.py -q"
  step ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  step ar-pyright "cd agent-runtime && uv run pyright"
  step ar-pytest "cd agent-runtime && uv run pytest -q"
  step e2e-mock-model "cd e2e && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run python -m pytest mock_model -q"
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  return "$status"
}

up() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 build=--build mode=dev option
  shift 6
  for option in "$@"; do
    case "$option" in
      --reuse) build=--no-build ;;
      --oidc) mode=oidc ;;
      *) die "unknown up option $option" ;;
    esac
  done
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  export WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port
  if [ "$build" = --no-build ]; then
    compose "$worktree" "$project" "$mode" build mock-github mock-model >"$EVID/stacks/$project-mocks.log" 2>&1 ||
      { tail -n 30 "$EVID/stacks/$project-mocks.log" >&2; die "$project could not build its mock images"; }
  fi
  compose "$worktree" "$project" "$mode" up "$build" --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  if [ "$mode" = oidc ]; then
    docker exec "$(service_of "$project" portal)" wget -qSO- http://platform-api:8000/healthz/ready 2>&1 | tee "$EVID/stacks/$project-ready.txt"
  else
    curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
  fi
}

down() {
  local worktree=$1 project=$2 mode=dev
  [ "${3:-}" = --oidc ] && mode=oidc
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" "$mode" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" "$mode" --profile e2e down -v --remove-orphans --rmi local
}

service_of() {
  docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=$2" | head -n 1
}

runner_in() {
  local project=$1
  shift
  local portal
  portal=$(service_of "$project" portal)
  [ -n "$portal" ] || die "no running Portal in project $project"
  docker image inspect "$RUNNER" >/dev/null 2>&1 || die "no runner image $RUNNER; build it with E2E_RUNNER_IMAGE=$RUNNER portal/e2e/runner-image.sh"
  mkdir -p "$EVID/.live-out"
  # A fresh export has no portal/e2e/out, and docker can't make a mount point inside a read-only mount.
  local e2e_mounts=() folder
  for folder in checks live support; do
    e2e_mounts+=(-v "$checker_root/portal/e2e/$folder:/work/e2e/$folder:ro")
  done
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH="${E2E_AUTH:-dev}" -e EVID=/evidence \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" \
    -e MOCK_OIDC_URL="${MOCK_OIDC_URL:-http://mock-oidc:8080/default}" \
    -e MOCK_GITHUB_URL=http://mock-github:8200 -e MOCK_MODEL_URL=http://mock-model:8300 -e PLAIN_HTTP_URL=http://portal:8080 \
    "${e2e_mounts[@]}" -v "$EVID:/evidence" -v "$EVID/.live-out:/work/e2e/out/live" \
    -w /work "$RUNNER" "$@"
}

check() {
  local project=$1
  shift
  runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p13.check.ts "$@"
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
    echo "no trunk stack given: on trunk /new is \"Page not found\" and the menu has no New workflow" | tee "$EVID/lane-1/p13-trunk.txt"
  fi
  TARGET=head check "$head" --grep '@lane1 '
}

lane() {
  local n=$1 project=$2
  case "$n" in
    2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10) ;;
    *) die "lane $n is not a shared-stack lane; lane 1 has its own command" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log"
  return "${PIPESTATUS[0]}"
}

perf() {
  local project=$1 status=0
  mkdir -p "$EVID/perf"
  rm -f "$EVID/perf/plan-head.json"
  TARGET=head check "$project" --grep '@perf ' 2>&1 | tee "$EVID/perf/playwright.log" || status=$?
  [ "$status" -eq 0 ] || return "$status"
  node -e '
    const fs = require("fs"), [dir, limit] = process.argv.slice(1)
    const { samples } = JSON.parse(fs.readFileSync(`${dir}/plan-head.json`, "utf8"))
    const sorted = [...samples].sort((a, b) => a - b)
    const median = sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
    const ok = samples.length === 10 && median < Number(limit)
    const line = `${ok ? "PASS" : "FAIL"} Plan it to step 2 with its rows, median of ${samples.length}: ${median.toFixed(0)} ms (${samples.map((v) => v.toFixed(0)).join(", ")}), under ${limit}`
    fs.writeFileSync(`${dir}/summary.txt`, line + "\n")
    console.log(line)
    process.exit(ok ? 0 : 1)
  ' "$EVID/perf" "$PLAN_LIMIT_MS"
}

size() {
  local out="$EVID/perf" name dir total trunk_total=0 head_total=0
  mkdir -p "$out"
  : >"$out/first-load-js.txt"
  for pair in "trunk:$1" "head:$2"; do
    name=${pair%%:*}
    dir=${pair#*:}/portal/dist
    [ -f "$dir/index.html" ] || die "no $dir/index.html; run gates on that worktree first, which builds it"
    total=0
    for src in $(/usr/bin/grep -oE '<(script|link rel="modulepreload")[^>]*(src|href)="[^"]+\.js"' "$dir/index.html" | sed -E 's/.*(src|href)="([^"]+)".*/\2/'); do
      bytes=$(gzip -c "$dir$src" | wc -c | tr -d ' ')
      echo "$name $src gzip=$bytes" | tee -a "$out/first-load-js.txt"
      total=$((total + bytes))
    done
    echo "$name total gzip=$total" | tee -a "$out/first-load-js.txt"
    if [ "$name" = trunk ]; then trunk_total=$total; else head_total=$total; fi
  done
  echo "growth=$((head_total - trunk_total)) bytes (limit $GROWTH_LIMIT; trunk measured from $1)" | tee -a "$out/first-load-js.txt"
  [ $((head_total - trunk_total)) -le "$GROWTH_LIMIT" ]
}

video() {
  local worktree=$1 project=$2 status=0 seconds
  up "$worktree" "$project" "${@:3}"
  mkdir -p "$EVID/review-video"
  check "$project" --grep '@review-video-setup' 2>&1 | tee "$EVID/review-video/setup.log" || status=$?
  [ "$status" -ne 0 ] || check "$project" --grep '@review-video ' 2>&1 | tee "$EVID/review-video/playwright.log" || status=$?
  down "$worktree" "$project"
  [ "$status" -eq 0 ] || return "$status"
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p13-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p13-review.mp4"
  fi
  if command -v ffprobe >/dev/null 2>&1 && [ -f "$EVID/p13-review.mp4" ]; then
    seconds=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$EVID/p13-review.mp4")
    echo "p13-review.mp4 runs $seconds s"
    awk -v s="$seconds" 'BEGIN { exit !(s >= 30 && s <= 60) }' || die "the review video runs $seconds s, not 30 to 60"
  fi
  ls -la "$EVID"/p13-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p13.sh <disk|gates|pygates|up|down|check|live|lane1|lane|perf|size|video> ..."
shift
case "$command" in
  disk | gates | pygates | up | down | check | live | lane1 | lane | perf | size | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
