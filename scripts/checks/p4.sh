#!/usr/bin/env bash
# Checker probes for P4 of the rebuild plan (the activity log's copy in Cosmos DB). Rerun any step
# on its own. The lanes themselves are in p4_lanes.py, standard library only.
#
# usage: scripts/checks/p4.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under $DISK_MIN_MB
#   export <sha> <dir>                     git archive of one commit of $SOURCE_REPO into <dir>, with $ENV_FILE as deploy/.env
#   pg-up | pg-down                        the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   cosmos-up | cosmos-down                an emulator for the platform-api tests (host port $COSMOS_PORT)
#   gates <worktree>                       platform-api's CI gates with the Cosmos DB tests required
#   build <src> <project>                  builds one stack's images, nothing started
#   up <src> <project> <portal> <api> <n8n>    one dev stack: build (unless NO_BUILD=1), then up
#   down <src> <project>                   logs, then down -v
#   lane1 <trunk-src> <head-src>           trunk and head stacks ($PREFIX-trunk, $PREFIX), lane 1
#   lane <2|3|7>                           a lane on the shared head stack $PREFIX, from $HEAD_SRC
#   lane4 | lane5 | lane6 | lane8 | lane9 | lane10 | lane11 | lane12 <head-src>
#                                          a lane on its own stack $PREFIX-l<n>
#   perf <trunk-src> <head-src> [rounds]   p95.py --stream in both shared stacks, interleaved
#   perf-table <dir>                       the medians and the rule: head under 1 s and at most trunk + 500 ms
#   cleanup                                removes the images this script made: its tags, its
#                                          projects' compose images, and the emulator image
#                                          only when this script pulled it
#
# Order:
#   p4.sh export <trunk-sha> $EVID/trunk && p4.sh export <head-sha> $EVID/head
#   p4.sh pg-up && p4.sh cosmos-up && p4.sh gates <head-worktree>
#   p4.sh up $EVID/head p4-check 44000 44001 44002     (builds the head images, then starts them)
#   p4.sh lane1 $EVID/trunk $EVID/head                  (builds trunk's images, starts $PREFIX-trunk)
#   p4.sh lane 2; p4.sh lane 3; p4.sh lane 7
#   p4.sh lane4 $EVID/head ... p4.sh lane12 $EVID/head  (own stacks on the head images that `up`
#                                                        or `build` made, each downed after)
#   p4.sh perf $EVID/trunk $EVID/head
#   p4.sh down $EVID/head p4-check; STACK_TAG=p4check-trunk p4.sh down $EVID/trunk p4-check-trunk
# Lane 8 builds a small libfaketime layer on the head image, which needs apt's network. It moves
# only platform-api's clock, which stamps the run's events and the decision.
# Lane 11 logs a backlog of $LANE11_EVENTS agent events and waits for its copy, then makes the
# emulator again while platform-api runs and nothing is logged, then starts a run. It samples
# readiness from before the emulator comes back, and needs one "behind" while the copy is short.
# Lane 12 runs down without -v, then up. Every `up` builds first and starts with --no-build, so
# PRUNE=1 (or a `docker builder prune -af` by hand, then NO_BUILD=1) frees the build cache between.
# Own-stack lanes reuse the head images, the mocks included: every stack names its mock images
# wab/mock-github:<tag> and wab/mock-model:<tag> through a generated overlay.
# Everything runs from a git archive export of this tree too: only `export` needs a git repository.
#
# Environment (defaults in brackets):
#   EVID [/tmp/swarm-p4]      evidence folder
#   ENV_FILE [$EVID/env/.env] compose env file; copy deploy/make-env.sh next to it and run it
#   PREFIX [p4-check]         compose project prefix
#   TAG [p4check]             image tag of the head build; TRUNK_TAG [p4check-trunk]
#   SOURCE_REPO [this tree]   the git repository `export` archives from
#   PORTS [44000]             the head stack's first host port: portal, then platform-api, then n8n
#   TRUNK_PORTS [44010]       the same for the trunk stack
#   LANE_PORTS [44020]        the same for lane 4's own stack; each next own-stack lane adds 10
#                             (lane5 44030, lane6 44040, lane8 44050, lane9 44060 with its second
#                             platform-api on 44063, lane10 44070, lane11 44080, lane12 44090).
#                             Every stack takes 4 ports; the script stops if two stacks overlap,
#                             or overlap PG_PORT or the COSMOS ports.
#   PG_NAME [p4-check-pg]  PG_PORT [55441]
#   COSMOS_NAME [p4-check-cosmos]  COSMOS_PORT [58081]  COSMOS_HEALTH_PORT [58080]
#   DISK_CONTAINER [wab-postgres-1]   a running container on the Docker VM's disk
#   DISK_MIN_MB [1431]        the floor in MiB (1431 MiB is 1.5 GB); the emulator image takes 1.61 GB
#   PULL_MIN_MB [2385]        the floor in MiB (2.5 GB) before a command pulls the emulator image
#   PRUNE [0]                 1 runs `docker builder prune -af` between build and up
#   HEAD_SRC [$EVID/head]     the exported head tree, for lane 2, 3 and 7
#   OVERLAYS                  extra compose files ("-f a.yaml -f b.yaml") for every stack and lane
#   LANE5_EVENTS [4000]       lane 5's backlog; raise it when the kill lands after the copy ends
#   LANE11_EVENTS [4000]      lane 11's backlog; raise it when no sample sees the copy made again
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p4}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PREFIX=${PREFIX:-p4-check}
TAG=${TAG:-p4check}
TRUNK_TAG=${TRUNK_TAG:-p4check-trunk}
PORTS=${PORTS:-44000}
TRUNK_PORTS=${TRUNK_PORTS:-44010}
LANE_PORTS=${LANE_PORTS:-44020}
LANE_STEP=10
STACK_WIDTH=4
PG_NAME=${PG_NAME:-p4-check-pg}
PG_PORT=${PG_PORT:-55441}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
COSMOS_NAME=${COSMOS_NAME:-p4-check-cosmos}
COSMOS_PORT=${COSMOS_PORT:-58081}
COSMOS_HEALTH_PORT=${COSMOS_HEALTH_PORT:-58080}
COSMOS_IMAGE=mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview@sha256:db53613dae19d0a3d5ad50688d14aa6e957af082dafea56b52e1bd3a6b3f1406
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
DISK_MIN_MB=${DISK_MIN_MB:-1431}
PULL_MIN_MB=${PULL_MIN_MB:-2385}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
SOURCE_REPO=${SOURCE_REPO:-$REPO}

die() { echo "p4.sh: $*" >&2; exit 2; }

free_kib() { docker exec "$DISK_CONTAINER" df -k / | awk 'NR==2 {print $4}'; }

disk() {
  docker exec "$DISK_CONTAINER" df -h / | tail -n 1
  if [ "$(free_kib)" -lt $((DISK_MIN_MB * 1024)) ]; then
    echo "BLOCKED: less than $DISK_MIN_MB MiB free on the Docker disk; the emulator image takes 1.61 GB on disk" >&2
    exit 3
  fi
}

export_tree() {
  local sha=$1 dir=$2
  rm -rf "$dir" && mkdir -p "$dir"
  git -C "$SOURCE_REPO" archive "$sha" | tar -x -C "$dir"
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  cp "$ENV_FILE" "$dir/deploy/.env"
  git -C "$SOURCE_REPO" rev-parse "$sha" >"$dir/.SHA"
}

pg_up() {
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_PASSWORD=test -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1 && { echo "postgres up on $PG_PORT"; return 0; }
    sleep 1
  done
  die "postgres did not become ready"
}

pg_down() { docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true; }

note_emulator_pull() {
  docker image inspect "$COSMOS_IMAGE" >/dev/null 2>&1 && return 0
  if [ "$(free_kib)" -lt $((PULL_MIN_MB * 1024)) ]; then
    echo "BLOCKED: the emulator image is not here, and pulling it (1.61 GB on disk) needs $PULL_MIN_MB MiB free" >&2
    exit 3
  fi
  mkdir -p "$EVID"
  date -u +%FT%TZ >"$EVID/.emulator-pulled"
}

cosmos_up() {
  disk
  note_emulator_pull
  docker rm -fv "$COSMOS_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$COSMOS_NAME" --add-host packages.microsoft.com:127.0.0.1 \
    -e PORT="$COSMOS_PORT" -e ENABLE_EXPLORER=false -e ENABLE_TELEMETRY=false \
    -p "127.0.0.1:$COSMOS_PORT:$COSMOS_PORT" -p "127.0.0.1:$COSMOS_HEALTH_PORT:8080" "$COSMOS_IMAGE" >/dev/null
  for _ in $(seq 1 120); do
    curl -fsS "http://127.0.0.1:$COSMOS_HEALTH_PORT/ready" >/dev/null 2>&1 && { echo "emulator up on $COSMOS_PORT"; return 0; }
    sleep 2
  done
  die "the emulator was not ready after 4 minutes"
}

cosmos_down() { docker rm -fv "$COSMOS_NAME" >/dev/null 2>&1 || true; }

gates() {
  local wt=$1 out="$EVID/gates" status=0
  mkdir -p "$out"
  run() {
    local name=$1
    shift
    if (cd "$wt" && eval "$*") >"$out/$name.log" 2>&1; then
      echo "PASS $name: $(tail -n 1 "$out/$name.log")"
    else
      echo "FAIL $name (see $out/$name.log): $(tail -n 3 "$out/$name.log" | tr '\n' ' ')"
      status=1
    fi
  }
  curl -fsS "http://127.0.0.1:$COSMOS_HEALTH_PORT/ready" >/dev/null 2>&1 || die "run cosmos-up first; the gates require the Cosmos DB tests"
  run contracts-generate "(cd platform-api && uv sync --locked && uv run python -m platform_api.contracts ../contracts) && (cd agent-runtime && uv sync --locked && uv run python -m agent_runtime.contracts ../contracts)"
  git -C "$wt" status --porcelain -- contracts >"$out/contracts-porcelain.txt"
  if [ -s "$out/contracts-porcelain.txt" ]; then
    echo "FAIL contracts-porcelain: $(tr '\n' ' ' <"$out/contracts-porcelain.txt")"
    status=1
  else
    echo "PASS contracts-porcelain: git status --porcelain -- contracts is empty"
  fi
  run pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  run pa-pyright "cd platform-api && uv run pyright"
  run pa-lint-imports "cd platform-api && uv run lint-imports"
  run pa-contracts "cd platform-api && uv run pytest tests/test_contracts.py -q"
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres COSMOS_ENDPOINT=http://127.0.0.1:$COSMOS_PORT COSMOS_REQUIRED=1 uv run pytest -q -rs -p no:cacheprovider"
  /usr/bin/grep -h "Cosmos DB tests:" "$out/pa-pytest.log" || true
  run checks-lint "cd platform-api && uv run ruff check ../scripts/checks/p4_lanes.py ../scripts/p95.py && uv run ruff format --check ../scripts/checks/p4_lanes.py ../scripts/p95.py"
  return "$status"
}

ports_of() {
  local first=$1
  echo "$first $((first + 1)) $((first + 2))"
}

lane_first() {
  local offset
  case "$1" in
    4) offset=0 ;; 5) offset=1 ;; 6) offset=2 ;; 8) offset=3 ;; 9) offset=4 ;; 10) offset=5 ;; 11) offset=6 ;; 12) offset=7 ;;
    *) die "lane $1 has no own stack" ;;
  esac
  echo $((LANE_PORTS + offset * LANE_STEP))
}

check_ports() {
  local blocks=() names=() n i j a b wa wb
  blocks+=("$PORTS:$STACK_WIDTH") names+=("PORTS (head)")
  blocks+=("$TRUNK_PORTS:$STACK_WIDTH") names+=("TRUNK_PORTS (trunk)")
  for n in 4 5 6 8 9 10 11 12; do
    blocks+=("$(lane_first "$n"):$STACK_WIDTH") names+=("lane $n (LANE_PORTS)")
  done
  blocks+=("$PG_PORT:1" "$COSMOS_PORT:1" "$COSMOS_HEALTH_PORT:1") names+=("PG_PORT" "COSMOS_PORT" "COSMOS_HEALTH_PORT")
  for i in "${!blocks[@]}"; do
    a=${blocks[$i]%%:*} wa=${blocks[$i]##*:}
    [ "$a" -ge 1024 ] && [ $((a + wa - 1)) -le 65535 ] || die "${names[$i]} uses ports $a to $((a + wa - 1)), outside 1024 to 65535"
    for j in "${!blocks[@]}"; do
      [ "$j" -gt "$i" ] || continue
      b=${blocks[$j]%%:*} wb=${blocks[$j]##*:}
      if [ "$a" -lt $((b + wb)) ] && [ "$b" -lt $((a + wa)) ]; then
        die "${names[$i]} (from $a) and ${names[$j]} (from $b) share host ports"
      fi
    done
  done
}

mock_overlay() {
  local overlay="$EVID/overlays/mock-images.yaml"
  mkdir -p "$EVID/overlays"
  cat >"$overlay" <<'YAML'
services:
  mock-github:
    image: wab/mock-github:${WAB_IMAGE_TAG:-dev}
  mock-model:
    image: wab/mock-model:${WAB_IMAGE_TAG:-dev}
YAML
  echo "$overlay"
}

compose_cmd() {
  local src=$1 project=$2
  shift 2
  echo "docker compose -p $project --env-file $ENV_FILE -f $src/deploy/compose.yaml -f $src/deploy/compose.e2e.yaml -f $(mock_overlay) $*"
}

stack_env() {
  local portal=$1 api=$2 n8n=$3
  echo "WAB_IMAGE_TAG=${STACK_TAG:-$TAG} PORTAL_HOST_PORT=$portal PLATFORM_API_HOST_PORT=$api N8N_HOST_PORT=$n8n"
}

build() {
  local src=$1 project=$2 log status=0
  disk
  mkdir -p "$EVID/stacks"
  log="$EVID/stacks/$project-build-$(cut -c1-7 "$src/.SHA").log"
  WAB_IMAGE_TAG="${STACK_TAG:-$TAG}" $(compose_cmd "$src" "$project" ${OVERLAYS:-}) build >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$log" >&2
    return "$status"
  fi
  echo "built $project at $(cut -c1-7 "$src/.SHA") as tag ${STACK_TAG:-$TAG}"
}

up() {
  local src=$1 project=$2 portal=$3 api=$4 n8n=$5 log status=0
  shift 5
  if [ "${NO_BUILD:-0}" != 1 ]; then
    build "$src" "$project"
    [ "${PRUNE:-0}" = 1 ] && docker builder prune -af >/dev/null
  fi
  disk
  note_emulator_pull
  mkdir -p "$EVID/stacks"
  log="$EVID/stacks/$project-up-$(cut -c1-7 "$src/.SHA").log"
  env $(stack_env "$portal" "$api" "$n8n") "$@" \
    $(compose_cmd "$src" "$project" ${OVERLAYS:-}) up --no-build --wait --wait-timeout 420 >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

down() {
  local src=$1 project=$2
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG="${STACK_TAG:-$TAG}" $(compose_cmd "$src" "$project" ${OVERLAYS:-}) --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  WAB_IMAGE_TAG="${STACK_TAG:-$TAG}" $(compose_cmd "$src" "$project" ${OVERLAYS:-}) --profile e2e down -v --remove-orphans
}

lanes_py() { python3 -I "$HERE/p4_lanes.py" "$@"; }

lane1() {
  local trunk_src=$1 head_src=$2 tapi hapi
  read -r _ tapi _ <<<"$(ports_of "$TRUNK_PORTS")"
  read -r _ hapi _ <<<"$(ports_of "$PORTS")"
  STACK_TAG=$TRUNK_TAG up "$trunk_src" "$PREFIX-trunk" $(ports_of "$TRUNK_PORTS")
  curl -fsS "http://localhost:$hapi/healthz" >/dev/null || up "$head_src" "$PREFIX" $(ports_of "$PORTS")
  lanes_py lane1 "http://localhost:$tapi" "$EVID/lane-1" "http://localhost:$hapi"
}

head_run() {
  python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["head"]["run_id"])' "$EVID/lane-1/p4-stream-trunk-head.json"
}

lane() {
  local n=$1 api head_src
  read -r _ api _ <<<"$(ports_of "$PORTS")"
  head_src=${HEAD_SRC:-$EVID/head}
  case "$n" in
    2 | 3) P4_COMPOSE="$(compose_cmd "$head_src" "$PREFIX" ${OVERLAYS:-})" lanes_py "lane$n" "http://localhost:$api" "$EVID/lane-$n" "$(head_run)" ;;
    7) P4_COMPOSE="$(compose_cmd "$head_src" "$PREFIX" ${OVERLAYS:-})" lanes_py lane7 "http://localhost:$api" "$EVID/lane-7" ;;
    *) die "lane $n runs on its own stack: p4.sh lane$n <head-src>" ;;
  esac
}

own_stack_lane() {
  local n=$1 src=$2 project="$PREFIX-l$1" portal api n8n status=0
  shift 2
  read -r portal api n8n <<<"$(ports_of "$(lane_first "$n")")"
  NO_BUILD=1 up "$src" "$project" "$portal" "$api" "$n8n" ${STACK_ENV:+"$STACK_ENV"} || { down "$src" "$project" >/dev/null 2>&1 || true; return 1; }
  env $(stack_env "$portal" "$api" "$n8n") ${STACK_ENV:+"$STACK_ENV"} \
    P4_COMPOSE="$(compose_cmd "$src" "$project" ${OVERLAYS:-})" \
    python3 -I "$HERE/p4_lanes.py" "lane$n" "http://localhost:$api" "$EVID/lane-$n" "$@" || status=$?
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

signing_key() {
  local key
  key=$(sed -n 's/^CALLBACK_SIGNING_KEY=//p' "$ENV_FILE")
  [ -n "$key" ] || die "no CALLBACK_SIGNING_KEY in $ENV_FILE"
  echo "$key"
}

lane4() { own_stack_lane 4 "$1"; }

lane5() {
  local key
  key=$(signing_key)
  own_stack_lane 5 "$1" "$key" "${LANE5_EVENTS:-4000}"
}

lane6() { own_stack_lane 6 "$1"; }

lane8() {
  local src=$1 overlay="$EVID/overlays/faketime.yaml"
  mkdir -p "$EVID/overlays"
  docker build --quiet --tag "wab/platform-api:$TAG-faketime" - >/dev/null <<DOCKERFILE
FROM wab/platform-api:$TAG
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libfaketime \\
    && rm -rf /var/lib/apt/lists/* \\
    && ln -s /usr/lib/*/faketime/libfaketimeMT.so.1 /usr/local/lib/libfaketime.so.1 \\
    && echo +0 > /tmp/faketime && chmod 666 /tmp/faketime
USER app
DOCKERFILE
  cat >"$overlay" <<YAML
services:
  platform-api:
    image: wab/platform-api:$TAG-faketime
    environment:
      LD_PRELOAD: /usr/local/lib/libfaketime.so.1
      FAKETIME_TIMESTAMP_FILE: /tmp/faketime
      FAKETIME_NO_CACHE: "1"
      DONT_FAKE_MONOTONIC: "1"
YAML
  OVERLAYS="${OVERLAYS:-} -f $overlay" own_stack_lane 8 "$src"
}

lane9() {
  local src=$1 overlay="$EVID/overlays/two-api.yaml" second key
  second=$(($(lane_first 9) + 3))
  key=$(signing_key)
  mkdir -p "$EVID/overlays"
  cat >"$overlay" <<YAML
services:
  platform-api-2:
    extends:
      file: $src/deploy/compose.yaml
      service: platform-api
    ports: !override
      - "$second:8000"
YAML
  OVERLAYS="${OVERLAYS:-} -f $overlay" own_stack_lane 9 "$src" "http://localhost:$second" "$key"
}

lane10() {
  STACK_ENV=ACTIVITY_READER=postgres own_stack_lane 10 "$1" "$EVID/lane-1/p4-stream-trunk-head.json"
}

lane11() {
  local key
  key=$(signing_key)
  own_stack_lane 11 "$1" "$key" "${LANE11_EVENTS:-4000}"
}

lane12() { own_stack_lane 12 "$1"; }

perf() {
  local trunk_src=$1 head_src=$2 rounds=${3:-3} out="$EVID/perf" status=0 i side src project tag
  mkdir -p "$out"
  for i in $(seq 1 "$rounds"); do
    for side in trunk head; do
      src=$head_src project=$PREFIX tag=$TAG
      [ "$side" = trunk ] && src=$trunk_src project=$PREFIX-trunk tag=$TRUNK_TAG
      WAB_IMAGE_TAG=$tag $(compose_cmd "$src" "$project") exec -T platform-api \
        python - --stream http://localhost:8000 /tmp/p95-stream.json --count 200 <"$REPO/scripts/p95.py" \
        | tail -n 1 >"$out/$side-$i.json" || status=1
      cat "$out/$side-$i.json"
    done
  done
  perf_table "$out"
  return "$status"
}

perf_table() {
  python3 -I - "$1" <<'PYEOF'
import json, statistics, sys
from pathlib import Path
out = Path(sys.argv[1])
medians = {}
for side in ("trunk", "head"):
    values = [json.loads(f.read_text())["p95_ms"] for f in sorted(out.glob(f"{side}-*.json"))]
    medians[side] = statistics.median(values) if values else None
    print(f"{side:5} stream p95 per round: {values} ms; median {medians[side]} ms")
trunk, head = medians["trunk"], medians["head"]
if trunk is None or head is None:
    print("missing data"); sys.exit(1)
limit = min(1000.0, trunk + 500)
verdict = "PASS" if head < 1000 and head <= trunk + 500 else "FAIL"
line = f"head median {head:.1f} ms vs trunk median {trunk:.1f} ms, limit {limit:.1f} ms -> {verdict}"
(out / "p95-table.txt").write_text(line + "\n")
print(line)
sys.exit(0 if verdict == "PASS" else 1)
PYEOF
}

projects() {
  local n
  echo "$PREFIX" "$PREFIX-trunk"
  for n in 4 5 6 8 9 10 11 12; do echo "$PREFIX-l$n"; done
}

cleanup() {
  local image project id
  for image in $(docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E "^wab/[a-z-]+:($TAG|$TRUNK_TAG)(-faketime)?$"); do
    docker rmi "$image" >/dev/null || true
  done
  for project in $(projects); do
    # -a: compose builds one image name for platform-api and bootstrap, so one copy has no tag.
    for id in $(docker images -aq --filter "label=com.docker.compose.project=$project" | sort -u); do
      docker rmi "$id" >/dev/null 2>&1 || true
    done
  done
  if [ -f "$EVID/.emulator-pulled" ]; then
    if [ -n "$(docker ps -aq --filter "ancestor=$COSMOS_IMAGE")" ]; then
      echo "kept the emulator image: a container still uses it"
    else
      docker rmi "$COSMOS_IMAGE" >/dev/null 2>&1 || true
      rm -f "$EVID/.emulator-pulled"
      echo "removed the emulator image this script pulled"
    fi
  else
    echo "kept the emulator image: this script did not pull it"
  fi
  docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E ":($TAG|$TRUNK_TAG)(-faketime)?$" || echo "no $TAG images left"
}

command=${1:-}
[ -n "$command" ] || die "usage: p4.sh <disk|export|pg-up|pg-down|cosmos-up|cosmos-down|gates|build|up|down|lane1|lane|lane4|lane5|lane6|lane8|lane9|lane10|lane11|lane12|perf|perf-table|cleanup> ..."
shift
check_ports
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  cosmos-up) cosmos_up ;;
  cosmos-down) cosmos_down ;;
  perf-table) perf_table "$@" ;;
  gates | build | up | down | lane1 | lane | lane4 | lane5 | lane6 | lane8 | lane9 | lane10 | lane11 | lane12 | perf | cleanup) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
