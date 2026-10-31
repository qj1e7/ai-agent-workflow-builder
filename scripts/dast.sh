#!/usr/bin/env bash
# OWASP ZAP against the real stack: an API scan of platform-api from its OpenAPI document, and a baseline scan of the Portal.
# Needs Docker and nothing else. Prints PASS or FAIL. Reports land in dast/out/.
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

set +e
run_zap api rules.conf zap-api-scan.py -t openapi.json -f openapi -O http://platform-api:8000 -T 10
api_status=$?
run_zap api-via-portal rules-via-portal.conf zap-api-scan.py -t openapi-public.json -f openapi -O http://portal:8080 -T 10
nginx_status=$?
run_zap portal rules.conf zap-baseline.py -t http://portal:8080 -m 2 -T 10
portal_status=$?
set -e

echo
status=0
report() {
  local name="$1" code="$2" label="$3"
  if [ "$code" -eq 0 ]; then
    echo "PASS $name: $(summary_line "$stack_out/$label.log")"
  else
    echo "FAIL $name (exit $code): $(summary_line "$stack_out/$label.log")"
    status=1
  fi
}
report "platform-api scan   " "$api_status" api
report "API through nginx   " "$nginx_status" api-via-portal
report "Portal baseline     " "$portal_status" portal
echo "Reports: $stack_out/{api,api-via-portal,portal}.{html,json,md}"
if [ "$status" -ne 0 ]; then
  echo "FAIL: a rule not in dast/zap-rules.conf raised an alert. Fix the cause, or record a false positive there with its reason."
  exit 1
fi
echo "PASS: ZAP found nothing outside the reasons recorded in dast/zap-rules.conf."
