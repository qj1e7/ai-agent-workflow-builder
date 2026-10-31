#!/usr/bin/env bash
# Runs dast.sh's own run_zap and summary_line with docker replaced by a stub, to show the retry.
# Then runs dast.sh's own closing lines (from "status=0" to the end) on made-up scan logs, to show
# what the script prints and which code it exits with when ZAP did not start, raised an alert, or both.
# usage: zap-port-retry-test.sh scripts/dast.sh
set -uo pipefail
script="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
work="$(mktemp -d "$PWD/zt.XXXX")"
root="$work"; stack_out=out; mkdir -p "$work/out"; cd "$work"
network=n; zap_name=z; ZAP_IMAGE=img; zap_options=""
eval "$(sed -n '/^zap_port=/,/^proxy_failed=/p' "$script")"
eval "$(sed -n '/^run_zap() {/,/^}/p' "$script")"
eval "$(sed -n '/^summary_line() {/,/^}/p' "$script")"
calls="$work/calls"
docker() {
  echo "docker $*" | grep -o -- "-P [0-9]*" >>"$calls"
  case "$MODE" in
    bind-once) if [ "$(wc -l <"$calls")" -eq 1 ]; then
        echo "ERROR org.parosproxy.paros.CommandLine - Terminating ZAP, unable to start the main proxy."; return 3
      fi; echo "FAIL-NEW: 0 FAIL-INPROG: 0 WARN-NEW: 0 WARN-INPROG: 0 INFO: 0 IGNORE: 1 PASS: 112"; return 0 ;;
    bind-always) echo "WARN ExtensionNetwork - Failed to start the main proxy: java.net.BindException Address already in use"
      echo "ERROR org.parosproxy.paros.CommandLine - Terminating ZAP, unable to start the main proxy."; return 3 ;;
    alert) echo "FAIL-NEW: 1 FAIL-INPROG: 0 WARN-NEW: 0 WARN-INPROG: 0 INFO: 0 IGNORE: 0 PASS: 111"; return 1 ;;
  esac
}
echo "Part 1. run_zap, one scan"
for MODE in bind-once bind-always alert; do
  : >"$calls"
  run_zap api rules.conf zap-api-scan.py -t openapi.json 2>"$work/err"; code=$?
  echo "case $MODE: exit $code, docker runs $(wc -l <"$calls" | tr -d ' '), port $(sort -u "$calls" | tr '\n' ' ')"
  sed 's/^/  stderr: /' "$work/err"
  echo "  summary: $(summary_line "$work/out/api.log")"
done

# The closing lines of dast.sh, exactly as written there.
closing="$(sed -n '/^status=0$/,$p' "$script")"
pass_log='FAIL-NEW: 0	FAIL-INPROG: 0	WARN-NEW: 0	WARN-INPROG: 0	INFO: 0	IGNORE: 1	PASS: 112'
alert_log='FAIL-NEW: 1	FAIL-INPROG: 0	WARN-NEW: 0	WARN-INPROG: 0	INFO: 0	IGNORE: 0	PASS: 111'
crash_log='ERROR org.parosproxy.paros.CommandLine - Terminating ZAP, unable to start the main proxy.
ERROR [Errno 5] Failed to connect to ZAP after 180 seconds'
error_log='ERROR [Errno 5] Failed to load the OpenAPI definition'
# usage: ending <case> <api log> <api code> <nginx log> <nginx code> <portal log> <portal code>
ending() {
  echo "case $1:"
  printf '%s\n' "$2" >out/api.log
  printf '%s\n' "$4" >out/api-via-portal.log
  printf '%s\n' "$6" >out/portal.log
  (api_status=$3 nginx_status=$5 portal_status=$7; eval "$closing") >"$work/end" 2>&1
  local code=$?
  sed 's/^/  /' "$work/end"
  echo "  exit $code"
}
echo
echo "Part 2. dast.sh's closing lines, three scans"
ending all-pass "$pass_log" 0 "$pass_log" 0 "$pass_log" 0
ending not-started "$crash_log" 3 "$pass_log" 0 "$pass_log" 0
ending two-not-started "$crash_log" 3 "$crash_log" 3 "$pass_log" 0
ending alert "$pass_log" 0 "$alert_log" 1 "$pass_log" 0
ending not-started-and-alert "$crash_log" 3 "$alert_log" 1 "$pass_log" 0
ending error-before-summary "$error_log" 3 "$pass_log" 0 "$pass_log" 0
cd /; rm -rf "$work"
