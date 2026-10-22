#!/bin/sh
# Builds the image the browser suites run in and prints its name on the last line of stdout.
# Docker reuses the install layer until package-lock.json changes, so a second run costs a second.
# The install lives in the image, so a host portal/node_modules (built for another OS) is never used.
set -eu

portal_dir=$(cd "$(dirname "$0")/.." && pwd)
image="${E2E_RUNNER_IMAGE:-portal-e2e-runner:local}"

docker build -q -f "$portal_dir/e2e/Dockerfile.runner" -t "$image" "$portal_dir" >/dev/null
echo "$image"
