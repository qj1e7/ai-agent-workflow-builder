#!/bin/sh
# Checks n8n-editor-gate.sh against a fake az, so nothing talks to Azure. check.sh runs it in the
# Terraform image.
# Usage: check-n8n-editor-gate.sh
set -eu

gate="$(cd "$(dirname "$0")" && pwd)/n8n-editor-gate.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/bin"

# The fake az answers from FAKE_JOBS (how many jobs named bootstrap exist) and FAKE_SUCCEEDED (how
# many of its executions succeeded). FAKE_FAIL=list or execution makes that call fail. Every call
# is logged, so a case can check that az was not asked at all.
cat >"$work/bin/az" <<'EOF'
#!/bin/sh
echo "$*" >>"$FAKE_LOG"
case "$*" in
  "containerapp job list "*)
    [ "${FAKE_FAIL:-}" = list ] && { echo "ERROR: (AuthorizationFailed) fake" >&2; exit 1; }
    echo "${FAKE_JOBS:-0}"
    ;;
  "containerapp job execution list "*)
    [ "${FAKE_FAIL:-}" = execution ] && { echo "ERROR: (ResourceNotFound) fake" >&2; exit 3; }
    echo "${FAKE_SUCCEEDED:-0}"
    ;;
  *)
    echo "fake az: unexpected call: $*" >&2
    exit 2
    ;;
esac
EOF
chmod +x "$work/bin/az"

failures=0

# expect <label> <want: true, false or stop> <note: note or none> <requested> [VAR=value ...]
# "stop" means the gate exits non-zero, which stops the deploy.
expect() {
  label=$1
  want=$2
  note=$3
  requested=$4
  shift 4
  : >"$work/log"
  : >"$work/summary"
  status=0
  got=$(env PATH="$work/bin:$PATH" FAKE_LOG="$work/log" GITHUB_STEP_SUMMARY="$work/summary" "$@" \
    sh "$gate" "$requested" rg-wab-dev 2>"$work/err") || status=$?
  [ "$status" -ne 0 ] && got=stop
  if grep -q "n8n stays internal until the first bootstrap has created its owner" "$work/summary"; then
    got_note=note
  else
    got_note=none
  fi
  if [ "$got" = "$want" ] && [ "$got_note" = "$note" ]; then
    echo "ok    $label: $got, $got_note"
  else
    echo "FAIL  $label: wanted $want and $note, got $got and $got_note"
    sed 's/^/      stderr: /' "$work/err"
    failures=$((failures + 1))
  fi
}

expect "editor not asked for" false none false
if [ -s "$work/log" ]; then
  echo "FAIL  editor not asked for: the gate called az"
  failures=$((failures + 1))
fi
expect "a new environment, no bootstrap job yet" false note true FAKE_JOBS=0
expect "the bootstrap job exists, no execution succeeded" false note true FAKE_JOBS=1 FAKE_SUCCEEDED=0
expect "the bootstrap job has succeeded before" true none true FAKE_JOBS=1 FAKE_SUCCEEDED=3
expect "az cannot list the jobs" stop none true FAKE_FAIL=list
expect "az cannot list the executions" stop none true FAKE_JOBS=1 FAKE_FAIL=execution
expect "az answers something that is not a count" stop none true FAKE_JOBS=1 FAKE_SUCCEEDED=Succeeded
expect "a switch that is neither true nor false" stop none yes
if ! grep -q "N8N_EDITOR_EXTERNAL must be true or false" "$work/err"; then
  echo "FAIL  a switch that is neither true nor false: the gate did not say why"
  failures=$((failures + 1))
fi

if [ "$failures" = 0 ]; then
  echo "check-n8n-editor-gate.sh: all cases behaved as expected"
else
  echo "check-n8n-editor-gate.sh: $failures case(s) failed"
  exit 1
fi
