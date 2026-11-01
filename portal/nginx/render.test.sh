#!/bin/sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
image='nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10'
prefix="${RENDER_CONTAINER_PREFIX:-portal-render}"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

ok() { echo "ok    $1"; }
bad() {
  echo "FAIL  $1"
  failures=$((failures + 1))
}

render() {
  name=$1
  shift
  docker run --rm --pull never --name "$prefix-$name" \
    -v "$here/default.conf.template:/etc/nginx/templates/default.conf.template:ro" \
    -v "$here/16-portal-auth.envsh:/docker-entrypoint.d/16-portal-auth.envsh:ro" \
    -e API_UPSTREAM=http://platform-api:8000 -e NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    "$@" "$image" \
    sh -c '/docker-entrypoint.sh nginx -t >/tmp/entrypoint.log 2>&1 || { cat /tmp/entrypoint.log; exit 1; }; cat /etc/nginx/conf.d/default.conf'
}

served_lines() { grep -E 'Content-Security-Policy|Strict-Transport-Security|max-age|"mode"' "$1"; }

# Starts nginx with the real nginx.conf and prints each response's Strict-Transport-Security header.
# Container Apps ends TLS and forwards plain http with X-Forwarded-Proto: https. Local dev sends no such header.
hsts_headers() {
  docker run --rm --pull never --name "$prefix-hsts" \
    -v "$here/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$here/default.conf.template:/etc/nginx/templates/default.conf.template:ro" \
    -v "$here/16-portal-auth.envsh:/docker-entrypoint.d/16-portal-auth.envsh:ro" \
    -e API_UPSTREAM=http://platform-api:8000 -e NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 -e PORTAL_MODE=live \
    "$image" \
    sh -c '/docker-entrypoint.sh nginx >/tmp/entrypoint.log 2>&1 || { cat /tmp/entrypoint.log; exit 1; }
      for path in / /config.json /healthz /assets/missing.js /api/health; do
        for proto in none http https; do
          if [ "$proto" = none ]; then set --; else set -- -H "X-Forwarded-Proto: $proto"; fi
          hsts=$(curl -s -o /dev/null -D - "$@" "http://127.0.0.1:8080$path" | tr -d "\r" | sed -n "s/^[Ss]trict-[Tt]ransport-[Ss]ecurity: //p")
          echo "hsts $path $proto ${hsts:-(none)}"
        done
      done'
}

expect_hsts() {
  if ! hsts_headers >"$work/hsts.out" 2>&1; then
    bad "nginx serves for the HSTS check:" && cat "$work/hsts.out"
    return
  fi
  if grep '^hsts ' "$work/hsts.out" | diff - "$here/testdata/hsts.golden" >"$work/hsts.diff"; then
    ok "HSTS is sent only when X-Forwarded-Proto is https, on every location"
  else
    bad "HSTS headers differ from the golden lines:" && cat "$work/hsts.diff"
  fi
}

expect_golden() {
  name=$1
  if ! render "$name" -e "PORTAL_MODE=$name" >"$work/$name.conf"; then
    bad "$name renders"
    return
  fi
  if served_lines "$work/$name.conf" | diff - "$here/testdata/$name.golden" >"$work/$name.diff"; then
    ok "$name serves the golden /config.json body and CSP"
  else
    bad "$name differs from the golden lines:" && cat "$work/$name.diff"
  fi
}

expect_oidc() {
  name=$1
  origin=$2
  auth=$3
  shift 3
  if ! render "$name" -e PORTAL_MODE=live "$@" >"$work/$name.conf"; then
    bad "$name renders"
    return
  fi
  diff "$work/live.conf" "$work/$name.conf" | grep '^[<>]' >"$work/$name.changes" || true
  changed_old=$(grep -c '^<' "$work/$name.changes")
  changed_new=$(grep -c '^>' "$work/$name.changes")
  csp="  add_header Content-Security-Policy \"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' $origin; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'\" always;"
  config="    return 200 '{\"mode\":\"live\"$auth}';"
  if [ "$changed_old" = 2 ] && [ "$changed_new" = 2 ] && grep -Fxq "> $csp" "$work/$name.changes" && grep -Fxq "> $config" "$work/$name.changes"; then
    ok "$name changes only connect-src and the /config.json body"
  else
    bad "$name changed these lines against dev:" && cat "$work/$name.changes"
  fi
}

expect_refused() {
  name=$1
  variable=$2
  shift 2
  if out=$(render "$name" -e PORTAL_MODE=live "$@" 2>&1); then
    bad "$name started a container"
  elif printf '%s' "$out" | grep -q "portal: .*$variable"; then
    ok "$name is refused, naming $variable"
  else
    bad "$name was refused without naming $variable:" && printf '%s\n' "$out"
  fi
}

ENTRA='https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0'
MOCK='http://mock-oidc:8080/default'
CLIENT='66666666-7777-8888-9999-000000000000'
SCOPE='openid profile offline_access api://platform-api/.default'

expect_golden live
expect_hsts

expect_oidc entra 'https://login.microsoftonline.com' \
  ",\"auth\":{\"authority\":\"$ENTRA\",\"client_id\":\"$CLIENT\",\"scope\":\"$SCOPE\"}" \
  -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_oidc mock 'http://mock-oidc:8080' \
  ",\"auth\":{\"authority\":\"$MOCK\",\"client_id\":\"portal\",\"scope\":\"openid profile offline_access platform-api\"}" \
  -e "OIDC_AUTHORITY=$MOCK" -e "OIDC_TEST_ONLY_HTTP_AUTHORITY=$MOCK" -e OIDC_CLIENT_ID=portal -e 'OIDC_SCOPE=openid profile offline_access platform-api'

JIRA='https://jira.example.test/browse/{key}'
expect_jira() {
  if ! render jira -e PORTAL_MODE=live -e "JIRA_BROWSE_URL=$JIRA" >"$work/jira.conf"; then
    bad "jira renders"
    return
  fi
  diff "$work/live.conf" "$work/jira.conf" | grep '^[<>]' >"$work/jira.changes" || true
  config="    return 200 '{\"mode\":\"live\",\"jira_browse_url\":\"$JIRA\"}';"
  if [ "$(grep -c '^[<>]' "$work/jira.changes")" = 2 ] && grep -Fxq "> $config" "$work/jira.changes"; then
    ok "jira changes only the /config.json body"
  else
    bad "jira changed these lines against dev:" && cat "$work/jira.changes"
  fi
}
expect_jira

expect_refused jira-no-key JIRA_BROWSE_URL -e 'JIRA_BROWSE_URL=https://jira.example.test/browse/'
expect_refused jira-ftp JIRA_BROWSE_URL -e 'JIRA_BROWSE_URL=ftp://jira.example.test/browse/{key}'
expect_refused jira-quote JIRA_BROWSE_URL -e 'JIRA_BROWSE_URL=https://jira.example.test/"/browse/{key}'
expect_refused jira-query JIRA_BROWSE_URL -e 'JIRA_BROWSE_URL=https://jira.example.test/browse/{key}?x=1'
expect_refused jira-newline JIRA_BROWSE_URL -e "JIRA_BROWSE_URL=https://jira.example.test/browse/{key}
\"}"
expect_refused only-authority OIDC_CLIENT_ID -e "OIDC_AUTHORITY=$ENTRA"
expect_refused only-client-id OIDC_AUTHORITY -e "OIDC_CLIENT_ID=$CLIENT"
expect_refused only-scope OIDC_AUTHORITY -e "OIDC_SCOPE=$SCOPE"
expect_refused no-scope OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT"
expect_refused demo-mode PORTAL_MODE -e PORTAL_MODE=demo
expect_refused demo-with-auth PORTAL_MODE -e PORTAL_MODE=demo -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused http-authority OIDC_AUTHORITY -e "OIDC_AUTHORITY=$MOCK" -e OIDC_CLIENT_ID=portal -e "OIDC_SCOPE=$SCOPE"
expect_refused http-allowance-mismatch OIDC_AUTHORITY -e "OIDC_AUTHORITY=$MOCK" -e 'OIDC_TEST_ONLY_HTTP_AUTHORITY=http://other:8080/default' -e OIDC_CLIENT_ID=portal -e "OIDC_SCOPE=$SCOPE"
expect_refused ftp-authority OIDC_AUTHORITY -e 'OIDC_AUTHORITY=ftp://login.example.test/v2.0' -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused authority-query OIDC_AUTHORITY -e "OIDC_AUTHORITY=$ENTRA?x=1" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused authority-fragment OIDC_AUTHORITY -e "OIDC_AUTHORITY=$ENTRA#x" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused authority-quote OIDC_AUTHORITY -e 'OIDC_AUTHORITY=https://login.example.test/"/v2.0' -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused client-id-space OIDC_CLIENT_ID -e "OIDC_AUTHORITY=$ENTRA" -e 'OIDC_CLIENT_ID=portal app' -e "OIDC_SCOPE=$SCOPE"
expect_refused client-id-quote OIDC_CLIENT_ID -e "OIDC_AUTHORITY=$ENTRA" -e 'OIDC_CLIENT_ID=portal"' -e "OIDC_SCOPE=$SCOPE"
expect_refused scope-without-openid OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e 'OIDC_SCOPE=profile offline_access'
expect_refused scope-openid-prefix-only OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e 'OIDC_SCOPE=openidx profile'
expect_refused scope-bad-char OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e 'OIDC_SCOPE=openid pro"file'
expect_refused scope-double-space OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e 'OIDC_SCOPE=openid  profile'
expect_refused authority-newline OIDC_AUTHORITY -e "OIDC_AUTHORITY=$ENTRA
\"; add_header X-Injected 1; #" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE"
expect_refused client-id-newline OIDC_CLIENT_ID -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT
'; return 200 'x" -e "OIDC_SCOPE=$SCOPE"
expect_refused scope-newline OIDC_SCOPE -e "OIDC_AUTHORITY=$ENTRA" -e "OIDC_CLIENT_ID=$CLIENT" -e "OIDC_SCOPE=$SCOPE
\"}"

if [ "$failures" = 0 ]; then
  echo "render.test.sh: all checks passed"
else
  echo "render.test.sh: $failures check(s) failed"
  exit 1
fi
