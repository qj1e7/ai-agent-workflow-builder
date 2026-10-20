#!/bin/sh
# Runs the live browser specs in the pinned Playwright image, inside the Portal container's network namespace.
# The page is then at http://localhost:8080, a secure context, and compose names such as mock-github still resolve.
# usage: run.sh <portal-container> [playwright arguments]
set -eu

PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.55.1-noble@sha256:2f29369043d81d6d69a815ceb80760f55e85f5020371ad06a4d996f18503ad1c

if [ "$#" -lt 1 ]; then
  echo "usage: run.sh <portal-container> [playwright arguments]" >&2
  exit 2
fi
portal_container=$1
shift

portal_dir=$(cd "$(dirname "$0")/../.." && pwd)

if [ ! -d "$portal_dir/node_modules/@playwright/test" ]; then
  echo "Installing the Portal dependencies (npm ci)." >&2
  (cd "$portal_dir" && npm ci --ignore-scripts)
fi

out="$portal_dir/e2e/out/live"
rm -rf "$out"
mkdir -p "$out"

docker run --rm --network "container:$portal_container" --ipc=host \
  -e CI="${CI:-}" -e BASE_URL=http://localhost:8080 \
  -e MOCK_GITHUB_URL="${MOCK_GITHUB_URL:-http://mock-github:8200}" \
  -v "$portal_dir:/work:ro" -v "$out:/work/e2e/out/live" \
  -w /work "$PLAYWRIGHT_IMAGE" \
  npx playwright test -c e2e/live/playwright.config.ts "$@"
