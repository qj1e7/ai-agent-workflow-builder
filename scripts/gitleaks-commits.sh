#!/usr/bin/env bash
# Runs gitleaks over every commit in <base>..<head> of the repo in the current folder.
# scripts/scan_commits.py is CI's main check of the commits, and this is the second one. gitleaks'
# default rules miss some keys, such as an Atlassian API token, and it doesn't read the lines a
# merge adds itself, which scan_commits.py does.
# gitleaks v8.21.2 logs "failed to scan Git repository" and still exits 0 when it can't read the
# commits. So this fails then, and when it scanned no commit of a range that has some.
#   GITLEAKS_IMAGE=<image> scripts/gitleaks-commits.sh <base> <head>
# Needs Docker. The image and its digest are in .github/workflows/ci.yml.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: GITLEAKS_IMAGE=<image> scripts/gitleaks-commits.sh <base> <head>" >&2
  exit 2
fi
range="$1..$2"
if ! expected=$(git rev-list --count "$range" --); then
  echo "Couldn't read the commits $range." >&2
  exit 2
fi
log=$(mktemp)
trap 'rm -f "$log"' EXIT

status=0
docker run --rm --volume "$PWD:/repo:ro" \
  --env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory --env GIT_CONFIG_VALUE_0=/repo \
  "$GITLEAKS_IMAGE" detect --source /repo --log-opts="$range" --redact --verbose \
  2>&1 | tee "$log" || status=$?

if grep -q "failed to scan Git repository" "$log"; then
  echo "gitleaks couldn't read the commits $range, so it scanned none of them." >&2
  exit 1
fi
scanned=$(grep -oE '[0-9]+ commits? scanned' "$log" | grep -oE '^[0-9]+' | tail -n 1 || true)
if [ "$expected" -gt 0 ] && [ "${scanned:-0}" -eq 0 ]; then
  echo "gitleaks scanned no commit of $range, which has $expected." >&2
  exit 1
fi
exit "$status"
