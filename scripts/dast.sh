#!/usr/bin/env bash
# OWASP ZAP against the real stack: an API scan of platform-api from its OpenAPI document, and a baseline scan of the Portal.
# Needs Docker and nothing else. Prints PASS or FAIL. Reports land in dast/out/.
# Exit codes: 0 pass; 1 an alert, or ZAP stopped with an error before its summary; 2 the stack did not start;
# 3 ZAP did not start for a scan and nothing else failed, so running the job again is the fix.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# ZAP 2.17.0, the 7 Aug 2026 build, pinned by digest.
ZAP_IMAGE="${ZAP_IMAGE:-zaproxy/zap-stable:20260807@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef}"

stack_default_project=wab-dast
stack_out="dast/out"
# shellcheck source=scripts/lib/stack.sh
source scripts/lib/stack.sh

zap_name="${project}-zap"
cleanup() {
  docker rm -f "$zap_name" >/dev/null 2>&1 || true
  stack_stop
}
trap cleanup EXIT

stack_prepare
rm -f "$stack_out"/*.html "$stack_out"/*.json "$stack_out"/*.md "$stack_out"/*.log "$stack_out"/*.conf

# Every request ZAP sends carries Alice's dev header, so it reaches the routes that need a signed-in Operator and Approver.
# The Accept header is pinned to JSON so the events route answers one page and not a stream that never ends.
zap_options="-silent"
zap_options+=" -config replacer.full_list(0).description=dev-user -config replacer.full_list(0).enabled=true"
zap_options+=" -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=X-Dev-User"
zap_options+=" -config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement=alice"
zap_options+=" -config replacer.full_list(1).description=json-only -config replacer.full_list(1).enabled=true"
zap_options+=" -config replacer.full_list(1).matchtype=REQ_HEADER -config replacer.full_list(1).matchstr=Accept"
zap_options+=" -config replacer.full_list(1).regex=false -config replacer.full_list(1).replacement=application/json"

echo "Starting the stack as compose project $project (no host ports)."
if ! stack_start; then
  exit 2
fi
stack_seed openapi >"$stack_out/openapi.json"
# Through nginx only the /api/ routes exist. /healthz and /internal are not published, and ZAP would flag the Portal page it gets back.
stack_seed openapi-public >"$stack_out/openapi-public.json"

# ZAP's proxy listens on a fixed port. Left to choose, the scan script picks a random port from
# 32768 to 61000, the range the kernel also gives every outgoing connection, so once something in
# the container held it when ZAP tried to bind (issue #79). 8090 is outside that range.
zap_port=8090
proxy_failed="unable to start the main proxy"

# The scanner joins the project's own network and is given only that network's host names as targets.
# If ZAP still cannot start its proxy, the scan runs once more, so a crash at start is not read as an alert.
# The second try writes the same log file, so it overwrites the first try's log. The first try's error lines
# are printed to the job's output before the retry, so they are kept there.
run_zap() {
  local label="$1" rules="$2" try code=0
  shift 2
  for try in 1 2; do
    # ZAP unpacks its add-ons into its home and temp folders. In memory, they leave nothing behind and need no free disk.
    docker run --rm --name "$zap_name" --network "$network" \
      --tmpfs /home/zap/.ZAP:rw,exec,uid=1000,gid=1000,size=1g --tmpfs /tmp:rw,exec,size=512m \
      --volume "$root/$stack_out:/zap/wrk:rw" \
      "$ZAP_IMAGE" "$@" -P "$zap_port" -c "$rules" -z "$zap_options" \
      -r "$label.html" -J "$label.json" -w "$label.md" >"$stack_out/$label.log" 2>&1
    code=$?
    if ! grep -q "$proxy_failed" "$stack_out/$label.log"; then
      return "$code"
    fi
    echo "ZAP could not start its proxy for the $label scan (try $try of 2):" >&2
    grep -E "BindException|$proxy_failed" "$stack_out/$label.log" >&2 || true
  done
  return "$code"
}

summary_line() {
  if grep -q "$proxy_failed" "$1"; then
    echo "ZAP did not start its proxy, so nothing was scanned"
    return
  fi
  grep -E "^FAIL-NEW" "$1" | tail -n 1 || echo "no summary"
}

api_status=0
portal_status=0
nginx_status=0

cp dast/zap-rules.conf "$stack_out/rules.conf"
cat dast/zap-rules.conf dast/zap-rules-via-portal.conf >"$stack_out/rules-via-portal.conf"

# -T is how many minutes ZAP's scan script waits for ZAP to start, and then for the passive scan to finish.
# When ZAP cannot start its proxy, the script waits all of it before it gives up, once per try.
# 3 minutes is far above a normal start. In CI run 41098264253, ZAP reached its proxy 5 seconds after Java
# started, and the whole API scan, passive wait included, took under a minute. A scan that never starts now
# costs 2 x 3 minutes, not 2 x 10, inside the CI job's 35-minute limit.
zap_wait=3

set +e
run_zap api rules.conf zap-api-scan.py -t openapi.json -f openapi -O http://platform-api:8000 -T "$zap_wait"
api_status=$?
run_zap api-via-portal rules-via-portal.conf zap-api-scan.py -t openapi-public.json -f openapi -O http://portal:8080 -T "$zap_wait"
nginx_status=$?
run_zap portal rules.conf zap-baseline.py -t http://portal:8080 -m 2 -T "$zap_wait"
portal_status=$?
set -e

echo
status=0
not_started=0
errored=0
# A scan that fails is one of three things, and each gets its own closing line:
# ZAP did not start (nothing was scanned, so run the job again), ZAP stopped with an error before its
# summary, or a real alert (the summary line is there).
report() {
  local name="$1" code="$2" label="$3"
  if [ "$code" -eq 0 ]; then
    echo "PASS $name: $(summary_line "$stack_out/$label.log")"
    return
  fi
  echo "FAIL $name (exit $code): $(summary_line "$stack_out/$label.log")"
  if grep -q "$proxy_failed" "$stack_out/$label.log"; then
    not_started=$((not_started + 1))
  elif grep -q "^FAIL-NEW" "$stack_out/$label.log"; then
    status=1
  else
    errored=$((errored + 1))
  fi
}
report "platform-api scan   " "$api_status" api
report "API through nginx   " "$nginx_status" api-via-portal
report "Portal baseline     " "$portal_status" portal
echo "Reports: $stack_out/{api,api-via-portal,portal}.{html,json,md}"
if [ "$not_started" -ne 0 ]; then
  echo "FAIL: ZAP did not start for $not_started scan(s), so nothing was scanned there. Run the job again."
fi
if [ "$errored" -ne 0 ]; then
  echo "FAIL: ZAP stopped with an error before its summary for $errored scan(s). Read that scan's log in $stack_out/."
fi
if [ "$status" -ne 0 ]; then
  echo "FAIL: a rule not in dast/zap-rules.conf raised an alert. Fix the cause, or record a false positive there with its reason."
fi
# An alert or an error needs a person to look, so it wins over a scan that only needs running again.
if [ "$status" -ne 0 ] || [ "$errored" -ne 0 ]; then
  exit 1
fi
if [ "$not_started" -ne 0 ]; then
  exit 3
fi
echo "PASS: ZAP found nothing outside the reasons recorded in dast/zap-rules.conf."
