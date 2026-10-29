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
#   oidc-up <src> <project> <tag> [override.yaml]    one OIDC stack (adds compose.oidc.yaml; no host ports)
#   down <src> <project> [oidc]           logs, then down -v
#   e2e <src> <project> <tag> <portal> <api> <n8n>   scripts/e2e.sh with E2E_SUITES=api in an exported tree
#   spec06 <src> <project>                the 06 OIDC spec against a running OIDC stack, in $E2E_RUNNER_IMAGE as it is
#   api <api-port> <user> <method> <path> [json-body]  one call with X-Dev-User; prints the body and the status
#   lane1 <trunk-src> <head-src>          trunk then head dev stacks: alice runs, bob approves; at head bob's
#                                         roles follow the People list (p3-approve-trunk-head.json)
#   dev-lanes <src>                       lanes 4 and 5 on one fresh dev stack, lanes 6, 7, 8 and 9 each on
#                                         its own, then the asker and roleless lanes together on one more
#   dev-lane <src> <name> <lane>...       the given p3_lanes.py lanes, in order, on one fresh dev stack
#   oidc-lanes <src>                      spec 06, lane 2 and the tenant lane on one fresh OIDC stack, then
#                                         lane 3 and the readd lane on another
#   oidc-lane <src> <name> <lane>...      the given lanes, in order, on one fresh OIDC stack (spec06 is a lane here)
#   lane10 <src>                          its own OIDC stack: restart platform-api with other FIRST_* values and
#                                         the People list stays; a fresh volume with those values seeds them
#   perf <trunk-src> <head-src> [rounds]  p95 of GET /api/v1/me, 500 requests, interleaved; both dev stacks must be up
#   perf-table <dir>                      the p95 medians and the pass/fail against trunk + 20 ms
#   people <src> <project> [oidc]         the People table as the owner sees it (psql inside the stack)
#
# Environment:
#   EVID            evidence folder (default /tmp/swarm-p3)
#   ENV_FILE        compose env file (default $EVID/env/.env, made by deploy/make-env.sh copied next to it)
#   PREFIX          compose project prefix for the stacks the lane commands start (default p3)
#   TAG             image tag of the head stacks (default p3build)
#   TRUNK_TAG       image tag of the trunk stack (default p3base)
#   PORTS           host ports "portal api n8n" of head dev stacks (default "48080 48000 45678")
#   TRUNK_PORTS     host ports of the trunk dev stack (default "58080 58000 55678")
#   PG_PORT         host port of the test PostgreSQL (default 55433)
#   PG_NAME         container name of the test PostgreSQL (default p3-check-pg)
#   DISK_CONTAINER  a running container on the Docker VM's disk (default wab-postgres-1)
#   E2E_RUNNER_IMAGE  browser runner image for spec06, used as it is and never built (default portal-e2e-runner:p1shell)
set -euo pipefail

EVID=${EVID:-/tmp/swarm-p3}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
PREFIX=${PREFIX:-p3}
TAG=${TAG:-p3build}
TRUNK_TAG=${TRUNK_TAG:-p3base}
read -r -a HEAD_PORTS <<<"${PORTS:-48080 48000 45678}"
read -r -a BASE_PORTS <<<"${TRUNK_PORTS:-58080 58000 55678}"
PG_PORT=${PG_PORT:-55433}
PG_NAME=${PG_NAME:-p3-check-pg}
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
  local status=0 log
  log="$EVID/stacks/$project-up-$(cut -c1-7 <"$src/.SHA").log"
  env $(stack_env "$tag" "$portal" "$api" "$n8n") \
    docker compose -p "$project" --env-file "$ENV_FILE" -f "$src/deploy/compose.yaml" -f "$src/deploy/compose.e2e.yaml" \
    up --build --wait --wait-timeout 300 >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    tail -n 20 "$log" >&2
    return "$status"
  fi
  curl -sS -w "\nGET /healthz/ready %{http_code}\n" "http://localhost:$api/healthz/ready"
}

oidc_up() {
  local src=$1 project=$2 tag=$3 override=${4:-}
  local extra=()
  [ -n "$override" ] && extra=(-f "$override")
  disk
  mkdir -p "$EVID/stacks"
  if ! WAB_IMAGE_TAG=$tag compose "$src" "$project" oidc ${extra[@]+"${extra[@]}"} up --build --wait --wait-timeout 300 >"$EVID/stacks/$project-up.log" 2>&1; then
    tail -n 30 "$EVID/stacks/$project-up.log" >&2
    echo "p3.sh: $project did not become healthy" >&2
    return 1
  fi
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
  local src=$1 project=$2 portal status=0 out="$EVID/spec06" live="$src/portal/e2e/out/live"
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  docker image inspect "$RUNNER" >/dev/null 2>&1 || die "no runner image $RUNNER; build it once with portal/e2e/runner-image.sh"
  rm -rf "$out" "$live" && mkdir -p "$out" "$live"
  docker run --rm --network "container:$portal" --ipc=host \
    -e CI=1 -e BASE_URL=http://localhost:8080 -e E2E_AUTH=oidc \
    -e MOCK_OIDC_URL="$ISSUER" -e MOCK_GITHUB_URL=http://mock-github:8200 -e PLAIN_HTTP_URL=http://portal:8080 \
    -v "$src/portal/e2e:/work/e2e:ro" -v "$live:/work/e2e/out/live" \
    -w /work "$RUNNER" \
    npx playwright test -c e2e/live/playwright.config.ts >"$out/run.log" 2>&1 || status=$?
  cp -R "$live/." "$out/" 2>/dev/null || true
  grep -E "passed|failed|skipped" "$out/run.log" || tail -n 5 "$out/run.log"
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
  local api_container status=0
  api_container=$(compose "$src" "$project" oidc ps -q platform-api)
  [ -n "$api_container" ] || die "no running platform-api in project $project"
  docker exec -i "$api_container" python - "$@" <"$(here_dir)/p3_lanes.py" || status=$?
  mkdir -p "$EVID/$out_name"
  docker cp "$api_container:/tmp/p3-out/." "$EVID/$out_name/" >/dev/null 2>&1 || true
  return "$status"
}

lane1() {
  local trunk=$1 head=$2 out="$EVID/lane-1" status=0
  mkdir -p "$out"
  up "$trunk" "$PREFIX-l1-trunk" "$TRUNK_TAG" "${BASE_PORTS[@]}"
  lanes_py lane1 "http://localhost:${BASE_PORTS[1]}" "$out" trunk || status=1
  down "$trunk" "$PREFIX-l1-trunk"
  up "$head" "$PREFIX-l1-head" "$TAG" "${HEAD_PORTS[@]}"
  lanes_py lane1 "http://localhost:${HEAD_PORTS[1]}" "$out" head || status=1
  down "$head" "$PREFIX-l1-head"
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

dev_lane() {
  local src=$1 name=$2 status=0
  shift 2
  local project="$PREFIX-$name"
  if ! up "$src" "$project" "$TAG" "${HEAD_PORTS[@]}"; then
    down "$src" "$project" >/dev/null 2>&1 || true
    return 1
  fi
  for lane in "$@"; do
    echo "== $lane"
    lanes_py "$lane" "http://localhost:${HEAD_PORTS[1]}" "$EVID/lane-$name" || status=1
  done
  down "$src" "$project"
  return "$status"
}

dev_lanes() {
  local src=$1 status=0
  dev_lane "$src" l45 lane4 lane5 || status=1
  dev_lane "$src" l6 lane6 || status=1
  dev_lane "$src" l7 lane7 || status=1
  dev_lane "$src" l8 lane8 || status=1
  dev_lane "$src" l9 lane9 || status=1
  dev_lane "$src" lx asker roleless || status=1
  return "$status"
}

oidc_lane() {
  local src=$1 name=$2 status=0
  shift 2
  local project="$PREFIX-$name"
  if ! oidc_up "$src" "$project" "$TAG"; then
    down "$src" "$project" oidc >/dev/null 2>&1 || true
    return 1
  fi
  for lane in "$@"; do
    echo "== $lane"
    if [ "$lane" = spec06 ]; then
      spec06 "$src" "$project" || status=1
    else
      in_stack "$src" "$project" "lane-$name" "$lane" http://localhost:8000 /tmp/p3-out "$ISSUER" || status=1
    fi
  done
  down "$src" "$project" oidc
  return "$status"
}

oidc_lanes() {
  local src=$1 status=0
  oidc_lane "$src" oidc-a spec06 lane2 tenant || status=1
  oidc_lane "$src" oidc-b lane3 readd || status=1
  return "$status"
}

# The People table, read by the owner role inside the stack.
people() {
  local src=$1 project=$2 oidc=${3:-dev}
  compose "$src" "$project" "$oidc" exec -T postgres psql -U postgres -d platform -At -F ' ' -c \
    "SELECT id, email, display, is_operator, is_approver, entra_oid IS NOT NULL AS bound, removed_at IS NOT NULL AS removed FROM orchestration.people ORDER BY email;"
}

deploy_lines() {
  local src=$1 project=$2
  compose "$src" "$project" oidc exec -T postgres psql -U postgres -d platform -At -c \
    "SELECT summary FROM orchestration.settings_changes WHERE changed_by = 'deploy' ORDER BY id;"
}

lane10() {
  local src=$1 out="$EVID/lane-10" project="$PREFIX-l10"
  rm -rf "$out" && mkdir -p "$out"
  # compose.oidc.yaml names alice and bob literally, so other values need an override file.
  cat >"$out/other-first-people.yaml" <<'YAML'
services:
  platform-api:
    environment:
      FIRST_OPERATOR: carol@example.test
      FIRST_APPROVERS: carol@example.test,dave@example.test
YAML
  oidc_up "$src" "$project" "$TAG" || { down "$src" "$project" oidc >/dev/null 2>&1; return 1; }
  people "$src" "$project" oidc >"$out/people-before.txt"
  deploy_lines "$src" "$project" >"$out/deploy-before.txt"
  compose "$src" "$project" oidc -f "$out/other-first-people.yaml" up -d --force-recreate --no-deps --wait platform-api >"$out/restart.log" 2>&1
  compose "$src" "$project" oidc exec -T platform-api sh -c 'echo "FIRST_OPERATOR=$FIRST_OPERATOR FIRST_APPROVERS=$FIRST_APPROVERS"' >"$out/restart-env.txt"
  people "$src" "$project" oidc >"$out/people-after.txt"
  deploy_lines "$src" "$project" >"$out/deploy-after.txt"
  down "$src" "$project" oidc >/dev/null
  oidc_up "$src" "$project" "$TAG" "$out/other-first-people.yaml" >/dev/null ||
    { down "$src" "$project" oidc >/dev/null 2>&1; return 1; }
  people "$src" "$project" oidc >"$out/control-people.txt"
  deploy_lines "$src" "$project" >"$out/control-deploy.txt"
  down "$src" "$project" oidc >/dev/null
  python3 -I - "$out" <<'PYEOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
read = lambda name: (out / name).read_text().strip().splitlines()
emails = lambda rows: sorted(r.split(" ")[1] for r in rows)
before, after, control = read("people-before.txt"), read("people-after.txt"), read("control-people.txt")
env = (out / "restart-env.txt").read_text().strip()
result = {
    "before": before,
    "after": after,
    "restart_env": env,
    "deploy_lines_before": read("deploy-before.txt"),
    "deploy_lines_after": read("deploy-after.txt"),
    "control_people": control,
    "control_deploy_lines": read("control-deploy.txt"),
}
checks = [
    ("carol@example.test" in env, f"platform-api restarted with other values: {env}"),
    (emails(before) == ["alice@example.test", "bob@example.test"], f"the first seed named alice and bob: {emails(before)}"),
    (before == after, "the People list is unchanged after the restart"),
    (len(result["deploy_lines_after"]) == 1, f"the deploy seeded once: {result['deploy_lines_after']}"),
    (emails(control) == ["carol@example.test", "dave@example.test"], f"control, a fresh volume with those values seeds them: {emails(control)}"),
]
(out / "p3-seed-once.json").write_text(json.dumps(result, indent=2) + "\n")
for ok, line in checks:
    print(("ok   " if ok else "FAIL ") + line)
passed = all(ok for ok, _ in checks)
print("PASS" if passed else "FAIL")
sys.exit(0 if passed else 1)
PYEOF
}

perf() {
  local trunk=$1 head=$2 rounds=${3:-3} out="$EVID/perf" status=0
  mkdir -p "$out"
  for i in $(seq 1 "$rounds"); do
    python3 -I "$trunk/scripts/p95.py" "http://localhost:${BASE_PORTS[1]}" GET /api/v1/me "$out/trunk-$i.json" --count 500 --user alice || status=1
    python3 -I "$head/scripts/p95.py" "http://localhost:${HEAD_PORTS[1]}" GET /api/v1/me "$out/head-$i.json" --count 500 --user alice || status=1
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
[ -n "$command" ] || die "usage: p3.sh <disk|export|pg-up|pg-down|gates|up|oidc-up|down|e2e|spec06|api|lane1|dev-lanes|dev-lane|oidc-lanes|oidc-lane|lane10|perf|perf-table|people> ..."
shift
case "$command" in
  disk) disk ;;
  export) export_tree "$@" ;;
  pg-up) pg_up ;;
  pg-down) pg_down ;;
  oidc-up) oidc_up "$@" ;;
  perf-table) perf_table "$@" ;;
  dev-lanes) dev_lanes "$@" ;;
  dev-lane) dev_lane "$@" ;;
  oidc-lanes) oidc_lanes "$@" ;;
  oidc-lane) oidc_lane "$@" ;;
  gates | up | down | e2e | spec06 | api | lane1 | lane10 | perf | people) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
