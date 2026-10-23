#!/bin/sh
# Offline checks for infra/. Every tool runs in a Docker image pinned by digest, and nothing
# talks to Azure: init skips the backend and no step has credentials.
# Usage: infra/scripts/check.sh [output-dir]
set -eu

TERRAFORM_IMAGE=hashicorp/terraform:1.16.5@sha256:c7926feace05d0f7e73542842bf3945924e955a1f782cf000ccbb8d18fa42d77
TOFU_IMAGE=ghcr.io/opentofu/opentofu:1.12.7@sha256:3f068ee39a7233d39d9179fb2116a052a6fecdc350dfe2fccebb45b17ef1aa86
TFLINT_IMAGE=ghcr.io/terraform-linters/tflint:v0.64.0@sha256:1c595f42d794c32c45a6ea8b58655fd66433d4ca3b1bc631c574a48d120bd19f
CHECKOV_IMAGE=bridgecrew/checkov:3.3.20@sha256:6d20ebbcde58b2dce6e3151a6771fefa4d468281fe442475455623f5799b9f53

infra=$(cd "$(dirname "$0")/.." && pwd)
cache=${INFRA_CHECK_CACHE:-$infra/.cache}
out=${1:-}
mkdir -p "$cache/terraform" "$cache/tofu" "$cache/tflint"
[ -n "$out" ] && mkdir -p "$out"

run() {
  name=$1
  shift
  echo "== $name"
  if [ -n "$out" ]; then
    status=0
    "$@" >"$out/$name.txt" 2>&1 || status=$?
    cat "$out/$name.txt"
    return "$status"
  fi
  "$@"
}

tool() {
  docker run --rm --user "$(id -u):$(id -g)" --env HOME=/tmp --tmpfs /tmp:exec "$@"
}

run terraform-fmt tool --volume "$infra:/infra" --workdir /infra \
  "$TERRAFORM_IMAGE" fmt -check -recursive -diff -no-color

for env_dir in "$infra"/envs/*/; do
  env=$(basename "$env_dir")
  run "terraform-validate-$env" tool \
    --volume "$infra:/infra" --volume "$cache/terraform:/cache" --env TF_PLUGIN_CACHE_DIR=/cache \
    --workdir "/infra/envs/$env" --entrypoint /bin/sh "$TERRAFORM_IMAGE" -c \
    'terraform init -backend=false -input=false -lockfile=readonly -no-color >/dev/null && terraform validate -no-color'

  run "terraform-variables-$env" tool --volume "$infra:/infra:ro" --entrypoint /bin/sh "$TERRAFORM_IMAGE" \
    /infra/scripts/check-variables.sh "/infra/envs/$env/variables.tf"

  # OpenTofu gets a scratch copy without the lock file, because the lock file names Terraform's registry.
  run "tofu-validate-$env" tool \
    --volume "$infra:/src:ro" --volume "$cache/tofu:/cache" --env TF_PLUGIN_CACHE_DIR=/cache \
    --tmpfs /work:exec --entrypoint /bin/sh "$TOFU_IMAGE" -c \
    "cp -R /src/. /work && rm -rf /work/.cache /work/envs/$env/.terraform /work/envs/$env/.terraform.lock.hcl && cd /work/envs/$env && tofu version && tofu init -backend=false -input=false -no-color >/dev/null && tofu validate -no-color"
done

run tflint tool \
  --volume "$infra:/infra" --volume "$cache/tflint:/plugins" --env TFLINT_PLUGIN_DIR=/plugins \
  ${GITHUB_TOKEN:+--env GITHUB_TOKEN} --workdir /infra --entrypoint /bin/sh "$TFLINT_IMAGE" -c \
  'tflint --version && tflint --init --config=/infra/.tflint.hcl && tflint --recursive --config=/infra/.tflint.hcl --format=compact --no-color'

run checkov tool --volume "$infra:/infra:ro" --workdir /infra "$CHECKOV_IMAGE" \
  --directory /infra --framework terraform --skip-path .terraform --skip-path .cache \
  --compact --quiet --download-external-modules false
