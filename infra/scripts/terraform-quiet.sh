#!/bin/sh
# Runs one terraform command with its full output in a file, and prints only the summary line,
# such as "Plan: 3 to add, 0 to change, 0 to destroy." On a failure it prints Terraform's errors
# instead. The repository's workflow logs are public, and the full output names every resource
# and its ID. The file stays on the runner.
# Usage: terraform-quiet.sh <output-file> <terraform-command> [arguments...]
set -eu

out=$1
command=$2
shift 2

if terraform "$command" -no-color "$@" >"$out" 2>&1; then
  grep -E '^(Plan: |No changes\.|Apply complete!)' "$out" || true
else
  status=$?
  echo "terraform $command failed:" >&2
  sed -n '/^Error: /,$p' "$out" >&2
  exit "$status"
fi
