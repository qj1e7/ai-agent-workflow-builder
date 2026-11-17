#!/bin/sh
# Checks n8n-paths-closed.sh against a fake curl, so nothing talks to Azure. check.sh runs it in
# the Terraform image.
# Usage: check-n8n-paths-closed.sh
set -eu

check="$(cd "$(dirname "$0")" && pwd)/n8n-paths-closed.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/bin"

# The fake curl answers 403 with Container Apps' refusal, unless FAKE_OPEN names a path that
# answers 200 or FAKE_DOWN makes every call fail. It writes the body to --output.
cat >"$work/bin/curl" <<'EOF'
#!/bin/sh
out=
url=
while [ "$#" -gt 0 ]; do
  case $1 in
    --output) out=$2; shift 2 ;;
    --write-out | --max-time) shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
[ -n "${FAKE_DOWN:-}" ] && { echo "curl: (6) Could not resolve host" >&2; exit 6; }
case $url in
  */"${FAKE_OPEN:-none}"/*) printf 'Workflow could not be started' >"$out"; printf 200 ;;
  *) printf 'RBAC: access denied' >"$out"; printf 403 ;;
esac
EOF
chmod +x "$work/bin/curl"

failures=0

# expect <label> <want: pass or fail> <url> [VAR=value ...]
expect() {
  label=$1
  want=$2
  url=$3
  shift 3
  status=0
  env PATH="$work/bin:$PATH" "$@" sh "$check" "$url" >"$work/out" 2>&1 || status=$?
  got=pass
  [ "$status" -ne 0 ] && got=fail
  if [ "$got" = "$want" ]; then
    echo "ok    $label: $got"
  else
    echo "FAIL  $label: wanted $want, got $got"
    sed 's/^/      /' "$work/out"
    failures=$((failures + 1))
  fi
}

expect "n8n internal" pass ""
expect "every path refused" pass "https://n8n.example.test/"
expect "a webhook answers" fail "https://n8n.example.test" FAKE_OPEN=webhook
expect "a waiting webhook answers" fail "https://n8n.example.test" FAKE_OPEN=webhook-waiting
expect "an MCP trigger answers" fail "https://n8n.example.test" FAKE_OPEN=mcp-test
expect "n8n can't be reached at all" fail "https://n8n.example.test" FAKE_DOWN=1

if [ "$failures" = 0 ]; then
  echo "check-n8n-paths-closed.sh: all cases behaved as expected"
else
  echo "check-n8n-paths-closed.sh: $failures case(s) failed"
  exit 1
fi
