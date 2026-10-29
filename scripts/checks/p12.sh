#!/usr/bin/env bash
# Checker probes for P12 of the rebuild plan (teach the Planner to say what it understood). Rerun
# any step on its own.
#
# usage: scripts/checks/p12.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   export <sha> <dir>                     git archive of one commit into <dir>, with the env file as deploy/.env
#   pg-up | pg-down                        the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   gates <worktree>                       every gate for agent-runtime, platform-api, e2e and the Portal typecheck
#   e2e <src> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   up <src> <project> <tag> <portal> <api> <n8n>    one dev stack (compose.yaml + compose.e2e.yaml)
#   down <src> <project>                   logs, then down -v
#   mock-mode <project> <ok|slow|broken>   switch the stack's mock model
#   shared <api>                           lanes 1, 2, 3, 4, 7, 9 and 10 on a shared head stack
#   trunk <api>                            lane 1's trunk half: trunk has no understand route
#   own <src> <project> <tag> <portal> <api> <n8n>   lanes 6, 8 and 5 on a stack of their own, then down
#   perf <api> trunk                       p95 of 50 suggest requests, the baseline
#   perf <api> head [mock|haiku]           p95 of 50 understand requests and the share from the model;
#                                          mock connects the mock model and also times suggest,
#                                          haiku uses Claude Haiku 5.5 once it is connected in Settings
#   perf-table                             the plan's perf rule over $EVID/perf
#   evals <src>                            the bake-off against the mock model, through the gateway provider
#   evals-gateway <src>                    the bake-off against the AI Singapore gateway; needs the key in the shell
#
# Environment:
#   EVID            evidence folder (default /tmp/swarm-p12)
#   ENV_FILE        compose env file (default $EVID/env/.env, made by deploy/make-env.sh copied next to it)
#   PG_PORT         host port of the test PostgreSQL (default 55439); PG_NAME its container (p12-check-pg)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
#   E2E_RUNNER_IMAGE  passed through to scripts/e2e.sh
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p12}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PG_PORT=${PG_PORT:-55439}
PG_NAME=${PG_NAME:-p12-check-pg}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
FOLLOW_UP="Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them"

die() { echo "p12.sh: $*" >&2; exit 2; }
lanes() { python3 -I "$HERE/p12_lanes.py" "$@"; }

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
  git -C "$ROOT" archive "$sha" | tar -x -C "$dir"
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  cp "$ENV_FILE" "$dir/deploy/.env"
  git -C "$ROOT" rev-parse "$sha" >"$dir/.SHA"
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
  run ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  run ar-pyright "cd agent-runtime && uv run pyright"
  run ar-understand "cd agent-runtime && uv run pytest tests/test_understand.py -q"
  run ar-pytest "cd agent-runtime && uv run pytest -q"
  run pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  run pa-pyright "cd platform-api && uv run pyright"
  run pa-lint-imports "cd platform-api && uv run lint-imports"
  run pa-contracts "cd platform-api && uv run pytest tests/test_contracts.py -q"
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q -rs"
  run e2e-static "cd e2e && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright"
  run mock-model-image "docker build -q --target test --tag p12check-mock-model:test e2e/mock_model && docker run --rm p12check-mock-model:test"
  docker rmi p12check-mock-model:test >/dev/null 2>&1 || true
  run portal-typecheck "cd portal && npm run typecheck"
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

e2e() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 out="$EVID/lane-1/e2e-$2" status=0
  disk
  mkdir -p "$out"
  (cd "$src" && env E2E_SUITES=api E2E_PROJECT="$project" $(stack_env "$tag" "$portal" "$api" "$n8n") scripts/e2e.sh) >"$out/run.log" 2>&1 || status=$?
  cp -R "$src/e2e/out/." "$out/" 2>/dev/null || true
  tail -n 4 "$out/run.log"
  return "$status"
}

up() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 status=0 log
  disk
  mkdir -p "$EVID/stacks"
  log="$EVID/stacks/$project-up.log"
  (export $(stack_env "$tag" "$portal" "$api" "$n8n") && compose "$src" "$project" up --build --wait --wait-timeout 300) >"$log" 2>&1 || status=$?
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

mock_mode() {
  local project=$1 mode=$2 mock
  mock=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=mock-model)
  [ -n "$mock" ] || die "no mock-model container in project $project"
  docker exec "$mock" python -c "import json,sys,urllib.request as u; r=u.Request('http://127.0.0.1:8300/_admin/mode', data=json.dumps({'mode': sys.argv[1]}).encode(), method='POST', headers={'Content-Type':'application/json'}); print(u.urlopen(r).read().decode())" "$mode"
}

shared() {
  local api=$1 status=0 lane
  lanes connect "http://localhost:$api" "$EVID/setup" || return 1
  for lane in 1 2 3 4 7 9 10; do
    echo "== lane $lane"
    lanes "lane$lane" "http://localhost:$api" "$EVID/lane-$lane" || status=1
  done
  return "$status"
}

trunk() { lanes trunk "http://localhost:$1" "$EVID/lane-1"; }

own() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 status=0
  up "$src" "$project" "$tag" "$portal" "$api" "$n8n" || return 1
  lanes connect "http://localhost:$api" "$EVID/lane-6" || status=1
  echo "== lane 6"
  mock_mode "$project" slow
  lanes starters "http://localhost:$api" "$EVID/lane-6" p12-slow-model.json 11 || status=1
  mock_mode "$project" ok
  echo "== lane 8"
  mock_mode "$project" broken
  lanes starters "http://localhost:$api" "$EVID/lane-8" p12-broken.json 11 || status=1
  mock_mode "$project" ok
  compose "$src" "$project" logs --no-color platform-api agent-runtime 2>&1 \
    | /usr/bin/grep -E "did not parse|fell back to the starter" >"$EVID/lane-8/p12-broken-logs.txt" || true
  if /usr/bin/grep -q "did not parse" "$EVID/lane-8/p12-broken-logs.txt" \
    && /usr/bin/grep -q "unusable_answer" "$EVID/lane-8/p12-broken-logs.txt"; then
    echo "ok   the runtime logged the parse failure and the platform logged the fallback"
  else
    echo "FAIL the parse failure is not in the logs (see $EVID/lane-8/p12-broken-logs.txt)"
    status=1
  fi
  cat "$EVID/lane-8/p12-broken-logs.txt"
  echo "== lane 5"
  lanes model-off "http://localhost:$api" "$EVID/lane-5" || status=1
  lanes starters "http://localhost:$api" "$EVID/lane-5" p12-no-model.json 11 || status=1
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

perf() {
  local api=$1 side=$2 model=${3:-mock} out="$EVID/perf"
  mkdir -p "$out"
  if [ "$side" = head ]; then
    [ "$model" = haiku ] || lanes connect "http://localhost:$api" "$out/setup-$side" >/dev/null
    python3 -I "$ROOT/scripts/p95.py" "http://localhost:$api" POST /api/v1/builder/understand \
      "$out/head-understand-$model.json" --count 50 --warm-up 3 --body "{\"text\": \"$FOLLOW_UP. Ref {marker}.\"}"
    lanes share "http://localhost:$api" "$out" "head-share-$model.json" 50 || true
    [ "$model" = mock ] || return 0
  fi
  python3 -I "$ROOT/scripts/p95.py" "http://localhost:$api" POST /api/v1/use-cases/suggest \
    "$out/$side-suggest.json" --count 50 --warm-up 3 --body '{"text": "Check LangGraph for new releases {marker}"}'
}

perf_table() {
  python3 -I - "$EVID/perf" <<'PYEOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
def p95(name):
    f = out / name
    return json.loads(f.read_text())["p95_ms"] if f.exists() else None
rows = []
understand, trunk, head = p95("head-understand-mock.json"), p95("trunk-suggest.json"), p95("head-suggest.json")
rows.append(f"POST /api/v1/builder/understand with the mock model: p95 {understand} ms, limit 300 ms -> {'PASS' if understand is not None and understand < 300 else 'FAIL'}")
if trunk is None or head is None:
    rows.append("POST /api/v1/use-cases/suggest: missing data")
else:
    rows.append(f"POST /api/v1/use-cases/suggest: head p95 {head} ms vs trunk p95 {trunk} ms, limit {trunk * 1.2:.1f} ms -> {'PASS' if head <= trunk * 1.2 else 'FAIL'}")
share = out / "head-share-mock.json"
if share.exists():
    s = json.loads(share.read_text())["result"]
    rows.append(f"answers from the mock model: {s['from_model']} of {s['count']}")
haiku = out / "head-share-haiku.json"
rows.append(
    f"answers from Claude Haiku 5.5: {json.loads(haiku.read_text())['result']['from_model']} of 50"
    if haiku.exists()
    else "answers from Claude Haiku 5.5: not run, waiting for the gateway key"
)
text = "\n".join(rows)
(out / "p95-table.txt").write_text(text + "\n")
print(text)
PYEOF
}

evals() {
  local src=$1 net=p12-evals mock=p12-evals-mock out="$EVID/evals"
  disk
  mkdir -p "$out" && chmod a+rwx "$out"
  docker network create "$net" >/dev/null 2>&1 || true
  docker build -q --target runtime --tag p12build-evals-mock:local "$src/e2e/mock_model" >/dev/null
  docker build -q --target evals --tag p12build-evals:local "$src/agent-runtime" >/dev/null
  docker run -d --rm --name "$mock" --network "$net" p12build-evals-mock:local >/dev/null
  local status=0
  docker run --rm --network "$net" --volume "$out:/app/evals/out:rw" \
    --env AGENT_MODEL_BASE_URL=http://$mock:8300 --env AGENT_MODEL_API_KEY=mock-key-not-real \
    --env GATEWAY_MODELS=mock-model --env OLLAMA_BASE_URL= \
    p12build-evals:local --out /app/evals/out/results-mock.json | tee "$out/table-mock.txt" || status=$?
  docker rm -f "$mock" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  docker rmi p12build-evals:local p12build-evals-mock:local >/dev/null 2>&1 || true
  return "$status"
}

evals_gateway() {
  local src=$1 out="$EVID/evals"
  [ -n "${AGENT_MODEL_API_KEY:-}" ] && [ -n "${AGENT_MODEL_BASE_URL:-}" ] || die "first run: read -s AGENT_MODEL_API_KEY && export AGENT_MODEL_API_KEY; export AGENT_MODEL_BASE_URL=https://llm-gateway.aisg.sg"
  disk
  mkdir -p "$out" && chmod a+rwx "$out"
  docker build -q --target evals --tag p12build-evals:local "$src/agent-runtime" >/dev/null
  local status=0
  docker run --rm --volume "$out:/app/evals/out:rw" --env AGENT_MODEL_BASE_URL --env AGENT_MODEL_API_KEY \
    --env GATEWAY_MODELS="${GATEWAY_MODELS:-azure_ai/claude-haiku-5-5}" --env OLLAMA_BASE_URL= \
    p12build-evals:local --out /app/evals/out/results-haiku.json | tee "$out/table-haiku.txt" || status=$?
  docker rmi p12build-evals:local >/dev/null 2>&1 || true
  return "$status"
}

command=${1:-}
[ -n "$command" ] || die "usage: p12.sh <command> ...; see the top of this file"
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  mock-mode) mock_mode "$@" ;;
  perf-table) perf_table ;;
  evals-gateway) evals_gateway "$@" ;;
  gates | e2e | up | down | shared | trunk | own | perf | evals) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
