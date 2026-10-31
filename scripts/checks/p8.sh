#!/usr/bin/env bash
# Checker probes for P8 of the rebuild plan (pause, resume, delete with Undo, and drafts for
# workflows). Rerun any step on its own.
#
# usage: scripts/checks/p8.sh <command> [arguments]
#
#   disk                                  free space on the Docker disk; fails under 1.5 GB
#   export <sha> <dir>                    git archive of one commit into <dir>, with the throwaway env file as deploy/.env
#   pg-up | pg-down                       the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   gates <worktree>                      platform-api's CI gates, both contract generators, and the Portal typecheck
#   up <src> <project> <tag> <portal> <api> <n8n>    one dev stack (compose.yaml + compose.e2e.yaml) from an exported tree
#   down <src> <project>                  logs, then down -v
#   e2e <src> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   lane <name> <api-port> [arguments]    one lane of p8_lanes.py against http://localhost:<api-port>, saved under $EVID/<name>
#   lane1 <trunk-api-port> <head-api-port>  lane 1 against a trunk stack and a head stack that are both up
#   lane3 <head-src> [portal api n8n]     lane 3 on its own stack (project p8-build-l3, default ports 43080 43000 43678)
#   dast <src> <project> <tag>            lane 10: scripts/dast.sh in an exported tree; writes $EVID/lane-10/p8-zap.txt
#   perf <trunk-api-port> <head-api-port> [rounds]  seeds 50 workflows on each, then scripts/p95.py interleaved
#   perf-table <dir>                      the p95 medians and the rule: head at most trunk plus 20 ms
#   cleanup                               removes the images this checker's projects and tags left
#
# Lanes on the shared head stack: p8.sh lane lane2 44000, then lane4, lane5, lane6, lane7, lane8, lane9.
#
# Environment:
#   EVID            evidence folder (default /tmp/swarm-p8)
#   ENV_FILE        compose env file (default $EVID/env/.env; copy deploy/make-env.sh next to it and run it)
#   PG_PORT         host port of the test PostgreSQL (default 55438)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p8}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PG_PORT=${PG_PORT:-55438}
PG_NAME=p8-build-pg
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)

die() { echo "p8.sh: $*" >&2; exit 2; }

disk() {
  local avail
  docker exec "$DISK_CONTAINER" df -h / | tail -n 1
  avail=$(docker exec "$DISK_CONTAINER" df -k / | awk 'NR==2 {print $4}')
  if [ "$avail" -lt $((1536 * 1024)) ]; then
    echo "BLOCKED: less than 1.5 GB free on the Docker disk" >&2
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
  docker run -d --name "$PG_NAME" -e POSTGRES_PASSWORD=test -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1 && { echo "postgres up on $PG_PORT"; return 0; }
    sleep 1
  done
  die "postgres did not become ready"
}

pg_down() { docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true; }

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
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q -rs"
  run checks-lint "cd platform-api && uv run ruff check ../scripts/checks/p8_lanes.py && uv run ruff format --check ../scripts/checks/p8_lanes.py"
  run portal-typecheck "cd portal && npm ci --no-audit --no-fund && npm run typecheck"
  return "$status"
}

stack_env() {
  local tag=$1 portal=$2 api=$3 n8n=$4
  echo "WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal PLATFORM_API_HOST_PORT=$api N8N_HOST_PORT=$n8n"
}

compose() {
  local src=$1 project=$2
  shift 2
  docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" "$@"
}

up() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 log
  disk
  mkdir -p "$EVID/stacks"
  log="$EVID/stacks/$project-up-$(cut -c1-7 "$src/.SHA").log"
  local status=0
  env $(stack_env "$tag" "$portal" "$api" "$n8n") \
    docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" \
    up --build --wait --wait-timeout 300 >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

down() {
  local src=$1 project=$2
  mkdir -p "$EVID/stacks"
  compose "$src" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$src" "$project" --profile e2e down -v --remove-orphans
}

e2e() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 out="$EVID/e2e"
  disk
  mkdir -p "$out"
  local status=0
  (cd "$src" && env E2E_SUITES=api E2E_PROJECT="$project" $(stack_env "$tag" "$portal" "$api" "$n8n") scripts/e2e.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/e2e/out/." "$out/" 2>/dev/null || true
  tail -n 4 "$out/run.log"
  return "$status"
}

lanes_py() { python3 -I "$HERE/p8_lanes.py" "$@"; }

lane() {
  local name=$1 port=$2
  shift 2
  lanes_py "$name" "http://localhost:$port" "$EVID/${name/lane/lane-}" "$@"
}

lane1() {
  local trunk=$1 head=$2
  lanes_py lane1 "http://localhost:$trunk" "$EVID/lane-1" "http://localhost:$head"
}

lane3() {
  local src=$1 portal=${2:-43080} api=${3:-43000} n8n=${4:-43678} project=p8-build-l3 key status=0
  key=$(sed -n 's/^STEP_KEY=//p' "$ENV_FILE")
  [ -n "$key" ] || die "no STEP_KEY in $ENV_FILE"
  up "$src" "$project" p8build "$portal" "$api" "$n8n"
  lanes_py lane3 "http://localhost:$api" "$EVID/lane-3" "$key" || status=$?
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

dast() {
  local src=$1 project=$2 tag=$3 out="$EVID/lane-10" status=0
  disk
  mkdir -p "$out"
  (cd "$src" && env E2E_PROJECT="$project" WAB_IMAGE_TAG="$tag" scripts/dast.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/dast/out/." "$out/" 2>/dev/null || true
  python3 -I - "$out" <<'PYEOF' | tee "$out/p8-zap.txt"
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
names = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}
total = {name: 0 for name in names.values()}
for label in ("api", "api-via-portal", "portal"):
    report = out / f"{label}.json"
    if not report.exists():
        print(f"{label}: no report"); continue
    counts = {name: 0 for name in names.values()}
    for site in json.loads(report.read_text()).get("site", []):
        for alert in site.get("alerts", []):
            risk = names.get(str(alert.get("riskcode")), "Informational")
            counts[risk] += 1
            if risk in ("High", "Medium"):
                print(f"  {label}: {risk} {alert.get('alert')} ({alert.get('pluginid')})")
    for name, n in counts.items():
        total[name] += n
    print(f"{label}: " + ", ".join(f"{n} {name}" for name, n in counts.items()))
print(f"total: {total['High']} High, {total['Medium']} Medium, {total['Low']} Low")
print("PASS" if total["High"] + total["Medium"] == 0 else "FAIL")
PYEOF
  tail -n 6 "$out/run.log" | tee -a "$out/p8-zap.txt"
  return "$status"
}

perf() {
  local trunk=$1 head=$2 rounds=${3:-3} out="$EVID/perf" status=0 port side
  mkdir -p "$out"
  for side in trunk head; do
    port=$trunk && [ "$side" = head ] && port=$head
    if [ "$(curl -sS -H 'X-Dev-User: alice' "http://localhost:$port/api/v1/use-cases" | python3 -I -c 'import json,sys; print(len(json.load(sys.stdin)["use_cases"]))')" -lt 50 ]; then
      lanes_py seed "http://localhost:$port" "$out/seed-$side" 50 >/dev/null
    fi
  done
  for i in $(seq 1 "$rounds"); do
    python3 -I "$REPO/scripts/p95.py" "http://localhost:$trunk" GET /api/v1/use-cases "$out/trunk-$i.json" --count 500 --warm-up 20 || status=1
    python3 -I "$REPO/scripts/p95.py" "http://localhost:$head" GET /api/v1/use-cases "$out/head-$i.json" --count 500 --warm-up 20 || status=1
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
    print(f"{side:5} GET /api/v1/use-cases p95 per round: {values} ms; median {medians[side]} ms")
trunk, head = medians["trunk"], medians["head"]
if trunk is None or head is None:
    print("missing data"); sys.exit(1)
limit = trunk + 20
verdict = "PASS" if head <= limit else "FAIL"
line = f"head median {head:.1f} ms vs trunk median {trunk:.1f} ms, limit {limit:.1f} ms -> {verdict}"
(out / "p95-table.txt").write_text(line + "\n")
print(line)
PYEOF
}

cleanup() {
  local image
  for image in $(docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E '^(wab/[a-z-]+:p8build(-base)?|p8-build[a-z0-9-]*:)'); do
    docker rmi "$image" >/dev/null || true
  done
  docker images --format '{{.Repository}}:{{.Tag}}' | /usr/bin/grep -E 'p8build|p8-build' || echo "no p8 images left"
}

command=${1:-}
[ -n "$command" ] || die "usage: p8.sh <disk|export|pg-up|pg-down|gates|up|down|e2e|lane|lane1|lane3|dast|perf|perf-table|cleanup> ..."
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  perf-table) perf_table "$@" ;;
  gates | up | down | e2e | lane | lane1 | lane3 | dast | perf | cleanup) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
