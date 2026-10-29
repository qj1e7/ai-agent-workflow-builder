#!/usr/bin/env bash
# Checker probes for P3 of the rebuild plan (people and their roles in the platform). Rerun any
# step on its own. The trees come from git archive, so the scripts under test write deploy/.env
# there and never in a worktree.
#
# usage: scripts/checks/p3.sh <command> [arguments]
#
#   disk                                  free space on the Docker disk; fails under 1.5 GB
#   export <sha> <dir>                    git archive of one commit into <dir>, with the throwaway env file as deploy/.env
#   pg-up | pg-down                       the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   gates <worktree>                      every CI gate for platform-api, agent-runtime, e2e and portal
#   up <src> <project> <tag> <portal> <api> <n8n>    one dev stack (compose.yaml + compose.e2e.yaml) from an exported tree
#   oidc-up <src> <project> <tag>         one OIDC stack (adds compose.oidc.yaml; no host ports)
#   down <src> <project> [oidc]           logs, then down -v
#   e2e <src> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   spec06 <src> <project>                the builder's 06 OIDC spec against a running OIDC stack
#   api <api-port> <user> <method> <path> [json-body]  one call with X-Dev-User; prints the body and the status
#   lane1 <trunk-src> <head-src>          trunk then head dev stacks: alice runs, bob approves (p3-approve-trunk-head.json)
#   lane2 <src> <project>                 on a running OIDC stack: mallory is not on the list
#   lane3 <src> <project>                 on a running OIDC stack: alice adds erin, erin's first sign-in binds
#   lanes4to9 <api-port>                  lanes 4 to 9 on one fresh dev stack, in the order 4, 7, 6, 5, 8, 9: lane 7
#                                         needs alice and bob as the only Approvers, so it runs before bob confirms dave
#   lane10 <src> <project>                restart platform-api of a running OIDC stack with other FIRST_* values
#   perf <trunk-src> <head-src> [rounds]  p95 of GET /api/v1/me, 500 requests, interleaved; both dev stacks must be up
#   perf-table <dir>                      the p95 medians and the pass/fail against trunk + 20 ms
#   people <src> <project> [oidc]         the People table as the owner sees it (psql inside the stack)
#
# Environment:
#   EVID            evidence folder (default /tmp/swarm-p3)
#   ENV_FILE        compose env file (default $EVID/env/.env, made by deploy/make-env.sh copied next to it)
#   PG_PORT         host port of the test PostgreSQL (default 55433)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
#   E2E_RUNNER_IMAGE  browser runner image for spec06 (default portal-e2e-runner:p1shell)
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p3}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PG_PORT=${PG_PORT:-55433}
PG_NAME=p3-check-pg
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
ISSUER=http://mock-oidc:8080/default

die() { echo "p3.sh: $*" >&2; exit 2; }
here_dir() { cd "$(dirname "$0")" && pwd; }
lanes_py() { python3 -I "$(here_dir)/p3_lanes.py" "$@"; }

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
  local sha=$1 dir=$2 repo=${3:-$(cd "$(dirname "$0")/../.." && pwd)}
  rm -rf "$dir" && mkdir -p "$dir"
  git -C "$repo" archive "$sha" | tar -x -C "$dir"
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  cp "$ENV_FILE" "$dir/deploy/.env"
  echo "$sha" >"$dir/.SHA"
}

pg_up() {
  docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$PG_NAME" -e POSTGRES_PASSWORD=test -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1 && { echo "postgres up on $PG_PORT"; return 0; }
    sleep 1
  done
  die "postgres did not become ready"
}

pg_down() { docker rm -f "$PG_NAME" >/dev/null 2>&1 || true; }

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
  run ar-contracts "cd agent-runtime && uv run pytest tests/test_contracts.py -q"
  run pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  run pa-pyright "cd platform-api && uv run pyright"
  run pa-lint-imports "cd platform-api && uv run lint-imports"
  run pa-contracts "cd platform-api && uv run pytest tests/test_contracts.py -q"
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q -rs"
  run e2e-static "cd e2e && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright"
  run portal-typecheck "cd portal && npm run typecheck"
  run portal-lint "cd portal && npm run lint"
  run portal-test "cd portal && npm test"
  run portal-build "cd portal && npm run build"
  return "$status"
}

stack_env() {
  local tag=$1 portal=$2 api=$3 n8n=$4
  echo "WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal PLATFORM_API_HOST_PORT=$api N8N_HOST_PORT=$n8n"
}

compose() {
  local src=$1 project=$2 oidc=${3:-dev}
  shift 3
  local files=(-f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml")
  [ "$oidc" = oidc ] && files+=(-f "$src/deploy/compose.oidc.yaml")
  docker compose -p "$project" --env-file "$ENV_FILE" "${files[@]}" "$@"
}

up() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6
  disk
  mkdir -p "$EVID/stacks"
  local status=0
  env $(stack_env "$tag" "$portal" "$api" "$n8n") \
    docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" \
    up --build --wait --wait-timeout 300 >"$EVID/stacks/$project-up-$(cut -c1-7 <"$src/.SHA").log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$EVID/stacks/$project-up-$(cut -c1-7 <"$src/.SHA").log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

oidc_up() {
  local src=$1 project=$2 tag=$3
  disk
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag compose "$src" "$project" oidc up --build --wait --wait-timeout 300 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  compose "$src" "$project" oidc exec -T platform-api python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz/ready').read().decode())"
}

down() {
  local src=$1 project=$2 oidc=${3:-dev}
  mkdir -p "$EVID/stacks"
  compose "$src" "$project" "$oidc" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$src" "$project" "$oidc" --profile e2e down -v --remove-orphans
}

e2e() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 out
  out="$EVID/e2e/$project"
  disk
  mkdir -p "$out"
  local status=0
  (cd "$src" && env E2E_SUITES=api E2E_PROJECT="$project" $(stack_env "$tag" "$portal" "$api" "$n8n") scripts/e2e.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/e2e/out/." "$out/" 2>/dev/null || true
  tail -n 4 "$out/run.log"
  return "$status"
}

portal_of() {
  docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=portal" | head -n 1
}

spec06() {
  local src=$1 project=$2 portal status=0
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  mkdir -p "$EVID/spec06"
  E2E_AUTH=oidc E2E_RUNNER_IMAGE=$RUNNER "$src/portal/e2e/live/run.sh" "$portal" >"$EVID/spec06/run.log" 2>&1 || status=$?
  rm -rf "$EVID/spec06/shots" && cp -R "$src/portal/e2e/out/live/shots" "$EVID/spec06/shots" 2>/dev/null || true
  grep -E "passed|failed|skipped" "$EVID/spec06/run.log" || tail -n 5 "$EVID/spec06/run.log"
  return "$status"
}

api() {
  local port=$1 user=$2 method=$3 path=$4 body=${5:-}
  local args=(-sS -X "$method" -H "X-Dev-User: $user" -H "Accept: application/json" -w "\nHTTP %{http_code}\n")
  if [ -n "$body" ]; then args+=(-H "Content-Type: application/json" --data "$body"); fi
  if [ "$method" = POST ] && [[ "$path" == */runs ]]; then args+=(-H "Idempotency-Key: p3check-$(date +%s%N)"); fi
  curl "${args[@]}" "http://localhost:$port$path"
}

# Runs one p3_lanes.py command inside the platform-api container of an OIDC stack (no host ports)
# and copies its output folder out.
in_stack() {
  local src=$1 project=$2 out_name=$3
  shift 3
  local api_container
  api_container=$(compose "$src" "$project" oidc ps -q platform-api)
  [ -n "$api_container" ] || die "no running platform-api in project $project"
  docker exec -i "$api_container" python - "$@" <"$(here_dir)/p3_lanes.py"
  local status=$?
  mkdir -p "$EVID/$out_name"
  docker cp "$api_container:/tmp/p3-out/." "$EVID/$out_name/" >/dev/null 2>&1 || true
  return "$status"
}

lane1() {
  local trunk=$1 head=$2 out="$EVID/lane-1" status=0
  mkdir -p "$out"
  up "$trunk" p3-l1-trunk p3base 58080 58000 55678
  lanes_py lane1 http://localhost:58000 "$out" trunk.json || status=1
  down "$trunk" p3-l1-trunk
  up "$head" p3-l1-head p3build 48080 48000 45678
  lanes_py lane1 http://localhost:48000 "$out" head.json || status=1
  down "$head" p3-l1-head
  python3 -I - "$out" <<'PYEOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
both = {side: json.loads((out / f"{side}.json").read_text()) for side in ("trunk", "head")}
summary = {
    side: {
        "run_state": d["run"]["state"],
        "approved_by": d["decision"] and d["decision"]["decision"]["by"],
        "bob_roles": d["me"]["roles"],
        "people_status": "listed" if isinstance(d["people"], dict) and "people" in d["people"] else "absent",
    }
    for side, d in both.items()
}
(out / "p3-approve-trunk-head.json").write_text(json.dumps({"summary": summary, "trunk": both["trunk"], "head": both["head"]}, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PYEOF
  return "$status"
}

lane2() { in_stack "$1" "$2" lane-2 lane2 http://localhost:8000 /tmp/p3-out "$ISSUER"; }
lane3() { in_stack "$1" "$2" lane-3 lane3 http://localhost:8000 /tmp/p3-out "$ISSUER"; }

lanes4to9() {
  local port=$1 status=0
  for lane in lane4 lane7 lane6 lane5 lane8 lane9; do
    echo "== $lane"
    lanes_py "$lane" "http://localhost:$port" "$EVID/lanes-4-9" || status=1
  done
  return "$status"
}

# The People table, read by the owner role inside the stack.
people() {
  local src=$1 project=$2 oidc=${3:-dev}
  compose "$src" "$project" "$oidc" exec -T postgres psql -U postgres -d platform -At -F ' ' -c \
    "SELECT id, email, display, is_operator, is_approver, entra_oid IS NOT NULL AS bound, removed_at IS NOT NULL AS removed FROM orchestration.people ORDER BY email;"
}

lane10() {
  local src=$1 project=$2 out="$EVID/lane-10"
  mkdir -p "$out"
  people "$src" "$project" oidc >"$out/people-before.txt"
  cat "$out/people-before.txt"
  # A second platform-api start with other values. The list must stay as it is.
  FIRST_OPERATOR=carol@example.test FIRST_APPROVERS=carol@example.test,dave@example.test \
    compose "$src" "$project" oidc up -d --force-recreate --no-deps --wait platform-api >"$out/restart.log" 2>&1
  compose "$src" "$project" oidc exec -T platform-api sh -c 'echo "FIRST_OPERATOR=$FIRST_OPERATOR FIRST_APPROVERS=$FIRST_APPROVERS"' | tee "$out/restart-env.txt"
  people "$src" "$project" oidc >"$out/people-after.txt"
  compose "$src" "$project" oidc logs --no-color platform-api 2>/dev/null | grep -i "seed\|People list" >"$out/seed-log.txt" || true
  python3 -I - "$out" <<'PYEOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
before = (out / "people-before.txt").read_text().strip().splitlines()
after = (out / "people-after.txt").read_text().strip().splitlines()
env = (out / "restart-env.txt").read_text().strip()
result = {"before": before, "after": after, "restart_env": env, "unchanged": before == after and len(before) >= 2}
(out / "p3-seed-once.json").write_text(json.dumps(result, indent=2) + "\n")
print("PASS people unchanged after a restart with other values" if result["unchanged"] else "FAIL people changed")
sys.exit(0 if result["unchanged"] else 1)
PYEOF
}

perf() {
  local trunk=$1 head=$2 rounds=${3:-3} out="$EVID/perf" status=0
  mkdir -p "$out"
  for i in $(seq 1 "$rounds"); do
    python3 -I "$trunk/scripts/p95.py" http://localhost:58000 GET /api/v1/me "$out/trunk-$i.json" --count 500 --user alice || status=1
    python3 -I "$head/scripts/p95.py" http://localhost:48000 GET /api/v1/me "$out/head-$i.json" --count 500 --user alice || status=1
  done
  perf_table "$out"
  return "$status"
}

perf_table() {
  python3 -I - "$1" <<'PYEOF'
import json, statistics, sys
from pathlib import Path
out = Path(sys.argv[1])
med = {}
rows = []
for side in ("trunk", "head"):
    vals = []
    for f in sorted(out.glob(f"{side}-*.json")):
        d = json.loads(f.read_text())
        vals.append(d.get("p95_ms"))
    got = [v for v in vals if v is not None]
    med[side] = statistics.median(got) if got else None
    rows.append(f"{side:5} GET /api/v1/me p95 per round: {', '.join('n/a' if v is None else f'{v:.2f}' for v in vals)} ms; median {med[side] and round(med[side], 2)} ms")
t, h = med["trunk"], med["head"]
if t is None or h is None:
    rows.append("missing data")
else:
    rows.append(f"head median {h:.2f} ms vs trunk median {t:.2f} ms, limit {t + 20:.2f} ms -> {'PASS' if h <= t + 20 else 'FAIL'}")
text = "\n".join(rows)
(out / "p95-table.txt").write_text(text + "\n")
print(text)
PYEOF
}

command=${1:-}
[ -n "$command" ] || die "usage: p3.sh <disk|export|pg-up|pg-down|gates|up|oidc-up|down|e2e|spec06|api|lane1|lane2|lane3|lanes4to9|lane10|perf|perf-table|people> ..."
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  oidc-up) oidc_up "$@" ;;
  perf-table) perf_table "$@" ;;
  gates | up | down | e2e | spec06 | api | lane1 | lane2 | lane3 | lanes4to9 | lane10 | perf | people) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
