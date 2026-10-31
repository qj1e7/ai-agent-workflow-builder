#!/usr/bin/env bash
# Checker probes for P10 of docs/design/rebuild-plan.md: Settings with the AI model and People and roles. Rerun any step on its own.
#
# usage: scripts/checks/p10.sh <command> [arguments]
#
#   disk                                   free space on the Docker disk; fails under 1.5 GB
#   gates <worktree>                       typecheck, lint, unit tests, nginx render, build
#   up [--no-build] <worktree> <project> <tag> <portal-port> <api-port> <n8n-port>
#                                          --no-build starts the images already built with that tag, the mocks included
#   down <worktree> <project>
#   check <project> [playwright arguments] run portal/e2e/checks/p10.check.ts in the runner image, in that project's Portal network
#   live <project> [playwright arguments]  run the builder's live specs (portal/e2e/live) the same way
#   lane1 <head-project> [trunk-project]   alice connects the mock model at head; trunk has no Settings tabs
#   lane <n> <project>                     lanes 7, 8, 9 and 10, one at a time on the shared stack, after lane 1; lane 10
#                                          then searches the stack's container logs and a database dump for the key
#   own [--no-build] <lanes> <worktree> <project> <tag> <portal-port> <api-port> <n8n-port>
#                                          lanes that change the People list or need a model address never confirmed:
#                                          "2,3" (in that order), "4", "5", "6" or "11", each on a fresh stack this brings up
#                                          and down. Lane 2 connects the mock model, then saves its second address
#                                          (mock-model-2 in deploy/compose.e2e.yaml), which waits. Lane 11 takes people off
#                                          the list while alice has People and roles open (D2 in the P10 recheck)
#   signin [--no-build] <worktree> <project> <tag>
#                                          the sign-in checks on a fresh stack with real sign-in (deploy/compose.oidc.yaml,
#                                          no host ports): carol is not on the list, and P1's lane 2; brings it up and down
#   size <trunk-worktree> <head-worktree>  gzip bytes of the JavaScript that dist/index.html loads
#   perf <project> [samples]               seeds 30 people once, then the largest contentful paint of People and roles
#                                          and the time until every row is drawn
#   video <project>                        the review video, as $EVID/p10-review.webm and, with ffmpeg, .mp4
#
# The shared stack runs lane1, then lanes 7, 8, 9 and 10, then perf. Lanes 7 and 9 need alice and bob as the only
# Approvers, so nothing that adds an Approver runs on that stack before them. Lanes 8 and 9 leave a request waiting to
# make Wide Pending an Approver, which no lane confirms. The video adds and confirms an Approver, so give it its own
# stack, or run it last.
#
# Environment:
#   EVID              evidence folder (default /tmp/swarm-p10)
#   ENV_FILE          compose env file with the stack's secrets (default $EVID/env/.env, made by deploy/make-env.sh)
#   DISK_CONTAINER    a running container whose disk is the Docker VM's disk (default wab-postgres-1); falls back to a throwaway alpine
#   E2E_RUNNER_IMAGE  browser runner image (default portal-e2e-runner:p1shell); never built here, so build it first with
#                     portal/e2e/runner-image.sh if it is missing
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
checker_root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p10}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
RUNNER=${E2E_RUNNER_IMAGE:-portal-e2e-runner:p1shell}
DISK_CONTAINER=${DISK_CONTAINER:-wab-postgres-1}

die() { echo "p10.sh: $*" >&2; exit 2; }

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
  (cd "$worktree/portal" && npm run typecheck && npm run lint && npm test) >"$out/typecheck-lint-test.log" 2>&1
  (cd "$worktree/portal" && npx vitest run src/screens/settings src/shell src/api) >"$out/vitest-settings-shell-api.log" 2>&1
  (cd "$worktree/portal" && sh nginx/render.test.sh) >"$out/nginx-render.log" 2>&1
  (cd "$worktree/portal" && npm run build) >"$out/build-head.log" 2>&1
  grep -E "Test Files|Tests " "$out/typecheck-lint-test.log" "$out/vitest-settings-shell-api.log"
  echo "nginx render checks ok: $(grep -c '^ok' "$out/nginx-render.log")"
  tail -n 1 "$out/nginx-render.log"
}

up() {
  local build=--build
  if [ "${1:-}" = --no-build ]; then
    build=
    shift
  fi
  local worktree=$1 project=$2 tag=$3 portal_port=$4 api_port=$5 n8n_port=$6
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  WAB_IMAGE_TAG=$tag PORTAL_HOST_PORT=$portal_port PLATFORM_API_HOST_PORT=$api_port N8N_HOST_PORT=$n8n_port \
    compose "$worktree" "$project" up ${build:+"$build"} --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  curl -sS -o "$EVID/stacks/$project-ready.json" -w "GET /healthz/ready %{http_code}\n" "http://localhost:$api_port/healthz/ready" | tee "$EVID/stacks/$project-ready.txt"
}

down() {
  local worktree=$1 project=$2
  mkdir -p "$EVID/stacks"
  compose "$worktree" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose "$worktree" "$project" --profile e2e down -v --remove-orphans
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
  # Each e2e folder is mounted on its own, so the live output can be mounted beside them. A fresh clone has no
  # portal/e2e/out, and docker can't make a mount point inside a read-only mount.
  local e2e_mounts=() folder
  for folder in checks live support; do
    e2e_mounts+=(-v "$checker_root/portal/e2e/$folder:/work/e2e/$folder:ro")
  done
  docker run --rm --network "container:$portal" --ipc=host \
    -e BASE_URL=http://localhost:8080 -e E2E_AUTH="${E2E_AUTH:-dev}" -e EVID="${RUNNER_EVID:-/evidence}" \
    -e TARGET="${TARGET:-head}" -e SAMPLE="${SAMPLE:-0}" -e MOCK_GITHUB_URL=http://mock-github:8200 \
    -e MOCK_MODEL_URL=http://mock-model:8300 -e SECOND_MODEL_URL=http://mock-model-2:8300 \
    -e MOCK_OIDC_URL=http://mock-oidc:8080/default -e PLAIN_HTTP_URL=http://portal:8080 \
    "${e2e_mounts[@]}" -v "$EVID:/evidence" -v "$EVID/.live-out:/work/e2e/out/live" \
    -w /work "$RUNNER" "$@"
}

check() {
  local project=$1
  shift
  runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p10.check.ts "$@"
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
    echo "no trunk stack given: trunk has no Settings tabs after P1, its Settings page says it is not built yet" | tee "$EVID/lane-1/p10-trunk.txt"
  fi
  TARGET=head check "$head" --grep '@lane1 ' 2>&1 | tee "$EVID/lane-1/playwright.log"
  return "${PIPESTATUS[0]}"
}

lane() {
  local n=$1 project=$2
  case "$n" in
    7 | 8 | 9 | 10) ;;
    *) die "lane $n does not run on the shared stack; see lane1 and own" ;;
  esac
  mkdir -p "$EVID/lane-$n"
  check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log"
  if [ "$n" = 10 ]; then search_logs_and_db_for_key "$project"; fi
}

search_logs_and_db_for_key() {
  local project=$1 out="$EVID/lane-10" key secret postgres logs dump in_logs in_db container
  key=$(cat "$out/key-for-host-search.txt" 2>/dev/null) || die "no $out/key-for-host-search.txt; run lane 10's check first"
  secret=${key%??}
  postgres=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=postgres" | head -n 1)
  [ -n "$postgres" ] || die "no running postgres in project $project"
  logs="$out/compose-logs.txt"
  dump="$out/.dump.sql"
  : >"$logs"
  for container in $(docker ps -aq --filter "label=com.docker.compose.project=$project"); do
    docker logs "$container" >>"$logs" 2>&1
  done
  docker exec "$postgres" pg_dumpall -U postgres >"$dump"
  in_logs=$(grep -cF -- "$secret" "$logs" || true)
  in_db=$(grep -cF -- "$secret" "$dump" || true)
  {
    echo "key under test: ${#key} characters, ending ${key: -2}; searched for its first ${#secret}"
    echo "container logs of $project: $(wc -l <"$logs" | tr -d ' ') lines; lines with the key: $in_logs"
    echo "pg_dumpall of $project: $(wc -c <"$dump" | tr -d ' ') bytes; lines with the key: $in_db (the dump is deleted after the search)"
  } | tee "$out/p10-no-key-host.txt"
  rm -f "$dump" "$out/key-for-host-search.txt"
  if [ "$in_logs" -ne 0 ] || [ "$in_db" -ne 0 ]; then
    echo "FAIL: the full key is in a log or the database" | tee -a "$out/p10-no-key-host.txt"
    return 1
  fi
  echo "PASS: the full key is in no log and no table" | tee -a "$out/p10-no-key-host.txt"
}

own() {
  local build=
  if [ "${1:-}" = --no-build ]; then
    build=--no-build
    shift
  fi
  local lanes=$1 worktree=$2 project=$3 tag=$4 portal_port=$5 api_port=$6 n8n_port=$7 status=0 n
  case "$lanes" in
    2,3 | 4 | 5 | 6 | 11) ;;
    *) die "own runs \"2,3\", \"4\", \"5\", \"6\" or \"11\", not $lanes" ;;
  esac
  down_on_exit down "$worktree" "$project"
  up ${build:+"$build"} "$worktree" "$project" "$tag" "$portal_port" "$api_port" "$n8n_port"
  for n in ${lanes//,/ }; do
    mkdir -p "$EVID/lane-$n"
    check "$project" --grep "@lane$n " 2>&1 | tee "$EVID/lane-$n/playwright.log" || status=$?
    [ "$status" -eq 0 ] || break
  done
  trap - EXIT
  down "$worktree" "$project"
  return "$status"
}

# A command that brings up its own stack calls this first, so every way out, a failed step or a die included, takes
# the stack down with its volumes. It clears the trap before its own down.
down_on_exit() {
  # shellcheck disable=SC2064 # the worktree and project are fixed now, quoted by printf %q, as the caller's locals are gone at exit
  trap "$(printf '%q ' "$@")" EXIT
}

# The sign-in stack adds the mock identity provider. It publishes no host port, so it can run beside another stack.
compose_oidc() {
  local worktree=$1 project=$2
  shift 2
  compose "$worktree" "$project" -f "$worktree/deploy/compose.oidc.yaml" "$@"
}

down_oidc() {
  local worktree=$1 project=$2
  mkdir -p "$EVID/stacks"
  compose_oidc "$worktree" "$project" --profile e2e logs --no-color >"$EVID/stacks/$project-compose.log" 2>&1 || true
  compose_oidc "$worktree" "$project" --profile e2e down -v --remove-orphans
}

signin() {
  local build=
  if [ "${1:-}" = --no-build ]; then
    build=--no-build
    shift
  fi
  local worktree=$1 project=$2 tag=$3 out="$EVID/signin" status=0 portal
  disk
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks" "$out"
  down_on_exit down_oidc "$worktree" "$project"
  WAB_IMAGE_TAG=$tag compose_oidc "$worktree" "$project" up ${build:+"$build"} --wait --wait-timeout 400 >"$EVID/stacks/$project-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$project-up.log" >&2; die "$project did not become healthy"; }
  portal=$(portal_of "$project")
  [ -n "$portal" ] || die "no running Portal in project $project"
  docker exec "$portal" wget -qSO- http://platform-api:8000/healthz/ready 2>&1 | tee "$out/ready.txt" || status=$?
  E2E_AUTH=oidc check "$project" --grep '@signin-not-on-list ' 2>&1 | tee "$out/not-on-list.log" || status=$?
  # P1's lane 2 writes its evidence under $EVID/signin/lane-2.
  E2E_AUTH=oidc RUNNER_EVID=/evidence/signin runner_in "$project" npx playwright test -c e2e/checks/playwright.config.ts p1.check.ts --grep '@lane2 ' 2>&1 | tee "$out/p1-lane2.log" || status=$?
  trap - EXIT
  down_oidc "$worktree" "$project"
  return "$status"
}

size() {
  local out="$EVID/perf" name dir total
  mkdir -p "$out"
  : >"$out/first-load-js.txt"
  for pair in "trunk:$1" "head:$2"; do
    name=${pair%%:*}
    dir=${pair#*:}/portal/dist
    [ -f "$dir/index.html" ] || die "no $dir/index.html; run gates on that worktree first, which builds it"
    total=0
    for src in $(grep -oE '<script[^>]*src="[^"]+"' "$dir/index.html" | sed -E 's/.*src="([^"]+)".*/\1/'); do
      bytes=$(gzip -c "$dir$src" | wc -c | tr -d ' ')
      echo "$name $src gzip=$bytes" | tee -a "$out/first-load-js.txt"
      total=$((total + bytes))
    done
    echo "$name total gzip=$total" | tee -a "$out/first-load-js.txt"
  done
  node -e '
    const fs = require("fs"), file = process.argv[1]
    const totals = Object.fromEntries([...fs.readFileSync(file, "utf8").matchAll(/^(trunk|head) total gzip=(\d+)$/gm)].map((m) => [m[1], Number(m[2])]))
    const grew = totals.head - totals.trunk
    const line = `first-load growth: ${grew} bytes gzip; rule: at most 30720: ${grew <= 30720 ? "PASS" : "FAIL"}`
    fs.appendFileSync(file, line + "\n")
    console.log(line)
    process.exit(grew <= 30720 ? 0 : 1)
  ' "$out/first-load-js.txt"
}

perf() {
  local project=$1 samples=${2:-5}
  mkdir -p "$EVID/perf"
  rm -f "$EVID"/perf/lcp-*.json
  check "$project" --grep @seed
  for i in $(seq 1 "$samples"); do
    TARGET=head SAMPLE=$i check "$project" --grep @perf
  done
  node -e '
    const fs = require("fs"), dir = process.argv[1]
    const rows = fs.readdirSync(dir).filter((f) => /^lcp-head-.*\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8"))).sort((a, b) => a.sample - b.sample)
    const median = (key) => rows.map((r) => r[key]).sort((a, b) => a - b)[Math.floor(rows.length / 2)]
    const lcp = median("lcp"), drawn = median("rowsDrawn"), pass = lcp < 2500 && drawn < 2500
    const lines = [
      `head: ${rows.map((r) => `#${r.sample} paint ${r.lcp.toFixed(0)} ms, every row drawn ${r.rowsDrawn.toFixed(0)} ms, ${r.rows} people (${r.element})`).join(", ")}`,
      `head median: paint ${lcp.toFixed(0)} ms, every row drawn ${drawn.toFixed(0)} ms`,
      `rule: both under 2500 ms: ${pass ? "PASS" : "FAIL"}`,
    ]
    fs.writeFileSync(`${dir}/lcp-summary.txt`, lines.join("\n") + "\n")
    console.log(lines.join("\n"))
    process.exit(pass ? 0 : 1)
  ' "$EVID/perf"
}

video() {
  local project=$1
  check "$project" --grep @review-video
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -i "$EVID/p10-review.webm" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$EVID/p10-review.mp4"
  fi
  ls -la "$EVID"/p10-review.*
}

command=${1:-}
[ -n "$command" ] || die "usage: p10.sh <disk|gates|up|down|check|live|lane1|lane|own|signin|size|perf|video> ..."
shift
case "$command" in
  disk | gates | up | down | check | live | lane1 | lane | own | signin | size | perf | video) "$command" "$@" ;;
  *) die "unknown command $command" ;;
esac
