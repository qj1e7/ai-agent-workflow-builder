#!/usr/bin/env bash
# Runs dast.sh's own run_zap and summary_line with docker replaced by a stub, to show the retry.
set -uo pipefail
script="$1"
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
for MODE in bind-once bind-always alert; do
  : >"$calls"
  run_zap api rules.conf zap-api-scan.py -t openapi.json 2>"$work/err"; code=$?
  echo "case $MODE: exit $code, docker runs $(wc -l <"$calls" | tr -d ' '), port $(sort -u "$calls" | tr '\n' ' ')"
  sed 's/^/  stderr: /' "$work/err"
  echo "  summary: $(summary_line "$work/out/api.log")"
done
rm -rf "$work"
