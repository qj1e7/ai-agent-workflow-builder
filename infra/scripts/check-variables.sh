#!/bin/sh
# Checks the variable rules in a variables.tf for sign-in and the first people:
# good values pass, and plan refuses what platform-api, agent-runtime or the Portal would refuse. It plans a module that holds only that
# file, so it needs no provider and no credentials. check.sh runs it in the Terraform image.
# Usage: check-variables.sh <variables.tf>
set -eu

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$1" "$work/variables.tf"
cd "$work"
terraform version | head -1
terraform init -input=false -no-color >/dev/null

ISSUER='https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0'
AUDIENCE='66666666-7777-8888-9999-000000000000'
CLIENT='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
SCOPE="openid profile offline_access api://$AUDIENCE/access_as_user"
nl='
'
failures=0

# expect <accepted|refused> <variable> <label> [-var name=value ...]
# A later -var for the same name wins, so each case overrides only what it tests.
expect() {
  want=$1
  variable=$2
  label=$3
  shift 3
  if out=$(terraform plan -input=false -no-color -lock=false \
    -var subscription_id=00000000-0000-0000-0000-000000000000 -var image_tag=test \
    -var n8n_owner_email=owner@example.test -var "oidc_issuer=$ISSUER" \
    -var "oidc_audience=$AUDIENCE" -var "oidc_client_id=$CLIENT" -var "oidc_scope=$SCOPE" \
    "$@" 2>&1); then
    got=accepted
  else
    got=refused
  fi
  # A sensitive variable's error names its block, not its value.
  message=$(printf '%s\n' "$out" | awk '/ var\.|: variable "/{f=1; next} /^This was checked/{f=0} /^ *(├|│)/{next} f && NF {printf "%s ", $0}')
  if [ "$got" = "$want" ] && { [ "$got" = accepted ] || printf '%s' "$out" | grep -q -e "var\.$variable " -e ": variable \"$variable\" {"; }; then
    echo "ok    $got  $label${message:+: $message}"
  else
    echo "FAIL  $label: wanted $want for $variable, got $got"
    printf '%s\n' "$out"
    failures=$((failures + 1))
  fi
}

expect accepted - "Entra values, no keys URL, no GitHub token"
expect accepted - "a keys URL" -var oidc_jwks_url=https://login.microsoftonline.com/t/discovery/v2.0/keys
expect accepted - "a GitHub token" -var github_token=example-token
expect accepted - "the first people, the Operator also an Approver" \
  -var first_operator=op@example.test -var first_approvers=op@example.test,ap@example.test
expect accepted - "the first people with spaces and capitals" \
  -var 'first_operator= Op@Example.test ' -var 'first_approvers=Op@Example.test , ap@example.test'

expect refused oidc_issuer "issuer over http" -var oidc_issuer=http://mock-oidc:8080/default
expect refused oidc_issuer "issuer with no host" -var oidc_issuer=https:///tenant/v2.0
expect refused oidc_issuer "issuer with a query" -var "oidc_issuer=$ISSUER?x=1"
expect refused oidc_issuer "issuer with a fragment" -var "oidc_issuer=$ISSUER#x"
expect refused oidc_issuer "issuer with a quote" -var 'oidc_issuer=https://login.example.test/"/v2.0'
expect refused oidc_issuer "issuer on two lines" -var "oidc_issuer=$ISSUER$nl\"; add_header X-Injected 1; #"
expect refused oidc_issuer "issuer not set" -var oidc_issuer=

expect refused oidc_jwks_url "keys URL over http" -var oidc_jwks_url=http://idp.test/keys
expect refused oidc_jwks_url "keys URL with a query" -var 'oidc_jwks_url=https://idp.test/keys?x=1'

expect refused oidc_audience "audience not set" -var oidc_audience=
expect refused oidc_audience "audience as the api:// URI" -var "oidc_audience=api://$AUDIENCE"

expect refused oidc_client_id "client ID not set" -var oidc_client_id=
expect refused oidc_client_id "client ID with a space" -var 'oidc_client_id=portal app'
expect refused oidc_client_id "client ID with a quote" -var 'oidc_client_id=portal"'
expect refused oidc_client_id "client ID on two lines" -var "oidc_client_id=$CLIENT$nl'; return 200 'x"

expect refused oidc_scope "scope not set" -var oidc_scope=
expect refused oidc_scope "scope without openid" -var 'oidc_scope=profile offline_access'
expect refused oidc_scope "scope with openidx only" -var 'oidc_scope=openidx profile'
expect refused oidc_scope "scope with a quote" -var 'oidc_scope=openid pro"file'
expect refused oidc_scope "scope with two spaces" -var 'oidc_scope=openid  profile'
expect refused oidc_scope "scope on two lines" -var "oidc_scope=$SCOPE$nl\"}"

expect refused first_approvers "an Operator and no Approvers" -var first_operator=op@example.test
expect refused first_approvers "Approvers and no Operator" -var first_approvers=a@example.test,b@example.test
expect refused first_approvers "one Approver" -var first_operator=op@example.test -var first_approvers=a@example.test
expect refused first_approvers "three Approvers" \
  -var first_operator=op@example.test -var first_approvers=a@example.test,b@example.test,c@example.test
expect refused first_approvers "the same Approver twice" \
  -var first_operator=op@example.test -var first_approvers=a@example.test,A@Example.test
expect refused first_approvers "an Approver that is not an email" \
  -var first_operator=op@example.test -var first_approvers=a@example.test,bob
expect refused first_operator "an Operator that is not an email" \
  -var first_operator=alice -var first_approvers=a@example.test,b@example.test

if [ "$failures" = 0 ]; then
  echo "check-variables.sh: all cases behaved as expected"
else
  echo "check-variables.sh: $failures case(s) failed"
  exit 1
fi
