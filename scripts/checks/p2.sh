#!/usr/bin/env bash
# Checker probes for P2 of the rebuild plan (retire the release-check template, rename the Room lead
# to the Planner). Rerun any step on its own.
#
# usage: scripts/checks/p2.sh <command> [arguments]
#
#   disk                                  free space on the Docker disk; fails under 1.5 GB
#   export <sha> <dir>                    git archive of one commit into <dir>, with the throwaway env file as deploy/.env
#   pg-up | pg-down                       the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   gates <worktree>                      every CI gate for platform-api, agent-runtime, e2e and portal
#   grep <worktree>                       the plan's retired-name grep, after npm run generate
#   e2e <src> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   up <src> <project> <tag> <portal> <api> <n8n>    one dev stack (compose.yaml + compose.e2e.yaml) from an exported tree
#   down <src> <project>                  logs, then down -v
#   api <api-port> <user> <method> <path> [json-body]  one call with X-Dev-User; prints the body and the status
#   load <src> <project> <tag> <out>      scripts/load.sh in an exported tree; copies load/out to <out>
#   dast <src> <project> <tag> <out>      scripts/dast.sh in an exported tree; copies dast/out to <out>
#   n8n <n8n-port> <out.json>             n8n's public workflow list, read with a short-lived key of the checker's own
#   counts <src> <project> | all-counts <project>   read-only row counts (and n8n's workflow table)
#   lane3a <trunk-src> <head-src>         trunk, one watchlist check, then head on the same volumes (project p2-l3)
#   lane3b <trunk-src> <head-src>         trunk, an old release-check run, then head on the same volumes (project p2-l3b)
#   lane10 <head-src>                     mock GitHub fails, retry after recovery, bob approves (project p2-l10)
#   perf <trunk-src> <head-src> [rounds]  scripts/load.sh interleaved; perf-table <dir> prints the p95 medians
#
# Lanes 2, 4, 5, 6, 7 on a shared head stack: python3 -I scripts/checks/p2_lanes.py lane2|lane5|lane6|lane4|lane7 ...
# The trees: p2.sh export <sha> /tmp/swarm-p2/src/head (and .../base), so scripts/*.sh write deploy/.env there, not here.
#
# Environment:
#   EVID          evidence folder (default /tmp/swarm-p2)
#   ENV_FILE      compose env file (default $EVID/env/.env, made by deploy/make-env.sh copied next to it)
#   PG_PORT       host port of the test PostgreSQL (default 45432)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p2}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PG_PORT=${PG_PORT:-45432}
PG_NAME=p2-check-pg
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
GREP=/usr/bin/grep

die() { echo "p2.sh: $*" >&2; exit 2; }

disk() {
  local avail
  docker exec "$DISK_CONTAINER" df -h / | tail -n 1
  avail=$(docker exec "$DISK_CONTAINER" df -k / | awk 'NR==2 {print $4}')
  if [ "$avail" -lt $((1536 * 1024)) ]; then
    echo "BLOCKED: less than 1.5 GB free on the Docker disk" >&2
    exit 3
  fi
}

# The scripts under test write deploy/.env when it is missing. An exported tree takes that write, not the worktree.
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
    echo "FAIL contracts-porcelain: $(cat "$out/contracts-porcelain.txt" | tr '\n' ' ')"
    status=1
  else
    echo "PASS contracts-porcelain: git status --porcelain -- contracts is empty"
  fi
  run ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  run ar-pyright "cd agent-runtime && uv run pyright"
  run ar-contracts "cd agent-runtime && uv run pytest tests/test_contracts.py -q"
  run ar-pytest "cd agent-runtime && uv run pytest -q"
  run pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  run pa-pyright "cd platform-api && uv run pyright"
  run pa-lint-imports "cd platform-api && uv run lint-imports"
  run pa-contracts "cd platform-api && uv run pytest tests/test_contracts.py -q"
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q -rs"
  run e2e-static "cd e2e && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright"
  run mock-github-image "docker build -q --target test --tag p2check-mock-github:test e2e/mock_github && docker run --rm p2check-mock-github:test"
  run mock-model-image "docker build -q --target test --tag p2check-mock-model:test e2e/mock_model && docker run --rm p2check-mock-model:test"
  docker rmi p2check-mock-github:test p2check-mock-model:test >/dev/null 2>&1 || true
  run portal-typecheck "cd portal && npm run typecheck"
  run portal-lint "cd portal && npm run lint"
  run portal-test "cd portal && npm test"
  run portal-build "cd portal && npm run build"
  return "$status"
}

grep_names() {
  local wt=$1 out="$EVID/gates/grep.txt"
  (cd "$wt/portal" && npm run generate) >/dev/null 2>&1
  (cd "$wt" && $GREP -rniE "room_lead|roomlead|room lead|release_check" platform-api agent-runtime contracts e2e scripts load portal/src \
    --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=out --exclude-dir=checks) >"$out" || true
  echo "hits: $(wc -l <"$out" | tr -d ' ')"
  cat "$out"
}

stack_env() {
  local tag=$1 portal=$2 api=$3 n8n=$4
  echo "WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal PLATFORM_API_HOST_PORT=$api N8N_HOST_PORT=$n8n"
}

e2e() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 out
  out="$EVID/lane-1/$project"
  disk
  mkdir -p "$out"
  local status=0
  (cd "$src" && env E2E_SUITES=api E2E_PROJECT="$project" $(stack_env "$tag" "$portal" "$api" "$n8n") scripts/e2e.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/e2e/out/." "$out/" 2>/dev/null || true
  tail -n 4 "$out/run.log"
  return "$status"
}

compose() {
  local src=$1 project=$2
  shift 2
  docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" "$@"
}

up() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6
  disk
  local status=0
  env $(stack_env "$tag" "$portal" "$api" "$n8n") \
    docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" \
    up --build --wait --wait-timeout 300 >"$EVID/stacks/$project-up-$(cat "$src/.SHA" | cut -c1-7).log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$EVID/stacks/$project-up-$(cat "$src/.SHA" | cut -c1-7).log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

down() {
  local src=$1 project=$2
  compose "$src" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$src" "$project" --profile e2e down -v --remove-orphans
}

api() {
  local port=$1 user=$2 method=$3 path=$4 body=${5:-}
  local args=(-sS -X "$method" -H "X-Dev-User: $user" -H "Accept: application/json" -w "\nHTTP %{http_code}\n")
  if [ -n "$body" ]; then args+=(-H "Content-Type: application/json" --data "$body"); fi
  if [ "$method" = POST ] && [[ "$path" == */runs ]]; then args+=(-H "Idempotency-Key: p2check-$(date +%s%N)"); fi
  curl "${args[@]}" "http://localhost:$port$path"
}

load() {
  local src=$1 project=$2 tag=$3 out=$4
  disk
  mkdir -p "$out"
  local status=0
  (cd "$src" && env E2E_PROJECT="$project" WAB_IMAGE_TAG="$tag" scripts/load.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/load/out/." "$out/" 2>/dev/null || true
  tail -n 2 "$out/run.log"
  return "$status"
}

dast() {
  local src=$1 project=$2 tag=$3 out=$4
  disk
  mkdir -p "$out"
  local status=0
  # KEEP=1 leaves the stack up after the scan, so the seeded run can be read; it is brought down here.
  (cd "$src" && env KEEP=1 E2E_PROJECT="$project" WAB_IMAGE_TAG="$tag" scripts/dast.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/dast/out/." "$out/" 2>/dev/null || true
  local scan=(docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" -f "$src/deploy/compose.scan.yaml")
  local seeded
  seeded=$(jq -r '.paths | to_entries[] | .value | to_entries[] | .value.parameters[]? | select(.name == "run_id") | .example' "$out/openapi.json" | head -n 1)
  "${scan[@]}" exec -T platform-api python -c "import json,urllib.request as u; r=u.Request('http://localhost:8000/api/v1/runs/$seeded', headers={'X-Dev-User':'alice','Accept':'application/json'}); d=json.load(u.urlopen(r)); print(json.dumps({'run_id': d['run_id'], 'state': d['state']}))" | tee "$out/seeded-run-after-scan.json"
  "${scan[@]}" logs --no-color >"$out/compose.log" 2>&1 || true
  "${scan[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  tail -n 6 "$out/run.log"
  return "$status"
}


# n8n's own public API, read with a short-lived key of the checker's own (label p2-checker), then the key is removed.
n8n_workflows() {
  local port=$1 out=$2 jar key_json key key_id
  jar=$(mktemp)
  local email pass
  email=$(sed -n 's/^N8N_OWNER_EMAIL=//p' "$ENV_FILE")
  pass=$(sed -n 's/^N8N_OWNER_PASSWORD=//p' "$ENV_FILE")
  curl -sS -c "$jar" -H 'Content-Type: application/json' \
    --data "{\"emailOrLdapLoginId\":\"$email\",\"password\":\"$pass\"}" "http://localhost:$port/rest/login" -o /dev/null -w "n8n login %{http_code}\n"
  key_json=$(curl -sS -b "$jar" -H 'Content-Type: application/json' \
    --data '{"label":"p2-checker","expiresAt":null,"scopes":["workflow:read","workflow:list"]}' "http://localhost:$port/rest/api-keys")
  key=$(echo "$key_json" | jq -r '.data.rawApiKey')
  key_id=$(echo "$key_json" | jq -r '.data.id')
  [ -n "$key" ] && [ "$key" != null ] || { echo "no api key: $key_json" >&2; rm -f "$jar"; return 1; }
  curl -sS -H "X-N8N-API-KEY: $key" "http://localhost:$port/api/v1/workflows?limit=100" >"$out"
  curl -sS -b "$jar" -X DELETE "http://localhost:$port/rest/api-keys/$key_id" -o /dev/null -w "checker key removed %{http_code}\n"
  rm -f "$jar"
  jq -r '.data[] | "\(.name) id=\(.id) active=\(.active) isArchived=\(.isArchived)"' "$out"
}

# Read-only counts of the rows a stack holds, and n8n's own workflow table.
counts() {
  local src=$1 project=$2
  compose "$src" "$project" exec -T postgres psql -U postgres -d platform -At -F ' ' -c "
    SELECT 'orchestration.runs', count(*) FROM orchestration.runs UNION ALL
    SELECT 'orchestration.proposals', count(*) FROM orchestration.proposals UNION ALL
    SELECT 'orchestration.approval_requests', count(*) FROM orchestration.approval_requests UNION ALL
    SELECT 'orchestration.outbox', count(*) FROM orchestration.outbox UNION ALL
    SELECT 'monitoring.run_events', count(*) FROM monitoring.run_events UNION ALL
    SELECT 'builder.use_cases', count(*) FROM builder.use_cases UNION ALL
    SELECT 'builder.use_case_versions', count(*) FROM builder.use_case_versions UNION ALL
    SELECT 'builder.use_case_cards', count(*) FROM builder.use_case_cards;"
  compose "$src" "$project" exec -T postgres psql -U postgres -d platform -At -F ' ' -c \
    "SELECT 'run', run_id, state, spec->>'workflow', spec->'task'->>'kind' FROM orchestration.runs ORDER BY run_id;"
  compose "$src" "$project" exec -T postgres psql -U postgres -d platform -At -F ' ' -c \
    "SELECT 'version', use_case_id, version, template FROM builder.use_case_versions ORDER BY use_case_id, version;"
  compose "$src" "$project" exec -T postgres psql -U postgres -d n8n -At -F ' ' -c \
    "SELECT 'n8n_workflow', id, name, active, \"isArchived\" FROM workflow_entity ORDER BY name;"
}


# scripts/load.sh three times at trunk and three times at head, interleaved. load.sh deletes load/out at
# its start, so each round's folder is copied out before the next round.
perf() {
  local trunk=$1 head=$2 rounds=${3:-3} out="$EVID/perf" status=0
  mkdir -p "$out"
  for i in $(seq 1 "$rounds"); do
    load "$trunk" p2-load-base p2base "$out/trunk-$i" || status=1
    load "$head" p2-load-head p2check "$out/head-$i" || status=1
  done
  perf_table "$out"
  return "$status"
}

perf_table() {
  python3 -I - "$1" <<'PYEOF'
import json, statistics, sys
from pathlib import Path
out = Path(sys.argv[1])
routes = {"list_runs": "GET /api/v1/runs", "run_events": "GET /api/v1/runs/{id}/events", "get_run": "GET /api/v1/runs/{id}"}
rows, med = [], {}
for side in ("trunk", "head"):
    for route, label in routes.items():
        vals = []
        for d in sorted(out.glob(f"{side}-*")):
            f = d / "summary.json"
            if not f.exists():
                vals.append(None); continue
            m = json.loads(f.read_text())["metrics"].get(f"http_req_duration{{path:{route}}}", {})
            vals.append(m.get("p(95)"))
        got = [v for v in vals if v is not None]
        med[(side, route)] = statistics.median(got) if got else None
        rows.append(f"{side:5} {label:32} p95 per run: {', '.join('n/a' if v is None else f'{v:.2f}' for v in vals)} ms; median {med[(side, route)] and round(med[(side, route)], 2)} ms")
rows.append("")
for route, label in routes.items():
    t, h = med[("trunk", route)], med[("head", route)]
    if t is None or h is None:
        rows.append(f"{label}: missing data"); continue
    limit = t * 1.2
    rows.append(f"{label}: head median {h:.2f} ms vs trunk median {t:.2f} ms, limit {limit:.2f} ms -> {'PASS' if h <= limit else 'FAIL'}")
text = "\n".join(rows)
(out / "p95-table.txt").write_text(text + "\n")
print(text)
PYEOF
}


here_dir() { cd "$(dirname "$0")" && pwd; }
lanes_py() { python3 -I "$(here_dir)/p2_lanes.py" "$@"; }

# Every table of the three platform schemas and n8n's workflow, execution and credential tables.
all_counts() {
  local project=$1 pg t
  pg=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=postgres)
  for t in $(docker exec "$pg" psql -U postgres -d platform -At -c "SELECT table_schema||'.'||table_name FROM information_schema.tables WHERE table_schema IN ('builder','orchestration','monitoring') AND table_type='BASE TABLE' ORDER BY 1"); do
    echo "$t $(docker exec "$pg" psql -U postgres -d platform -At -c "SELECT count(*) FROM $t")"
  done
  for t in workflow_entity execution_entity credentials_entity; do
    echo "n8n.$t $(docker exec "$pg" psql -U postgres -d n8n -At -c "SELECT count(*) FROM $t")"
  done
}

bootstrap_log() {
  local src=$1 project=$2
  compose "$src" "$project" logs --no-color bootstrap
}

# Lane 3a: trunk, one watchlist check, then head on the same project and volumes.
lane3a() {
  local trunk=$1 head=$2 project=${3:-p2-l3} out="$EVID/lane-3a" status=0
  mkdir -p "$out"
  up "$trunk" "$project" p2base 58080 58000 55678
  lanes_py check http://localhost:58000 "$out" trunk-check.json LangGraph langchain-ai/langgraph 1.2.14
  n8n_workflows 55678 "$out/n8n-workflows-trunk.json"
  counts "$trunk" "$project" >"$out/counts-trunk.txt"
  up "$head" "$project" p2check 58080 58000 55678 >"$out/switch-to-head.txt" 2>&1 || status=$?
  echo "head up exit=$status"
  bootstrap_log "$head" "$project" >"$out/bootstrap-after-switch.log"
  tail -n 2 "$out/bootstrap-after-switch.log"
  n8n_workflows 55678 "$out/p2-n8n-workflows.json"
  local run_id
  run_id=$(jq -r .run.run_id "$out/trunk-check.json")
  curl -sS -m 5 -H "X-Dev-User: alice" -o "$out/old-run.json" -w "GET /api/v1/runs/$run_id %{http_code}\n" "http://localhost:58000/api/v1/runs/$run_id" || echo "GET /api/v1/runs/$run_id: no answer"
}

# Lane 3b: trunk, an old release-check use case and run, then head on the same project and volumes.
lane3b() {
  local trunk=$1 head=$2 project=${3:-p2-l3b} out="$EVID/lane-3b" status=0
  mkdir -p "$out"
  up "$trunk" "$project" p2base 18180 18100 15679
  lanes_py release-check http://localhost:18100 "$out"
  all_counts "$project" >"$out/all-counts-before.txt"
  up "$head" "$project" p2check 18180 18100 15679 >"$out/switch-to-head.txt" 2>&1 || status=$?
  echo "head up exit=$status (1 expected)"
  bootstrap_log "$head" "$project" | tee "$out/bootstrap.log"
  all_counts "$project" >"$out/all-counts-after.txt"
  diff "$out/all-counts-before.txt" "$out/all-counts-after.txt" && echo "row counts identical"
  docker inspect -f 'platform-api {{.State.Status}} started={{.State.StartedAt}}' "$project-platform-api-1"
}

# Lane 10: the mock GitHub answers 503, a check fails, the mock recovers, alice retries, bob approves.
lane10() {
  local head=$1 project=${2:-p2-l10} out="$EVID/lane-10" gh run_id
  mkdir -p "$out"
  up "$head" "$project" p2check 58080 58000 55678
  gh=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=mock-github)
  mock_mode() { docker exec "$gh" python -c "import json,sys,urllib.request as u; r=u.Request('http://127.0.0.1:8200/_admin/mode', data=json.dumps({'mode': sys.argv[1]}).encode(), method='POST', headers={'Content-Type':'application/json'}); print(u.urlopen(r).read().decode())" "$1"; }
  mock_mode unavailable
  lanes_py check http://localhost:58000 "$out" first-run.json LangGraph langchain-ai/langgraph 1.2.14
  run_id=$(jq -r .run.run_id "$out/first-run.json")
  mock_mode ok
  lanes_py retry http://localhost:58000 "$out" "$run_id" retry-call.json
  lanes_py wait http://localhost:58000 "$out" "$run_id" awaiting_approval,failed,succeeded after-retry.json
  lanes_py lane4 http://localhost:58000 "$out/approve-after-retry" "$run_id"
}

command=${1:-}
[ -n "$command" ] || die "usage: p2.sh <disk|export|pg-up|pg-down|gates|grep|e2e|up|down|api|load|dast> ..."
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  grep) grep_names "$@" ;;
  n8n) n8n_workflows "$@" ;;
  perf-table) perf_table "$@" ;;
  all-counts) all_counts "$@" ;;
  lane3a | lane3b | lane10) "$command" "$@" ;;
  gates | e2e | up | down | api | load | dast | counts | perf) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
