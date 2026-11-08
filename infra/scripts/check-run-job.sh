#!/bin/sh
# Checks run-job.sh against a fake az and a fake sleep, so nothing talks to Azure and no case
# waits. check.sh runs it in the Terraform image.
# Usage: check-run-job.sh
set -eu

runner="$(cd "$(dirname "$0")" && pwd)/run-job.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/bin"

# The fake az starts execution exec-1. FAKE_POLL_FAILS status calls fail first, the way Azure's
# 503 page does, then the status is FAKE_STATUS. Every call is logged.
cat >"$work/bin/az" <<'FAKE'
#!/bin/sh
echo "$*" >>"$FAKE_LOG"
case "$*" in
  "containerapp job start "*)
    echo exec-1
    ;;
  "containerapp job execution show "*)
    polls=$(grep -c "job execution show" "$FAKE_LOG")
    if [ "$polls" -le "${FAKE_POLL_FAILS:-0}" ]; then
      echo "ERROR: 503 Service Unavailable" >&2
      exit 1
    fi
    echo "${FAKE_STATUS:-Succeeded}"
    ;;
  *)
    echo "fake az: unexpected call: $*" >&2
    exit 2
    ;;
esac
FAKE
printf '#!/bin/sh\nexit 0\n' >"$work/bin/sleep"
chmod +x "$work/bin/az" "$work/bin/sleep"

failures=0

# expect <label> <want: exit status> <VAR=value ...>
expect() {
  label=$1
  want=$2
  shift 2
  : >"$work/log"
  status=0
  env PATH="$work/bin:$PATH" FAKE_LOG="$work/log" "$@" \
    sh "$runner" rg-wab-dev migrate 60 >"$work/out" 2>"$work/err" || status=$?
  if [ "$status" = "$want" ]; then
    echo "ok    $label: exit $status"
  else
    echo "FAIL  $label: wanted exit $want, got $status"
    sed 's/^/      stderr: /' "$work/err"
    failures=$((failures + 1))
  fi
}

expect "two failed polls, then Succeeded" 0 FAKE_POLL_FAILS=2
expect "the execution Failed" 1 FAKE_STATUS=Failed

expect "five failed polls in a row" 1 FAKE_POLL_FAILS=5
if ! grep -q "migrate: could not read the status of execution exec-1" "$work/err"; then
  echo "FAIL  five failed polls in a row: the script did not name the job and execution"
  failures=$((failures + 1))
fi
if [ "$(grep -c "job start" "$work/log")" != 1 ]; then
  echo "FAIL  five failed polls in a row: the job was started more than once"
  failures=$((failures + 1))
fi

if [ "$failures" = 0 ]; then
  echo "check-run-job.sh: all cases behaved as expected"
else
  echo "check-run-job.sh: $failures case(s) failed"
  exit 1
fi
