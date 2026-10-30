#!/usr/bin/env bash
# Checker probes for P11 of docs/design/rebuild-plan.md: Home with what needs you. Rerun any step on its own.
# Works from a fresh `git archive` export: nothing here needs git, and each e2e folder is mounted on its own.
#
# usage: scripts/checks/p11.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       portal: npm ci when needed, typecheck, lint, unit tests, nginx render, build
#   pygates <worktree>                     both contract generators with empty porcelain; platform-api ruff, pyright,
#                                          lint-imports and its tests on a throwaway PostgreSQL ($PG_NAME on $PG_PORT, removed
#                                          after); agent-runtime ruff, pyright, tests
#   up <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse] [--oidc]
#                                          --reuse starts a second stack on the images an earlier up built with that tag, and
#                                          builds only this project's own mock images; --oidc adds deploy/compose.oidc.yaml,
#                                          which publishes no host port
#   down <worktree> <project> [--oidc] [<tag>]
#                                          stops the stack, deletes its volumes (down -v), and removes the images named after
#                                          the project (mock-github, mock-model, e2e) and its dangling ones; with a tag, also
#                                          wab/*:<tag> unless another stack still uses them. Without a tag the tag's images
#                                          stay, so a later up --reuse still finds them
#   check <project> [playwright arguments] run portal/e2e/checks/p11.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run portal/e2e/live, such as 06-home.live.ts, the same way
#   lane1 <head-project> [trunk-project]   trunk's Home is the P1 empty page: record it; then bob's first item at head
#   lane <n> <project>                     lanes 2, 3, 6, 8 and 9, one at a time on a shared stack
#   lane4 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own stack: the mock GitHub fails a check alice started; Retry on Home; down
#   lane5 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own stack, as it changes the People list: alice asks for carol as an Approver; down
#   lane7 <worktree> <project> <tag> [--reuse]
#                                          its own oidc stack: alice adds erin as an Operator, erin signs in to day one, and
#                                          axe checks erin's Home at 1440 and 390 px (lane 9's second half); down
#   lane10 <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own stack: one waiting run copied to 50 with psql, Home as bob, then the perf
#                                          probe on the same 50 runs; down
#   lane10-on <worktree> <project> <api-port>
#                                          lane 10 and the perf box on a head stack that is already up, which stays up
#   perf-trunk <trunk-worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own trunk stack with the same 50 waiting runs: GET /api/v1/runs p95 for the
#                                          baseline; run it before lane10 so the rule can compare; down
#   perf-trunk-on <trunk-worktree> <project> <api-port>
#                                          the same on a trunk stack that is already up, such as lane 1's, which stays up
#   judge_perf                             reads $EVID/perf and says PASS or FAIL for each perf rule
#   probes <project>                       the checker's probes on a shared head stack, after the lanes: focus after a menu
#                                          move to Home, a run on a workflow someone else owns, two Approvers one after the
#                                          other, a workflow deleted while its run waits (recorded only), who sees a stopped
#                                          run and a retried one, and a new AI model address (declined again at the end)
#
# Each own-stack lane takes its stack down with the images named after its project, and with the tag's images only when
# it built them (no --reuse). So run the lanes with --reuse while the stack that built the tag is up, or keep the images
# with a down that names no tag.
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript each built dist/index.html loads; fails past +30 KB
#   video <worktree> <project> <tag> <portal-port> <api-port> <n8n-port> [--reuse]
#                                          its own stack: the review video of bob deciding from Home and alice's stopped run,
#                                          30 to 60 s, as $EVID/p11-review.webm and, with ffmpeg, .mp4; down
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p11)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
#   PG_NAME           container name of the throwaway PostgreSQL that pygates starts (default p11-gates-pg)
#   PG_PORT           its host port (default 56940)
#   PERF_SAMPLES      Home loads for the paint probe (default 5); P95_COUNT requests per route (default 500)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p11}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
PG_NAME=${PG_NAME:-p11-gates-pg}
PG_PORT=${PG_PORT:-56940}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
PERF_SAMPLES=${PERF_SAMPLES:-5}
P95_COUNT=${P95_COUNT:-500}
GROWTH_LIMIT=30720
SEED_COPIES=49

die() { echo "p11.sh: $*" >&2; exit 2; }

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
  step pa-home "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest tests/test_home.py -q"
  step ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  step ar-pyright "cd agent-runtime && uv run pyright"
  step ar-pytest "cd agent-runtime && uv run pytest -q"
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  echo "throwaway PostgreSQL $PG_NAME removed: $(docker ps -aq --filter "name=^$PG_NAME\$" | wc -l | tr -d ' ') left"
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
  local worktree=$1 project=$2 mode=dev tag='' option image
  shift 2
  for option in "$@"; do
    case "$option" in
      --oidc) mode=oidc ;;
      '') ;;
      *) tag=$option ;;
    esac
  done
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" "$mode" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" "$mode" --profile e2e down -v --remove-orphans
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
  local tag=$1 option
  shift
  for option in "$@"; do
    [ "$option" != --reuse ] || return 0
  done
  echo "$tag"
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
  runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p11.check.ts "$@"
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
    echo "no trunk stack given: on trunk / is the P1 empty page, \"This page is not built yet.\"" | tee "$EVID/lane-1/p11-trunk.txt"
  fi
  TARGET=head check "$head" --grep '@lane1 '
}

lane() {
  local n=$1 project=$2
  case "$n" in
    2 | 3 | 6 | 8 | 9) ;;
    *) die "lane $n does not run on a shared stack; see lane1, lane4, lane5, lane7 and lane10" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log"
  return "${PIPESTATUS[0]}"
}

own_stack() {
  local lane=$1 grep=$2 worktree=$3 project=$4 status=0
  shift 4
  up "$worktree" "$project" "$@"
  mkdir -p "$EVID/lane-$lane"
  check "$project" --grep "$grep" 2>&1 | tee "$EVID/lane-$lane/playwright.log" || status=$?
  down "$worktree" "$project" "$(built_tag "$@")"
  return "$status"
}

lane4() { own_stack 4 '@lane4 ' "$@"; }

lane5() { own_stack 5 '@lane5 ' "$@"; }

lane7() {
  local worktree=$1 project=$2 tag=$3 status=0
  up "$worktree" "$project" "$tag" 0 0 0 --oidc ${4:+"$4"}
  mkdir -p "$EVID/lane-7" "$EVID/lane-9"
  E2E_AUTH=oidc check "$project" --grep '@lane7-oidc' 2>&1 | tee "$EVID/lane-7/playwright.log" || status=$?
  down "$worktree" "$project" --oidc "$(built_tag "$tag" ${4:+"$4"})"
  return "$status"
}

seed_waiting() {
  local worktree=$1 project=$2 run=$3 out=$4
  compose "$worktree" "$project" dev exec -T postgres psql -U postgres -d platform -v ON_ERROR_STOP=1 \
    -v run="$run" -v copies="$SEED_COPIES" <"$here/p11_seed_waiting.sql" >"$out/seed.log" 2>&1 ||
    { cat "$out/seed.log" >&2; die "could not copy the waiting run"; }
  tail -n 3 "$out/seed.log"
}

json_field() {
  node -e 'let raw = ""; process.stdin.on("data", (c) => (raw += c)).on("end", () => console.log(JSON.parse(raw)[process.argv[1]]))' "$1"
}

fifty_waiting() {
  local worktree=$1 project=$2 out=$3 run
  check "$project" --grep '@lane10-setup' 2>&1 | tee "$out/setup.log"
  run=$(json_field runId <"$EVID/lane-10/seed.json")
  [ -n "$run" ] && [ "$run" != undefined ] || die "the setup wrote no run id to $EVID/lane-10/seed.json"
  seed_waiting "$worktree" "$project" "$run" "$out"
}

p95() {
  local api_port=$1 user=$2 route=$3 out=$4
  python3 "$checker_root/scripts/p95.py" "http://localhost:$api_port" GET "$route" "$out" --count "$P95_COUNT" --user "$user" --warm-up 20
}

lane10-on() {
  local worktree=$1 project=$2 api_port=$3 status=0 i
  mkdir -p "$EVID/lane-10" "$EVID/perf"
  fifty_waiting "$worktree" "$project" "$EVID/lane-10" || status=$?
  if [ "$status" -eq 0 ]; then
    check "$project" --grep '@lane10 ' 2>&1 | tee "$EVID/lane-10/playwright.log" || status=$?
    p95 "$api_port" bob /api/v1/home "$EVID/perf/p95-home-head.json" || status=$?
    p95 "$api_port" alice /api/v1/runs "$EVID/perf/p95-runs-head.json" || status=$?
    rm -f "$EVID"/perf/lcp-*.json
    for i in $(seq 1 "$PERF_SAMPLES"); do
      TARGET=head SAMPLE=$i check "$project" --grep @perf || status=$?
    done
    judge_perf || status=$?
  fi
  return "$status"
}

lane10() {
  local worktree=$1 project=$2 api_port=$5 status=0
  up "$worktree" "$project" "${@:3}"
  lane10-on "$worktree" "$project" "$api_port" || status=$?
  down "$worktree" "$project" "$(built_tag "${@:3}")"
  return "$status"
}

perf-trunk-on() {
  local worktree=$1 project=$2 api_port=$3 status=0
  mkdir -p "$EVID/perf-trunk" "$EVID/perf"
  fifty_waiting "$worktree" "$project" "$EVID/perf-trunk" || status=$?
  [ "$status" -ne 0 ] || p95 "$api_port" alice /api/v1/runs "$EVID/perf/p95-runs-trunk.json" || status=$?
  return "$status"
}

perf-trunk() {
  local worktree=$1 project=$2 api_port=$5 status=0
  up "$worktree" "$project" "${@:3}"
  perf-trunk-on "$worktree" "$project" "$api_port" || status=$?
  down "$worktree" "$project" "$(built_tag "${@:3}")"
  return "$status"
}

probes() {
  local project=$1
  mkdir -p "$EVID/probes"
  check "$project" --grep '@focus-home |@owner |@two-step |@deleted |@stopped-who |@model-confirm ' 2>&1 | tee "$EVID/probes/playwright.log"
  return "${PIPESTATUS[0]}"
}

judge_perf() {
  node -e '
    const fs = require("fs"), dir = process.argv[1]
    const read = (name) => (fs.existsSync(`${dir}/${name}`) ? JSON.parse(fs.readFileSync(`${dir}/${name}`, "utf8")) : null)
    const home = read("p95-home-head.json"), runs = read("p95-runs-head.json"), trunk = read("p95-runs-trunk.json")
    const paints = fs.readdirSync(dir).filter((f) => /^lcp-head-.*\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8")))
    const lcps = paints.map((p) => p.lcp).sort((a, b) => a - b)
    const median = lcps[Math.floor(lcps.length / 2)]
    const growth = trunk && runs ? runs.p95_ms / trunk.p95_ms - 1 : null
    const checks = [
      [`GET /api/v1/home p95 with 50 waiting runs: ${home?.p95_ms} ms, under 250`, home !== null && home.p95_ms < 250],
      [growth === null ? "GET /api/v1/runs p95: no trunk number; run perf-trunk first" : `GET /api/v1/runs p95: trunk ${trunk.p95_ms} ms, head ${runs.p95_ms} ms, growth ${(growth * 100).toFixed(1)} %, at most 20`, growth !== null && growth <= 0.2],
      [`Home largest contentful paint, median of ${lcps.length}: ${median?.toFixed(0)} ms (${lcps.map((v) => v.toFixed(0)).join(", ")}), under 2500`, median !== undefined && median < 2500],
    ]
    const lines = checks.map(([words, ok]) => `${ok ? "PASS" : "FAIL"} ${words}`)
    fs.writeFileSync(`${dir}/summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    process.exit(checks.every(([, ok]) => ok) ? 0 : 1)
  ' "$EVID/perf"
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

video() {
  local worktree=$1 project=$2 status=0 seconds
  up "$worktree" "$project" "${@:3}"
  mkdir -p "$EVID/review-video"
  check "$project" --grep '@review-video-setup' 2>&1 | tee "$EVID/review-video/setup.log" || status=$?
  [ "$status" -ne 0 ] || check "$project" --grep '@review-video ' 2>&1 | tee "$EVID/review-video/playwright.log" || status=$?
  down "$worktree" "$project" "$(built_tag "${@:3}")"
  [ "$status" -eq 0 ] || return "$status"
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p11-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p11-review.mp4"
  fi
  if command -v ffprobe >/dev/null 2>&1 && [ -f "$EVID/p11-review.mp4" ]; then
    seconds=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$EVID/p11-review.mp4")
    echo "p11-review.mp4 runs $seconds s"
    awk -v s="$seconds" 'BEGIN { exit !(s >= 30 && s <= 60) }' || die "the review video runs $seconds s, not 30 to 60"
  fi
  ls -la "$EVID"/p11-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p11.sh <disk|gates|pygates|up|down|check|live|lane1|lane|lane4|lane5|lane7|lane10|lane10-on|perf-trunk|perf-trunk-on|judge_perf|probes|size|video> ..."
shift
case "$command" in
  disk | gates | pygates | up | down | check | live | lane1 | lane | lane4 | lane5 | lane7 | lane10 | lane10-on | perf-trunk | perf-trunk-on | judge_perf | probes | size | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
