#!/usr/bin/env bash
# Checker probes for P4 of the rebuild plan (the activity log's copy in Cosmos DB). Rerun any step
# on its own. The lanes themselves are in p4_lanes.py, standard library only.
#
# usage: scripts/checks/p4.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under $DISK_MIN_MB
#   export <sha> <dir>                     git archive of one commit into <dir>, with $ENV_FILE as deploy/.env
#   pg-up | pg-down                        the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   cosmos-up | cosmos-down                an emulator for the platform-api tests (host port $COSMOS_PORT)
#   gates <worktree>                       platform-api's CI gates with the Cosmos DB tests required
#   up <src> <project> <portal> <api> <n8n>    one dev stack; builds the images unless NO_BUILD=1
#   down <src> <project>                   logs, then down -v
#   lane1 <trunk-src> <head-src>           trunk and head stacks ($PREFIX-trunk, $PREFIX), lane 1
#   lane <2|3|7>                           a lane on the shared head stack $PREFIX, from $HEAD_SRC
#   lane4 | lane5 | lane6 | lane8 | lane9 | lane10 <head-src>   a lane on its own stack $PREFIX-l<n>
#   perf <trunk-src> <head-src> [rounds]   p95.py --stream in both shared stacks, interleaved
#   perf-table <dir>                       the medians and the rule: head under 1 s and at most trunk + 500 ms
#   cleanup                                removes the images this checker's tag left
#
# Order:
#   p4.sh export <trunk-sha> $EVID/trunk && p4.sh export <head-sha> $EVID/head
#   p4.sh pg-up && p4.sh cosmos-up && p4.sh gates <head-worktree>
#   p4.sh up $EVID/head p4-check 44080 44000 44678     (builds the head images)
#   p4.sh lane1 $EVID/trunk $EVID/head                  (builds trunk's images, starts $PREFIX-trunk)
#   p4.sh lane 2; p4.sh lane 3; p4.sh lane 7
#   p4.sh lane4 $EVID/head ... p4.sh lane10 $EVID/head  (own stacks, NO_BUILD=1, each downed after)
#   p4.sh perf $EVID/trunk $EVID/head
#   p4.sh down $EVID/head p4-check; STACK_TAG=p4check-trunk p4.sh down $EVID/trunk p4-check-trunk
# Lane 8 builds a small libfaketime layer on the head image, which needs apt's network.
#
# Environment (defaults in brackets):
#   EVID [/tmp/swarm-p4]      evidence folder
#   ENV_FILE [$EVID/env/.env] compose env file; copy deploy/make-env.sh next to it and run it
#   PREFIX [p4-check]         compose project prefix
#   TAG [p4check]             image tag of the head build; TRUNK_TAG [p4check-trunk]
#   PORTS [44]                first two digits of the head stack's ports: 44080 44000 44678;
#                             trunk uses 45, own stacks 46 to 51 (lane4 46 ... lane10 51)
#   PG_NAME [p4-check-pg]  PG_PORT [55441]
#   COSMOS_NAME [p4-check-cosmos]  COSMOS_PORT [58081]  COSMOS_HEALTH_PORT [58080]
#   DISK_CONTAINER [wab-postgres-1]   a running container on the Docker VM's disk; DISK_MIN_MB [2560]
#   HEAD_SRC [$EVID/head]     the exported head tree, for lane 2, 3 and 7
#   LANE5_EVENTS [600]        lane 5's backlog; raise it when the kill lands after the copy ends
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p4}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PREFIX=${PREFIX:-p4-check}
TAG=${TAG:-p4check}
TRUNK_TAG=${TRUNK_TAG:-p4check-trunk}
PORTS=${PORTS:-44}
PG_NAME=${PG_NAME:-p4-check-pg}
PG_PORT=${PG_PORT:-55441}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
COSMOS_NAME=${COSMOS_NAME:-p4-check-cosmos}
COSMOS_PORT=${COSMOS_PORT:-58081}
COSMOS_HEALTH_PORT=${COSMOS_HEALTH_PORT:-58080}
COSMOS_IMAGE=mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview@sha256:db53613dae19d0a3d5ad50688d14aa6e957af082dafea56b52e1bd3a6b3f1406
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
DISK_MIN_MB=${DISK_MIN_MB:-2560}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)

die() { echo "p4.sh: $*" >&2; exit 2; }

disk() {
  local avail
  docker exec "$DISK_CONTAINER" df -h / | tail -n 1
  avail=$(docker exec "$DISK_CONTAINER" df -k / | awk 'NR==2 {print $4}')
  if [ "$avail" -lt $((DISK_MIN_MB * 1024)) ]; then
    echo "BLOCKED: less than $DISK_MIN_MB MB free on the Docker disk; the emulator image is 603 MB compressed" >&2
    exit 3
  fi
}

export_tree() {
  local sha=$1 dir=$2
  rm -rf "$dir" && mkdir -p "$dir"
  git -C "$REPO" archive "$sha" | tar -x -C "$dir"
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  cp "$ENV_FILE" "$dir/deploy/.env"
  git -C "$REPO" rev-parse "$sha" >"$dir/.SHA"
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

cosmos_up() {
  docker rm -fv "$COSMOS_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$COSMOS_NAME" -e PORT="$COSMOS_PORT" -e ENABLE_EXPLORER=false -e ENABLE_TELEMETRY=false \
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
  echo "${first}080 ${first}000 ${first}678"
}

compose_cmd() {
  local src=$1 project=$2
  shift 2
  echo "docker compose -p $project --env-file $ENV_FILE -f $src/deploy/compose.yaml -f $src/deploy/compose.e2e.yaml $*"
}

up() {
  local src=$1 project=$2 portal=$3 api=$4 n8n=$5 tag=${STACK_TAG:-$TAG} log build=--build
  shift 5
  disk
  [ "${NO_BUILD:-0}" = 1 ] && build=--no-build
  mkdir -p "$EVID/stacks"
  log="$EVID/stacks/$project-up-$(cut -c1-7 "$src/.SHA").log"
  local status=0
  env WAB_IMAGE_TAG="$tag" PORTAL_HOST_PORT="$portal" PLATFORM_API_HOST_PORT="$api" N8N_HOST_PORT="$n8n" "$@" \
    $(compose_cmd "$src" "$project" ${OVERLAYS:-}) up $build --wait --wait-timeout 420 >"$log" 2>&1 || status=$?
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
  read -r _ tapi _ <<<"$(ports_of 45)"
  read -r _ hapi _ <<<"$(ports_of "$PORTS")"
  STACK_TAG=$TRUNK_TAG up "$trunk_src" "$PREFIX-trunk" $(ports_of 45)
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
    2 | 3) P4_COMPOSE="$(compose_cmd "$head_src" "$PREFIX")" lanes_py "lane$n" "http://localhost:$api" "$EVID/lane-$n" "$(head_run)" ;;
    7) P4_COMPOSE="$(compose_cmd "$head_src" "$PREFIX")" lanes_py lane7 "http://localhost:$api" "$EVID/lane-7" ;;
    *) die "lane $n runs on its own stack: p4.sh lane$n <head-src>" ;;
  esac
}

own_stack_lane() {
  local n=$1 src=$2 first=$3 project="$PREFIX-l$1" portal api n8n status=0
  shift 3
  read -r portal api n8n <<<"$(ports_of "$first")"
  # shellcheck disable=SC2086
  NO_BUILD=1 up "$src" "$project" "$portal" "$api" "$n8n" ${STACK_ENV:-} || { down "$src" "$project" >/dev/null 2>&1 || true; return 1; }
  P4_COMPOSE="$(compose_cmd "$src" "$project" ${OVERLAYS:-})" lanes_py "lane$n" "http://localhost:$api" "$EVID/lane-$n" "$@" || status=$?
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

lane4() { own_stack_lane 4 "$1" 46; }

lane5() {
  local key
  key=$(sed -n 's/^CALLBACK_SIGNING_KEY=//p' "$ENV_FILE")
  [ -n "$key" ] || die "no CALLBACK_SIGNING_KEY in $ENV_FILE"
  own_stack_lane 5 "$1" 47 "$key" "${LANE5_EVENTS:-600}"
}

lane6() { own_stack_lane 6 "$1" 48; }

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
  OVERLAYS="-f $overlay" own_stack_lane 8 "$src" 49
}

lane9() {
  local src=$1 overlay="$EVID/overlays/two-api.yaml" second=50001
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
  OVERLAYS="-f $overlay" own_stack_lane 9 "$src" 50 "http://localhost:$second"
}

lane10() {
  STACK_ENV=ACTIVITY_READER=postgres own_stack_lane 10 "$1" 51 "$EVID/lane-1/p4-stream-trunk-head.json"
}

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

cleanup() {
  local image
  for image in $(docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E "^wab/[a-z-]+:($TAG|$TRUNK_TAG)(-faketime)?$"); do
    docker rmi "$image" >/dev/null || true
  done
  docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E "$TAG" || echo "no $TAG images left"
}

command=${1:-}
[ -n "$command" ] || die "usage: p4.sh <disk|export|pg-up|pg-down|cosmos-up|cosmos-down|gates|up|down|lane1|lane|lane4|lane5|lane6|lane8|lane9|lane10|perf|perf-table|cleanup> ..."
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  cosmos-up) cosmos_up ;;
  cosmos-down) cosmos_down ;;
  perf-table) perf_table "$@" ;;
  gates | up | down | lane1 | lane | lane4 | lane5 | lane6 | lane8 | lane9 | lane10 | perf | cleanup) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
