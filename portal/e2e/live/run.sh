#!/bin/sh
# Runs the live browser specs in the runner image (pinned Playwright, locked dependencies), inside the Portal container's network namespace.
# The page is then at http://localhost:8080, a secure context, and compose names such as mock-github still resolve.
# The same container also reaches the Portal as http://portal:8080, a plain HTTP origin, which 04-plain-http-origin uses.
# Needs only Docker.
# usage: run.sh <portal-container> [playwright arguments]
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: run.sh <portal-container> [playwright arguments]" >&2
  exit 2
fi
portal_container=$1
shift

portal_dir=$(cd "$(dirname "$0")/../.." && pwd)

runner=$("$portal_dir/e2e/runner-image.sh")

out="$portal_dir/e2e/out/live"
rm -rf "$out"
mkdir -p "$out"

docker run --rm --network "container:$portal_container" --ipc=host \
  -e CI="${CI:-}" -e BASE_URL=http://localhost:8080 \
  -e MOCK_GITHUB_URL="${MOCK_GITHUB_URL:-http://mock-github:8200}" \
  -e PLAIN_HTTP_URL="${PLAIN_HTTP_URL:-http://portal:8080}" \
  -v "$portal_dir/e2e:/work/e2e:ro" -v "$out:/work/e2e/out/live" \
  -w /work "$runner" \
  npx playwright test -c e2e/live/playwright.config.ts "$@"
