#!/usr/bin/env bash
# Checker probes for P12 of the rebuild plan (teach the Planner to say what it understood). Rerun
# any step on its own. <export> is a tree the export command made.
#
# usage: scripts/checks/p12.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   export <sha> <dir>                     git archive of one commit into <dir>, with the env file as deploy/.env;
#                                          run it from a git checkout of the repository, not from an export
#   pg-up | pg-down                        the PostgreSQL 17 the platform-api tests use (host port $PG_PORT)
#   gates <worktree>                       every gate for agent-runtime, platform-api, e2e and the Portal typecheck
#   build <export> <tag> [project]         build every image of a stack once, the mock images named by <tag> too;
#                                          the compose project is p12-build-<tag> unless named
#   rmi <tag>                              remove the images build made
#   e2e <export> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   up <export> <project> <tag> <portal> <api> <n8n>  one dev stack (compose.yaml + compose.e2e.yaml), not rebuilt
#   down <export> <project> [oidc]         logs, then down -v
#   mock-mode <project> <ok|slow|broken>   switch the stack's mock model
#   snapshot <project> <file>              every table of the platform database: rows, and writes so far; and
#                                          how many runs n8n's database holds
#   shared <project> <api>                 lanes 1, 2, 3, 4, 7, 9 and 10 and the no-tool lane on a shared
#                                          head stack; lanes 7, 9 and no-tool must leave every table as it was
#   no-tool <project> <api>                both P12 checks' 52 live tasks: the fooled mock names an ability for
#                                          each, the runtime holds each write to the tools and keeps each search
#   trunk <api>                            lane 1's trunk half: trunk has no understand route
#   own <export> <prefix> <tag> <portal> <api> <n8n>  lanes 6, 8 and 5, each on a stack of its own, then down
#   trouble <export> <project> <tag> <portal> <api> <n8n>   its own stack: the runtime hangs (the platform's
#                                          10 s limit), the runtime is down, the model settings cannot be
#                                          read and PostgreSQL is down (a database error is a 500)
#   oidc <export> <project> <tag>          its own OIDC stack (no host ports): everyone signs in once, then the
#                                          route's sign-in for each kind of person, and it writes nothing. Pulls
#                                          ghcr.io/navikt/mock-oauth2-server:6.0.4 when it is not on the disk
#   perf <api> trunk                       p95 of 50 suggest requests, the baseline
#   perf <api> head [mock|haiku]           p95 of 50 understand requests and the share from the model;
#                                          mock connects the mock model and also times suggest,
#                                          haiku uses Claude Haiku 5.5 once it is connected in Settings
#   perf-table                             the plan's perf rule over $EVID/perf
#   evals <export>                         the bake-off on the host against the mock model, then the check
#                                          that the fooled mock fails every write case of the no-tool lane
#   evals-gateway <export>                 the bake-off on the host against the AI Singapore gateway; needs
#                                          the key in the shell
#
# The usual order: export, build, then shared on one head stack (up first), own, trouble, oidc,
# perf and evals, and rmi at the end.
#
# Environment:
#   EVID            evidence folder (default /tmp/swarm-p12)
#   ENV_FILE        compose env file (default $EVID/env/.env, made by deploy/make-env.sh copied next to it)
#   PG_PORT         host port of the test PostgreSQL (default 55439); PG_NAME its container (p12-check-pg)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
#   STATS_SECONDS   how long to wait for PostgreSQL to count writes before a snapshot (default 11)
#   MOCK_PORT       host port of the mock model for the evals (default 18300)
#   E2E_RUNNER_IMAGE  passed through to scripts/e2e.sh
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p12}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PG_PORT=${PG_PORT:-55439}
PG_NAME=${PG_NAME:-p12-check-pg}
PG_IMAGE=postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}
STATS_SECONDS=${STATS_SECONDS:-11}
MOCK_PORT=${MOCK_PORT:-18300}
ISSUER=http://mock-oidc:8080/default
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CASES="$ROOT/e2e/mock_model/no_tool_cases.json"
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
  docker rm -fv "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_PASSWORD=test -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null
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
  run ar-ruff "cd agent-runtime && uv run ruff check . && uv run ruff format --check ."
  run ar-pyright "cd agent-runtime && uv run pyright"
  run ar-understand "cd agent-runtime && uv run pytest tests/test_understand.py tests/test_abilities.py -q"
  run ar-pytest "cd agent-runtime && uv run pytest -q"
  run pa-ruff "cd platform-api && uv run ruff check . && uv run ruff format --check ."
  run pa-pyright "cd platform-api && uv run pyright"
  run pa-lint-imports "cd platform-api && uv run lint-imports"
  run pa-contracts "cd platform-api && uv run pytest tests/test_contracts.py -q"
  run pa-pytest "cd platform-api && PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:$PG_PORT/postgres uv run pytest -q -rs"
  run e2e-static "cd e2e && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright"
  run mock-model "cd e2e/mock_model && ../.venv/bin/python -m unittest test_model_server"
  run checks-static "cd e2e && uv run ruff check ../scripts/checks/p12_lanes.py && uv run ruff format --check ../scripts/checks/p12_lanes.py && uv run pyright ../scripts/checks/p12_lanes.py && bash -n ../scripts/checks/p12.sh"
  run portal-typecheck "cd portal && npm run typecheck"
  return "$status"
}

mock_image_names() {
  mkdir -p "$EVID/stacks"
  cat >"$EVID/stacks/p12-images.yaml" <<'YAML'
services:
  mock-github:
    image: wab/mock-github:${WAB_IMAGE_TAG:-dev}
  mock-model:
    image: wab/mock-model:${WAB_IMAGE_TAG:-dev}
YAML
  echo "$EVID/stacks/p12-images.yaml"
}

compose() {
  local src=$1 project=$2 mode=$3
  shift 3
  local files=(-f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml")
  [ "$mode" = oidc ] && files+=(-f "$src/deploy/compose.oidc.yaml")
  files+=(-f "$(mock_image_names)")
  docker compose -p "$project" --env-file "$ENV_FILE" "${files[@]}" "$@"
}

stack_env() {
  local tag=$1 portal=$2 api=$3 n8n=$4
  echo "WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal PLATFORM_API_HOST_PORT=$api N8N_HOST_PORT=$n8n"
}

container() {
  local id
  id=$(docker ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=$2" | head -n 1)
  [ -n "$id" ] || die "no running $2 in project $1"
  echo "$id"
}

healthy() {
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$1")" = healthy ] && return 0
    sleep 1
  done
  die "container $1 did not become healthy"
}

build() {
  local src=$1 tag=$2 project=${3:-p12-build-$2}
  disk
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag compose "$src" "$project" dev build >"$EVID/stacks/build-$tag.log" 2>&1 \
    || { tail -n 20 "$EVID/stacks/build-$tag.log" >&2; return 1; }
  docker image ls --filter "reference=wab/*:$tag" --format '{{.Repository}}:{{.Tag}} {{.Size}}'
}

rmi() {
  local tag=$1
  docker image rm "wab/platform-api:$tag" "wab/agent-runtime:$tag" "wab/portal:$tag" \
    "wab/mock-github:$tag" "wab/mock-model:$tag" >/dev/null 2>&1 || true
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
  (export $(stack_env "$tag" "$portal" "$api" "$n8n") && compose "$src" "$project" dev up --no-build --wait --wait-timeout 300) >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

down() {
  local src=$1 project=$2 mode=${3:-dev}
  mkdir -p "$EVID/stacks"
  compose "$src" "$project" "$mode" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$src" "$project" "$mode" --profile e2e down -v --remove-orphans
}

mock_mode() {
  local project=$1 mode=$2
  docker exec "$(container "$project" mock-model)" python -c "import json,sys,urllib.request as u; r=u.Request('http://127.0.0.1:8300/_admin/mode', data=json.dumps({'mode': sys.argv[1]}).encode(), method='POST', headers={'Content-Type':'application/json'}); print(u.urlopen(r).read().decode())" "$mode"
}

psql_in() { docker exec "$1" psql -U postgres -d "${3:-platform}" -v ON_ERROR_STOP=1 -qAtc "$2"; }

snapshot() {
  local project=$1 file=$2
  mkdir -p "$(dirname "$file")"
  psql_in "$(container "$project" postgres)" "
select 'rows', table_schema||'.'||table_name,
  (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
from information_schema.tables
where table_schema not in ('pg_catalog','information_schema') and table_type='BASE TABLE'
union all
select 'writes', schemaname||'.'||relname, (n_tup_ins + n_tup_upd + n_tup_del)::text from pg_stat_user_tables
order by 1, 2" | tr '|' ' ' >"$file"
  psql_in "$(container "$project" postgres)" "
select 'n8n executions', (xpath('/row/c/text()', query_to_xml('select count(*) as c from public.execution_entity', false, true, '')))[1]::text
where to_regclass('public.execution_entity') is not null
union all
select 'n8n executions', 'none' where to_regclass('public.execution_entity') is null" n8n | tr '|' ' ' >>"$file"
}

# PostgreSQL counts a connection's writes when it next goes idle, at most 10 s later, hence the
# wait before each snapshot.
unchanged() {
  local project=$1 out=$2 status=0
  shift 2
  sleep "$STATS_SECONDS"
  snapshot "$project" "$out/db-before.txt"
  "$@" || status=1
  sleep "$STATS_SECONDS"
  snapshot "$project" "$out/db-after.txt"
  if diff -u "$out/db-before.txt" "$out/db-after.txt" >"$out/db-diff.txt"; then
    echo "ok   every table has the same rows and no new writes ($(wc -l <"$out/db-after.txt" | tr -d ' ') lines)"
  else
    echo "FAIL a table changed (see $out/db-diff.txt):"
    cat "$out/db-diff.txt"
    status=1
  fi
  return "$status"
}

no_tool() {
  local project=$1 api=$2 out="$EVID/lane-no-tool"
  mkdir -p "$out"
  docker exec -i "$(container "$project" agent-runtime)" python - mock-raw http://mock-model:8300 - "$(cat "$CASES")" \
    <"$HERE/p12_lanes.py" >"$out/mock-raw.json"
  lanes no-tool "http://localhost:$api" "$out" "$CASES" "$out/mock-raw.json"
}

shared() {
  local project=$1 api=$2 status=0 lane url="http://localhost:$2"
  lanes connect "$url" "$EVID/setup" || return 1
  for lane in 1 2 3 4; do
    echo "== lane $lane"
    lanes "lane$lane" "$url" "$EVID/lane-$lane" || status=1
  done
  for lane in 7 9; do
    echo "== lane $lane"
    mkdir -p "$EVID/lane-$lane"
    unchanged "$project" "$EVID/lane-$lane" lanes "lane$lane" "$url" "$EVID/lane-$lane" || status=1
  done
  echo "== lane 10"
  lanes lane10 "$url" "$EVID/lane-10" || status=1
  echo "== the no-tool lane"
  mkdir -p "$EVID/lane-no-tool"
  unchanged "$project" "$EVID/lane-no-tool" no_tool "$project" "$api" || status=1
  return "$status"
}

trunk() { lanes trunk "http://localhost:$1" "$EVID/lane-1"; }

own_lane() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 lane=$7 status=0 url="http://localhost:$5"
  local out="$EVID/lane-$lane"
  echo "== lane $lane on $project"
  up "$src" "$project" "$tag" "$portal" "$api" "$n8n" || { down "$src" "$project" >/dev/null 2>&1; return 1; }
  lanes connect "$url" "$out" || status=1
  case "$lane" in
    6)
      mock_mode "$project" slow
      lanes starters "$url" "$out" p12-slow-model.json 11 || status=1
      ;;
    8)
      mock_mode "$project" broken
      lanes starters "$url" "$out" p12-broken.json 11 || status=1
      compose "$src" "$project" dev logs --no-color platform-api agent-runtime 2>&1 \
        | /usr/bin/grep -E "did not parse|fell back to the starter" >"$out/p12-broken-logs.txt" || true
      if /usr/bin/grep -q "did not parse" "$out/p12-broken-logs.txt" \
        && /usr/bin/grep -q "unusable_answer" "$out/p12-broken-logs.txt"; then
        echo "ok   the runtime logged the parse failure and the platform logged the fallback"
      else
        echo "FAIL the parse failure is not in the logs (see $out/p12-broken-logs.txt)"
        status=1
      fi
      cat "$out/p12-broken-logs.txt"
      ;;
    5)
      lanes model-off "$url" "$out" || status=1
      lanes starters "$url" "$out" p12-no-model.json 11 || status=1
      ;;
  esac
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

own() {
  local src=$1 prefix=$2 tag=$3 portal=$4 api=$5 n8n=$6 status=0 lane
  for lane in 6 8 5; do
    own_lane "$src" "$prefix-l$lane" "$tag" "$portal" "$api" "$n8n" "$lane" || status=1
  done
  return "$status"
}

trouble() {
  local src=$1 project=$2 tag=$3 portal=$4 api=$5 n8n=$6 status=0 url="http://localhost:$5"
  local out="$EVID/lane-trouble" runtime pg
  mkdir -p "$out"
  up "$src" "$project" "$tag" "$portal" "$api" "$n8n" || { down "$src" "$project" >/dev/null 2>&1; return 1; }
  step() { lanes ask "$url" "$out" "$@" || status=1; }
  back() {
    for _ in $(seq 1 20); do
      lanes ask "$url" "$out/waiting" waiting rows >/dev/null 2>&1 && return 0
      sleep 1
    done
  }
  lanes connect "$url" "$out" || status=1
  runtime=$(container "$project" agent-runtime)
  pg=$(container "$project" postgres)
  echo "== the runtime answers"
  step 0-healthy rows
  echo "== the runtime hangs: the platform's own 10 s limit answers the starters"
  docker pause "$runtime" >/dev/null
  step 1-runtime-paused starters 11 9.5
  docker unpause "$runtime" >/dev/null
  echo "== the runtime is down: the starters at once"
  docker stop "$runtime" >/dev/null
  step 2-runtime-stopped starters 3
  docker start "$runtime" >/dev/null
  healthy "$runtime"
  back
  step 3-runtime-back rows
  echo "== the model settings cannot be read: a database error is a 500, not the starters"
  psql_in "$pg" "revoke select on orchestration.model_setting from wab_orchestration"
  step 4-settings-unreadable 500
  psql_in "$pg" "grant select on orchestration.model_setting to wab_orchestration"
  step 5-settings-back rows
  echo "== PostgreSQL is down: a 500"
  docker stop "$pg" >/dev/null
  step 6-postgres-stopped 500
  docker start "$pg" >/dev/null
  healthy "$pg"
  back
  step 7-postgres-back rows
  compose "$src" "$project" dev logs --no-color platform-api 2>&1 \
    | /usr/bin/grep -E "fell back to the starter|Traceback|Error" >"$out/platform-api-log.txt" || true
  if /usr/bin/grep -q "no answer within 10 seconds" "$out/platform-api-log.txt" \
    && /usr/bin/grep -q "did not answer" "$out/platform-api-log.txt"; then
    echo "ok   the platform logged why it fell back each time"
  else
    echo "FAIL the fallbacks are not in the log (see $out/platform-api-log.txt)"
    status=1
  fi
  down "$src" "$project" >/dev/null 2>&1 || true
  return "$status"
}

in_api() {
  local project=$1 out=$2 command=$3 api status=0
  api=$(container "$project" platform-api)
  docker exec -i "$api" python - "$command" http://localhost:8000 /tmp/p12-oidc "$ISSUER" <"$HERE/p12_lanes.py" || status=1
  docker cp "$api:/tmp/p12-oidc/." "$out/" >/dev/null 2>&1 || true
  return "$status"
}

oidc() {
  local src=$1 project=$2 tag=$3 status=0 out="$EVID/lane-oidc"
  disk
  mkdir -p "$out" "$EVID/stacks"
  if ! WAB_IMAGE_TAG=$tag compose "$src" "$project" oidc up --no-build --wait --wait-timeout 300 platform-api mock-oidc \
    >"$EVID/stacks/$project-up.log" 2>&1; then
    tail -n 20 "$EVID/stacks/$project-up.log" >&2
    down "$src" "$project" oidc >/dev/null 2>&1 || true
    return 1
  fi
  in_api "$project" "$out" oidc-sign-in || status=1
  unchanged "$project" "$out" in_api "$project" "$out" oidc || status=1
  down "$src" "$project" oidc >/dev/null 2>&1 || true
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

# A venv of its own under $EVID, so a --no-dev sync never strips the tree's venv of its dev tools.
bake_off() {
  local src=$1 name=$2 out="$EVID/evals"
  mkdir -p "$out"
  (
    cd "$src/agent-runtime"
    unset ANTHROPIC_API_KEY AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT GOOGLE_API_KEY OLLAMA_MODELS EVAL_JUDGE
    export OLLAMA_BASE_URL= UV_PROJECT_ENVIRONMENT="$out/.venv"
    uv sync --locked --no-dev --group evals >"$out/sync.log" 2>&1 || { tail -n 5 "$out/sync.log" >&2; exit 1; }
    uv run --no-dev --group evals --no-sync python -m evals --out "$out/results-$name.json"
  ) | tee "$out/table-$name.txt"
}

evals() {
  local src=$1 out="$EVID/evals" status=0 mock
  mkdir -p "$out"
  rm -f "$out/results-mock.json"
  python3 -I "$src/e2e/mock_model/model_server.py" --host 127.0.0.1 --port "$MOCK_PORT" >"$out/mock-model.log" 2>&1 &
  mock=$!
  for _ in $(seq 1 50); do
    curl -fsS "http://127.0.0.1:$MOCK_PORT/healthz" >/dev/null 2>&1 && break
    sleep 0.2
  done
  (
    export AGENT_MODEL_BASE_URL="http://127.0.0.1:$MOCK_PORT" AGENT_MODEL_API_KEY=mock-key-not-real GATEWAY_MODELS=mock-model
    bake_off "$src" mock
  ) || true
  kill "$mock" 2>/dev/null || true
  wait "$mock" 2>/dev/null || true
  [ -f "$out/results-mock.json" ] || die "the bake-off wrote no results"
  echo "== the fooled mock fails every write case of the no-tool lane"
  lanes evals-check "$out/results-mock.json" "$out" "$src/e2e/mock_model/no_tool_cases.json" || status=1
  return "$status"
}

evals_gateway() {
  local src=$1
  [ -n "${AGENT_MODEL_API_KEY:-}" ] && [ -n "${AGENT_MODEL_BASE_URL:-}" ] || die "first run: read -s AGENT_MODEL_API_KEY && export AGENT_MODEL_API_KEY; export AGENT_MODEL_BASE_URL=https://llm-gateway.aisg.sg"
  (
    export GATEWAY_MODELS="${GATEWAY_MODELS:-azure_ai/claude-haiku-5-5}"
    bake_off "$src" haiku
  )
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
  no-tool) no_tool "$@" ;;
  perf-table) perf_table ;;
  evals-gateway) evals_gateway "$@" ;;
  gates | build | rmi | e2e | up | down | snapshot | shared | trunk | own | trouble | oidc | perf | evals) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
