#!/usr/bin/env bash
# Checker probes for P14 of docs/design/rebuild-plan.md: the rebuilt app on Azure, after the operator's deploy.
# docs/evidence/deploy/README.md is the runbook. Rerun any step on its own. The browser lanes are in
# portal/e2e/checks/p14.check.ts, and run on this machine's Playwright, not in the runner image, because Azure signs
# people in through Entra ID.
#
# usage: scripts/checks/p14.sh <command> [arguments]
#
#   settings               print the settings below, and check that Azure answers
#   signin <who>           open a browser at the Azure Portal and sign in as the test account for <who>: operator,
#                          approver or outsider. Saves the browser state in $P14_STATE_DIR/<who>.json
#   forget                 delete the saved sign-ins
#   up <worktree>          the local stack at head for lane 1 and perf: deploy/compose.yaml only, so dev sign-in and
#                          the real GitHub, as on Azure
#   down <worktree>        logs, then down -v
#   lane <n>               lane n of the plan, 1 to 10. Lane 1 also needs the local stack
#   perf                   Home's paint and the run page's event delay, on the local stack and on Azure, interleaved
#   all                    lanes 3, 7, 2, 9, 1, 4, 5 and 10, then perf. Lanes 6 and 8 need the operator, so run them
#                          on their own
#
# Who must be there:
#   signin   the operator signs in by hand, once per test account
#   lane 5   the operator's own `az login`, with Cosmos DB's Data Reader role on the account (the runbook says how)
#   lane 6   the operator types the gateway key into the browser. This script never sees it
#   lane 8   restarts the platform-api container app with the operator's `az login`, after asking
#
# Settings. None is a secret, and this script writes none to disk. The saved sign-ins hold Entra ID cookies, so they
# live outside the repo, readable by their owner only.
#   AZURE_PORTAL_URL      the Portal's address that deploy.yml printed, https://portal.<domain> (needed)
#   AZURE_API_URL         platform-api's address [AZURE_PORTAL_URL with portal. changed to platform-api.]
#   AZURE_RESOURCE_GROUP  [rg-wab-dev], for lanes 5 and 8
#   COSMOS_ACCOUNT        the account deploy.yml printed [the group's only cosmos-wab- account], for lane 5
#   P14_STATE_DIR         [$HOME/.wab-p14] the saved sign-ins. Refused inside the repo
#   P14_RESTART_OK        yes skips lane 8's question
#   LOCAL_PORTAL_URL      [http://localhost:$PORTAL_HOST_PORT], PORTAL_HOST_PORT [8080], PLATFORM_API_HOST_PORT [8000]
#   P14_PROJECT           [p14-local] the local stack's compose project
#   ENV_FILE              [$EVID/env/.env] the local stack's secrets, made by deploy/make-env.sh
#   EVID                  [/tmp/swarm-p14] evidence folder, one sub-folder per lane
#   ZAP_IMAGE             [the image scripts/dast.sh pins]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
EVID=${EVID:-/tmp/swarm-p14}
ENV_FILE=${ENV_FILE:-$EVID/env/.env}
AZURE_PORTAL_URL=${AZURE_PORTAL_URL:-}
AZURE_PORTAL_URL=${AZURE_PORTAL_URL%/}
AZURE_API_URL=${AZURE_API_URL:-${AZURE_PORTAL_URL/:\/\/portal./://platform-api.}}
AZURE_API_URL=${AZURE_API_URL%/}
RG=${AZURE_RESOURCE_GROUP:-rg-wab-dev}
P14_STATE_DIR=${P14_STATE_DIR:-$HOME/.wab-p14}
PORTAL_HOST_PORT=${PORTAL_HOST_PORT:-8080}
PLATFORM_API_HOST_PORT=${PLATFORM_API_HOST_PORT:-8000}
LOCAL_PORTAL_URL=${LOCAL_PORTAL_URL:-http://localhost:$PORTAL_HOST_PORT}
P14_PROJECT=${P14_PROJECT:-p14-local}
ZAP_IMAGE=${ZAP_IMAGE:-$(sed -n 's/^ZAP_IMAGE="\${ZAP_IMAGE:-\(.*\)}"$/\1/p' "$root/scripts/dast.sh")}

die() { echo "p14.sh: $*" >&2; exit 2; }
pass() { echo "PASS lane $1: $2" | tee -a "$EVID/summary.txt"; }
fail() { echo "FAIL lane $1: $2" | tee -a "$EVID/summary.txt"; return 1; }

need_azure() {
  [[ $AZURE_PORTAL_URL =~ ^https://portal\.[^/]+$ ]] ||
    die "set AZURE_PORTAL_URL to the Portal's address that deploy.yml printed, such as https://portal.<domain>"
  [[ $AZURE_API_URL =~ ^https://[^/]+$ ]] || die "AZURE_API_URL must be platform-api's https address"
}

# Sets STATE_REAL, and stops the script when the folder is inside the repo.
state_dir() {
  mkdir -p "$P14_STATE_DIR"
  STATE_REAL=$(cd "$P14_STATE_DIR" && pwd -P)
  case "$STATE_REAL/" in
    "$(cd "$root" && pwd -P)"/*)
      rmdir "$STATE_REAL" 2>/dev/null || true
      die "P14_STATE_DIR is inside the repo. The saved sign-ins hold cookies, so keep them out of git."
      ;;
  esac
  chmod 700 "$STATE_REAL"
}

pw() {
  state_dir
  mkdir -p "$EVID"
  (cd "$root/portal" && EVID="$EVID" AZURE_PORTAL_URL="$AZURE_PORTAL_URL" LOCAL_PORTAL_URL="$LOCAL_PORTAL_URL" \
    P14_STATE_DIR="$STATE_REAL" npx playwright test -c e2e/checks/playwright.config.ts p14.check.ts "$@")
}

docker_free_mb() {
  docker run --rm alpine:3.20 df -m / | awk 'NR==2 {print $4}'
}

settings() {
  echo "AZURE_PORTAL_URL=$AZURE_PORTAL_URL"
  echo "AZURE_API_URL=$AZURE_API_URL"
  echo "AZURE_RESOURCE_GROUP=$RG"
  echo "COSMOS_ACCOUNT=${COSMOS_ACCOUNT:-(the only cosmos-wab- account in the group)}"
  state_dir
  echo "P14_STATE_DIR=$STATE_REAL"
  echo "LOCAL_PORTAL_URL=$LOCAL_PORTAL_URL"
  echo "EVID=$EVID"
  echo "ZAP_IMAGE=$ZAP_IMAGE"
  need_azure
  curl -sS -o /dev/null --max-time 30 -w "GET $AZURE_PORTAL_URL/ %{http_code}\n" "$AZURE_PORTAL_URL/"
  curl -sS -o /dev/null --max-time 30 -w "GET $AZURE_API_URL/healthz %{http_code}\n" "$AZURE_API_URL/healthz"
  local who
  for who in operator approver outsider; do
    if [ -f "$P14_STATE_DIR/$who.json" ]; then echo "saved sign-in: $who"; else echo "no saved sign-in yet: $who"; fi
  done
}

signin() {
  local who=${1:-}
  case "$who" in
    operator | approver | outsider) ;;
    *) die "signin takes operator, approver or outsider" ;;
  esac
  need_azure
  P14_SIGNIN=$who pw --grep "@signin\$" --headed --retries 0
}

forget() {
  rm -f "$P14_STATE_DIR/operator.json" "$P14_STATE_DIR/approver.json" "$P14_STATE_DIR/outsider.json"
  echo "deleted the saved sign-ins in $P14_STATE_DIR"
}

compose() {
  local worktree=$1
  shift
  PORTAL_HOST_PORT=$PORTAL_HOST_PORT PLATFORM_API_HOST_PORT=$PLATFORM_API_HOST_PORT \
    docker compose -p "$P14_PROJECT" --env-file "$ENV_FILE" -f "$worktree/deploy/compose.yaml" "$@"
}

up() {
  local worktree=${1:?up takes the worktree at head} free
  free=$(docker_free_mb)
  echo "Docker disk: $free MB free"
  [ "$free" -ge 3072 ] || die "less than 3 GB free on the Docker disk; the stack needs about that, Cosmos DB's emulator included"
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE; copy deploy/make-env.sh next to it and run it"
  mkdir -p "$EVID/stacks"
  compose "$worktree" up --build --wait --wait-timeout 600 >"$EVID/stacks/$P14_PROJECT-up.log" 2>&1 ||
    { tail -n 30 "$EVID/stacks/$P14_PROJECT-up.log" >&2; die "$P14_PROJECT did not become healthy"; }
  curl -sS -o "$EVID/stacks/$P14_PROJECT-ready.json" -w "GET /healthz/ready %{http_code}\n" \
    "http://localhost:$PLATFORM_API_HOST_PORT/healthz/ready"
}

down() {
  local worktree=${1:?down takes the worktree at head}
  mkdir -p "$EVID/stacks"
  compose "$worktree" logs --no-color >"$EVID/stacks/$P14_PROJECT-compose.log" 2>&1 || true
  compose "$worktree" down -v --remove-orphans
}

lane_browser() {
  local n=$1
  shift
  mkdir -p "$EVID/lane-$n"
  pw --grep "@lane$n\$" "$@" 2>&1 | tee "$EVID/lane-$n/playwright.log"
  return "${PIPESTATUS[0]}"
}

lane1() {
  curl -sS -o /dev/null --max-time 10 "$LOCAL_PORTAL_URL/" || die "no local stack at $LOCAL_PORTAL_URL; start it with p14.sh up <worktree>"
  echo "Trunk was never deployed with these modules. The local stack at head stands in for trunk." | tee "$EVID/lane-1/trunk.txt"
  if lane_browser 1; then pass 1 "the same steps to the approval gate on the local stack and on Azure (lane-1/p14-local-azure.png)"; else fail 1 "see lane-1/playwright.log"; fi
}

lane3() {
  local out="$EVID/lane-3" code
  code=$(curl -sS --max-time 30 -o "$out/p14-ready.json" -w '%{http_code}' "$AZURE_API_URL/healthz/ready") || code=none
  [ -f "$out/p14-ready.json" ] || : >"$out/p14-ready.json"
  jq . "$out/p14-ready.json" 2>/dev/null || cat "$out/p14-ready.json"
  if [ "$code" = 200 ] && jq -e '
      .ready == true
      and (.checks | length > 0 and all(.ok))
      and any(.checks[]; .name == "activity_copy")
      and any(.checks[]; .name == "workflows" and (.detail | test("run_failure_reporter active")))' \
    "$out/p14-ready.json" >/dev/null; then
    pass 3 "GET /healthz/ready is 200, every part is ready, the copy to Cosmos DB and n8n's error workflow included"
  else
    fail 3 "GET /healthz/ready answered $code; lane-3/p14-ready.json says which part is not ready"
  fi
}

lane5() {
  local out="$EVID/lane-5" run account endpoint body code now
  lane_browser 5 || { fail 5 "could not read lane 4's run from the API; see lane-5/playwright.log"; return 1; }
  run=$(jq -r .run_id "$out/api-events.json")
  account=${COSMOS_ACCOUNT:-$(az cosmosdb list --resource-group "$RG" --query "[?starts_with(name, 'cosmos-wab-')].name | [0]" --output tsv)}
  [ -n "$account" ] || die "no Cosmos DB account named cosmos-wab-* in $RG; set COSMOS_ACCOUNT"
  endpoint="https://$account.documents.azure.com"
  body=$(jq -cn --arg run "$run" '{query: "SELECT c.id, c.runId, c.seq, c.kind, c.ts FROM c WHERE c.runId = @run", parameters: [{name: "@run", value: $run}]}')
  now=$(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S GMT')
  # The token is the operator's own, from az, for this one call. Bash's builtin printf hands it to curl on stdin, so it
  # never shows in a process list and is never written to a file.
  code=$(printf 'Authorization: type%%3Daad%%26ver%%3D1.0%%26sig%%3D%s\n' \
    "$(az account get-access-token --resource "$endpoint" --query accessToken --output tsv)" |
    curl -sS --max-time 30 -o "$out/cosmos-answer.json" -w '%{http_code}' -X POST "$endpoint/dbs/activity/colls/run_events/docs" \
      -H @- -H "x-ms-date: $now" -H "x-ms-version: 2018-12-31" -H "Content-Type: application/query+json" \
      -H "x-ms-documentdb-isquery: True" -H "x-ms-documentdb-partitionkey: [\"$run\"]" -H "x-ms-max-item-count: 1000" \
      --data "$body") || code=none
  if [ "$code" = 403 ]; then
    echo "Cosmos DB refused your sign-in. Give yourself its Data Reader role on the activity database, once:" >&2
    echo "  az cosmosdb sql role assignment create --account-name $account --resource-group $RG \\" >&2
    echo "    --role-definition-id 00000000-0000-0000-0000-000000000001 --scope /dbs/activity \\" >&2
    echo "    --principal-id \$(az ad signed-in-user show --query id --output tsv)" >&2
    fail 5 "403 from Cosmos DB"
    return 1
  fi
  [ "$code" = 200 ] || { fail 5 "Cosmos DB answered $code; see lane-5/cosmos-answer.json"; return 1; }
  jq --arg account "$account" --arg run "$run" '{account: $account, run_id: $run, partition: $run, count: (.Documents | length), items: (.Documents | sort_by(.seq))}' \
    "$out/cosmos-answer.json" >"$out/p14-cosmos.json"
  if jq -en --slurpfile api "$out/api-events.json" --slurpfile cosmos "$out/p14-cosmos.json" '
      ($api[0].events | map({seq, kind})) as $want
      | ($cosmos[0].items | map({seq, kind})) as $got
      | $want == $got and ($cosmos[0].items | all(.runId == $api[0].run_id))' >/dev/null; then
    pass 5 "every one of the run's $(jq '.events | length' "$out/api-events.json") events is in Cosmos DB under the run's partition (lane-5/p14-cosmos.json)"
  else
    fail 5 "the Cosmos DB items differ from the API's events; compare lane-5/api-events.json with lane-5/p14-cosmos.json"
  fi
}

lane6() {
  echo "Lane 6 opens Settings in a browser. Pick AI Singapore gateway, paste the key, press Connect, choose Claude Haiku 5.5, then press Test and save."
  if lane_browser 6 --headed; then pass 6 "Test and save succeeded, so SETTINGS_ENCRYPTION_KEY is set (lane-6/p14-model.png)"; else fail 6 "see lane-6/playwright.log"; fi
}

lane7() {
  local out="$EVID/lane-7" url result status line ok=1
  : >"$out/p14-https.txt"
  for url in "${AZURE_API_URL/https:/http:}/healthz/ready" "${AZURE_PORTAL_URL/https:/http:}/"; do
    status=0
    result=$(curl -sS -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$url" 2>/dev/null) || status=$?
    # curl's exit 7 is a refused connection, 52 an empty reply and 56 a reset. Any other failure, such as a host
    # that does not resolve, says nothing about plain http, so it fails the lane.
    case "$status:$result" in
      0:30[1278]\ https://*) line=$result ;;
      7:* | 52:* | 56:*) line="refused (curl exit $status)" ;;
      0:*) line=$result ok=0 ;;
      *) line="no answer (curl exit $status)" ok=0 ;;
    esac
    echo "$url -> $line" | tee -a "$out/p14-https.txt"
  done
  if [ "$ok" = 1 ]; then pass 7 "plain http is refused or sent to https (lane-7/p14-https.txt)"; else fail 7 "plain http was not refused or sent to https (lane-7/p14-https.txt)"; fi
}

lane8() {
  local out="$EVID/lane-8" pid revision waited=0 answer
  if [ "${P14_RESTART_OK:-}" != yes ]; then
    read -r -p "Lane 8 restarts the platform-api container app in $RG while a run page is open. Go ahead? [y/N] " answer
    [ "$answer" = y ] || [ "$answer" = Y ] || die "lane 8 not run"
  fi
  rm -f "$out/stream-open" "$out/restarted"
  mkdir -p "$out"
  lane_browser 8 &
  pid=$!
  until [ -f "$out/stream-open" ]; do
    kill -0 "$pid" 2>/dev/null || { wait "$pid" || true; fail 8 "the page stopped before its stream opened; see lane-8/playwright.log"; return 1; }
    [ "$waited" -lt 600 ] || { kill "$pid"; fail 8 "no open stream after 10 minutes"; return 1; }
    sleep 2
    waited=$((waited + 2))
  done
  revision=$(az containerapp revision list --name platform-api --resource-group "$RG" --query "[?properties.active].name | [0]" --output tsv)
  echo "restarting platform-api revision $revision" | tee "$out/restart.txt"
  az containerapp revision restart --name platform-api --resource-group "$RG" --revision "$revision" --output none
  date -u '+%Y-%m-%dT%H:%M:%SZ' | tee -a "$out/restart.txt" >"$out/restarted"
  if wait "$pid"; then pass 8 "the run page reconnected and showed every event once (lane-8/p14-restart.png)"; else fail 8 "see lane-8/playwright.log"; fi
}

lane9() {
  if lane_browser 9; then pass 9 "someone not on the People list is told to ask an Operator (lane-9/p14-not-on-list.png)"; else fail 9 "see lane-9/playwright.log"; fi
}

lane10() {
  local out="$EVID/lane-10" free status=0 medium
  free=$(docker_free_mb)
  [ "$free" -ge 3072 ] || die "less than 3 GB free on the Docker disk ($free MB); ZAP's image needs about 2 GB"
  cp "$root/dast/zap-rules.conf" "$out/rules.conf"
  docker run --rm --tmpfs /home/zap/.ZAP:rw,exec,uid=1000,gid=1000,size=1g --tmpfs /tmp:rw,exec,size=512m \
    --volume "$out:/zap/wrk:rw" "$ZAP_IMAGE" zap-baseline.py -t "$AZURE_PORTAL_URL" -m 2 -T 10 -c rules.conf \
    -J p14-zap.json -w p14-zap.md -r p14-zap.html >"$out/zap.log" 2>&1 || status=$?
  [ -f "$out/p14-zap.json" ] || { tail -n 20 "$out/zap.log" >&2; fail 10 "ZAP wrote no report"; return 1; }
  medium=$(jq '[.site[].alerts[] | select((.riskcode | tonumber) >= 2)] | length' "$out/p14-zap.json")
  {
    echo "ZAP baseline scan of $AZURE_PORTAL_URL with $ZAP_IMAGE, exit $status"
    grep -E '^FAIL-NEW|^WARN-NEW|^PASS' "$out/zap.log" | tail -n 3 || true
    echo "Medium or High alerts: $medium"
    jq -r '.site[].alerts[] | "\(.riskdesc)  \(.pluginid)  \(.alert)"' "$out/p14-zap.json"
  } | tee "$out/p14-zap.txt"
  if [ "$medium" = 0 ]; then pass 10 "ZAP reports 0 Medium or High findings (lane-10/p14-zap.txt)"; else fail 10 "ZAP reports $medium Medium or High findings (lane-10/p14-zap.txt)"; fi
}

lane() {
  local n=${1:?lane takes a number from 1 to 10}
  need_azure
  mkdir -p "$EVID/lane-$n"
  case "$n" in
    1) lane1 ;;
    2) if lane_browser 2; then pass 2 "Home names the first Operator and Settings shows them as Operator (lane-2/p14-sign-in.png)"; else fail 2 "see lane-2/playwright.log"; fi ;;
    3) lane3 ;;
    4) if lane_browser 4; then pass 4 "the practice Jira holds the approved run's ticket (lane-4/p14-approved.png)"; else fail 4 "see lane-4/playwright.log"; fi ;;
    5) lane5 ;;
    6) lane6 ;;
    7) lane7 ;;
    8) lane8 ;;
    9) lane9 ;;
    10) lane10 ;;
    *) die "lane takes a number from 1 to 10" ;;
  esac
}

perf() {
  need_azure
  curl -sS -o /dev/null --max-time 10 "$LOCAL_PORTAL_URL/" || die "no local stack at $LOCAL_PORTAL_URL; start it with p14.sh up <worktree>"
  mkdir -p "$EVID/perf"
  if pw --grep "@perf\$" 2>&1 | tee "$EVID/perf/playwright.log"; then
    pass perf "Home's median paint under 3 s and the 95th percentile event delay under 2 s on Azure (perf/p14-perf.json)"
  else
    fail perf "see perf/p14-perf.json and perf/playwright.log"
  fi
}

all() {
  local n status=0
  need_azure
  curl -sS -o /dev/null --max-time 10 "$LOCAL_PORTAL_URL/" || die "no local stack at $LOCAL_PORTAL_URL for lane 1 and perf; start it with p14.sh up <worktree>"
  for n in 3 7 2 9 1 4 5 10; do
    lane "$n" || status=1
  done
  perf || status=1
  echo "Lanes 6 and 8 need the operator: run p14.sh lane 6 and p14.sh lane 8."
  return "$status"
}

command=${1:-}
[ -n "$command" ] || { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 2; }
shift
mkdir -p "$EVID"
case "$command" in
  settings | signin | forget | up | down | lane | perf | all) "$command" "$@" ;;
  *) die "unknown command $command; run it with no command for help" ;;
esac
