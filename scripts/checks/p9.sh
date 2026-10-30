#!/usr/bin/env bash
# Checker probes for P9 of docs/design/rebuild-plan.md: the Workflows list and the workflow page. Rerun any step on its own.
# Works from a fresh `git archive` export: nothing here needs git, and each e2e folder is mounted on its own.
# The checks run from this script's own tree, whatever stack they point at, so a trunk stack is checked with this head
# copy: trunk has no p9.sh or p9.check.ts.
#
# usage: scripts/checks/p9.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       npm ci when needed, typecheck, lint, unit tests, nginx render, build
#   pygates <worktree>                     both contract generators change nothing in contracts/; platform-api ruff, pyright,
#                                          lint-imports and its tests on a throwaway PostgreSQL ($PG_NAME on $PG_PORT, removed
#                                          after); agent-runtime ruff, pyright and tests
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          --reuse starts a second stack on the images an earlier up built with that tag;
#                                          it still builds this project's mock-github and mock-model, which have no tag
#   down <worktree> <project> [<tag>]      stops the stack, deletes its volumes (down -v), and removes the images named after
#                                          the project (mock-github, mock-model, e2e) and its dangling ones; with a tag, also
#                                          wab/*:<tag> unless another stack still uses them
#   check <project> [playwright arguments] run portal/e2e/checks/p9.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run portal/e2e/live, such as 04-workflows.live.ts, the same way
#   lane1 <head-project> [trunk-project]   trunk has no Workflows page: record it; then two seeded rows at head
#   lane <n> <project>                     lanes 2, 3, 5, 6, 7, 9 and 10, one at a time on a shared stack. Lane 9 also lists
#                                          each check axe could not decide in lane-9/p9-axe-undecided.txt, for a person to read
#   lane4 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          lane 4 brings up its own stack, writes a schedule into orchestration.schedules
#                                          with psql, and takes it down with its images (and the tag's, unless --reuse)
#   lane8 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          lane 8 brings up its own stack, stops mock-model before the run, and takes it down
#                                          with its images (and the tag's, unless --reuse)
#   probes <project>                       the checker's probes: focus from every page at 1440 and 390 px, presses on a
#                                          workflow someone else paused, resumed or deleted, the watchlist and its Resume on the
#                                          Software page, roles, own runs, Delete and Undo, messages, reduced motion, and
#                                          retired words in the pages and in every message a press brings
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript each built dist/index.html loads; fails past +30 KB
#   perf <project> [samples]               largest contentful paint of a workflow page with 20 runs; fails at a median of 2.5 s or more
#   video <project>                        the review video, as $EVID/p9-review.webm and, with ffmpeg, .mp4
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p9)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
#   PG_NAME           container name of the throwaway PostgreSQL that pygates starts (default p9-gates-pg)
#   PG_PORT           its host port (default 56940)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p9}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
GROWTH_LIMIT=30720
PG_NAME=${PG_NAME:-p9-gates-pg}
PG_PORT=${PG_PORT:-56940}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3

die() { echo "p9.sh: $*" >&2; exit 2; }

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
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  /usr/bin/grep -E "Test Files|Tests " "$out/typecheck-lint-test.log"
  echo "nginx render checks ok: $(/usr/bin/grep -c '^ok' "$out/nginx-render.log")"
  tail -n 1 "$out/nginx-render.log"
  tail -n 8 "$out/build-head.log"
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
  rm -rf "$out/contracts-before"
  cp -R "$worktree/contracts" "$out/contracts-before"
  step contracts-generate "(cd platform-api && uv sync --locked && uv run python -m platform_api.contracts ../contracts) && (cd agent-runtime && uv sync --locked && uv run python -m agent_runtime.contracts ../contracts)"
  if diff -r "$out/contracts-before" "$worktree/contracts" >"$out/contracts-diff.txt"; then
    echo "PASS contracts-unchanged: both generators wrote what contracts/ already held"
  else
    echo "FAIL contracts-unchanged (see $out/contracts-diff.txt): $(head -n 3 "$out/contracts-diff.txt" | tr '\n' ' ')"
    status=1
  fi
  step pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  step pa-pyright "cd platform-api && uv run pyright"
  step pa-lint-imports "cd platform-api && uv run lint-imports"
  step pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q"
  step ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  step ar-pyright "cd agent-runtime && uv run pyright"
  step ar-pytest "cd agent-runtime && uv run pytest -q"
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  echo "throwaway PostgreSQL $PG_NAME removed: $(docker ps -aq --filter "name=^$PG_NAME\$" | wc -l | tr -d ' ') left"
  return "$status"
}

up() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 build=--build
  case "${7:-}" in
    '') ;;
    --reuse) build=--no-build ;;
    *) die "unknown up option $7" ;;
  esac
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  export WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port
  if [ "$build" = --no-build ]; then
    compose "$worktree" "$project" build mock-github mock-model >"$EVID/stacks/$project-mocks.log" 2>&1 ||
      { tail -n 30 "$EVID/stacks/$project-mocks.log" >&2; die "$project could not build its mock images"; }
  fi
  compose "$worktree" "$project" up "$build" --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
}

down() {
  local worktree=$1 project=$2 tag=${3:-} image
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" --profile e2e down -v --remove-orphans
  docker image ls --format '{{.Repository}}:{{.Tag}}' --filter "reference=$project-*" | while read -r image; do
    docker image rm "$image" >/dev/null || echo "kept $image, which a container still uses"
  done
  docker image prune -f --filter "label=com.docker.compose.project=$project" >/dev/null
  if [ -n "$tag" ]; then
    for image in wab/platform-api wab/agent-runtime wab/portal; do
      docker image inspect "$image:$tag" >/dev/null 2>&1 || continue
      docker image rm "$image:$tag" >/dev/null 2>&1 || echo "kept $image:$tag, which another stack still uses"
    done
  fi
  echo "images named after $project left: $(docker image ls -q --filter "reference=$project-*" | wc -l | tr -d ' ')"
}

built_tag() {
  if [ "${2:-}" = --reuse ]; then echo ''; else echo "$1"; fi
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
  # A fresh export has no portal/e2e/out, and docker can't make a mount point inside a read-only mount.
  local e2e_mounts=() folder
  for folder in checks live support; do
    e2e_mounts+=(-v "$checker_root/portal/e2e/$folder:/work/e2e/$folder:ro")
  done
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH=dev -e EVID=/evidence \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" \
    -e MOCK_GITHUB_URL=http://mock-github:8200 -e MOCK_MODEL_URL=http://mock-model:8300 -e PLAIN_HTTP_URL=http://portal:8080 \
    "${e2e_mounts[@]}" -v "$EVID:/evidence" -v "$EVID/.live-out:/work/e2e/out/live" \
    -w /work "$RUNNER" "$@"
}

check() {
  local project=$1
  shift
  runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p9.check.ts "$@"
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
    echo "no trunk stack given: on trunk /workflows is the shell's empty page, \"This page is not built yet.\"" | tee "$EVID/lane-1/p9-trunk.txt"
  fi
  TARGET=head check "$head" --grep '@lane1 '
}

lane() {
  local n=$1 project=$2
  case "$n" in
    2 | 3 | 5 | 6 | 7 | 9 | 10) ;;
    *) die "lane $n does not run on a shared stack; see lane1, lane4 and lane8" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log"
  return "${PIPESTATUS[0]}"
}

json_field() {
  node -e 'let raw = ""; process.stdin.on("data", (c) => (raw += c)).on("end", () => console.log(JSON.parse(raw)[process.argv[1]]))' "$1"
}

schedule_agent_workflow_in_database() {
  local worktree=$1 project=$2 api_port=$3 out="$EVID/lane-4" name made id
  name="p9 lane4 scheduled $(date +%H%M%S)"
  made=$(curl -sS -X POST -H 'X-Dev-User: alice' -H 'Content-Type: application/json' \
    -d "{\"name\": \"$name\", \"instruction\": \"Check LangGraph for a new release and raise a ticket in MOCK.\", \"agents\": [{\"card_id\": \"crd_version_checker\", \"values\": {\"GitHub repository\": \"langchain-ai/langgraph\", \"Jira project\": \"MOCK\"}}]}" \
    "http://localhost:$api_port/api/v1/agent-use-cases")
  id=$(printf '%s' "$made" | json_field use_case_id)
  [ -n "$id" ] && [ "$id" != undefined ] || die "alice could not make the lane 4 workflow: $made"
  compose "$worktree" "$project" exec -T postgres psql -U postgres -d platform -v ON_ERROR_STOP=1 -c \
    "insert into orchestration.schedules (use_case_id, day, at, time_zone, owner_id, owner_name, saved_at) values ('$id', 'monday', '09:00', 'Asia/Singapore', 'alice', 'Alice', now())" \
    >"$out/schedule-insert.log" 2>&1 || { cat "$out/schedule-insert.log" >&2; die "could not write the lane 4 schedule"; }
  compose "$worktree" "$project" exec -T postgres psql -U postgres -d platform -Atc \
    "select use_case_id||' '||day||' '||at||' '||time_zone||' '||owner_id from orchestration.schedules where use_case_id = '$id'" >"$out/schedule-row.txt"
  printf '{"id": "%s", "name": "%s", "schedule": "written into orchestration.schedules with psql, because no route gives an agent workflow a schedule: Mondays at 09:00 Singapore time, owned by alice"}\n' "$id" "$name" >"$out/workflow.json"
  cat "$out/workflow.json"
}

lane4() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 status=0
  up "$worktree" "$project" "$tag" "$portal_port" "$api_port" "$n8n_port" ${7:+"$7"}
  mkdir -p "$EVID/lane-4"
  schedule_agent_workflow_in_database "$worktree" "$project" "$api_port" || status=$?
  [ "$status" -ne 0 ] || check "$project" --grep '@lane4 ' 2>&1 | tee "$EVID/lane-4/playwright.log" || status=$?
  down "$worktree" "$project" "$(built_tag "$tag" "${7:-}")"
  return "$status"
}

lane8() {
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6 status=0
  up "$worktree" "$project" "$tag" "$portal_port" "$api_port" "$n8n_port" ${7:+"$7"}
  mkdir -p "$EVID/lane-8"
  check "$project" --grep '@lane8-setup' 2>&1 | tee "$EVID/lane-8/setup.log" || status=$?
  if [ "$status" -eq 0 ]; then
    compose "$worktree" "$project" stop mock-model | tee "$EVID/lane-8/mock-model-stopped.txt"
    check "$project" --grep '@lane8 ' 2>&1 | tee "$EVID/lane-8/playwright.log" || status=$?
  fi
  down "$worktree" "$project" "$(built_tag "$tag" "${7:-}")"
  return "$status"
}

probes() {
  local project=$1
  mkdir -p "$EVID/safety" "$EVID/probe-focus"
  check "$project" --grep '@focus |@stale |@watchlist |@watchlist-resume |@roles |@own-run |@delete-undo |@toast |@reduced |@words ' 2>&1 | tee "$EVID/safety/playwright.log"
  return "${PIPESTATUS[0]}"
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
    for src in $(/usr/bin/grep -oE '<script[^>]*src="[^"]+"' "$dir/index.html" | sed -E 's/.*src="([^"]+)".*/\1/'); do
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
    const middle = (values) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]
    const median = middle(rows.map((r) => r.lcp))
    const drawn = middle(rows.map((r) => r.runsDrawnAt))
    const lines = [`head: ${rows.map((r) => `#${r.sample} ${r.lcp.toFixed(0)} ms (${r.element}, ${r.runsShown} runs shown, run list drawn at ${r.runsDrawnAt.toFixed(0)} ms)`).join(", ")}`, `head median: ${median.toFixed(0)} ms; run list drawn, median: ${drawn.toFixed(0)} ms`, `rule: under 2500 ms: ${median < 2500 ? "PASS" : "FAIL"}`, "trunk has no workflow page, so its paint is not measured"]
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    process.exit(median < 2500 ? 0 : 1)
  ' "$EVID/perf"
}

video() {
  local project=$1
  check "$project" --grep @review-video
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p9-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p9-review.mp4"
  fi
  ls -la "$EVID"/p9-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p9.sh <disk|gates|pygates|up|down|check|live|lane1|lane|lane4|lane8|probes|size|perf|video> ..."
shift
case "$command" in
  disk | gates | pygates | up | down | check | live | lane1 | lane | lane4 | lane8 | probes | size | perf | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
