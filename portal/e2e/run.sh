#!/bin/sh
# Builds the Portal image, serves it in demo mode and runs the Playwright specs in the same network namespace, so the page is at http://localhost:8080, a secure context.
set -eu

PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.55.1-noble@sha256:2f29369043d81d6d69a815ceb80760f55e85f5020371ad06a4d996f18503ad1c

portal_dir=$(cd "$(dirname "$0")/.." && pwd)
repo_dir=$(dirname "$portal_dir")
suffix=$$
network=portal-e2e-$suffix
server=portal-e2e-server-$suffix

cleanup() {
  docker rm -f "$server" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker build -f "$portal_dir/Dockerfile" -t portal:e2e "$repo_dir"
docker network create "$network" >/dev/null
docker run -d --name "$server" --network "$network" --network-alias portal \
  -e PORTAL_MODE=demo portal:e2e >/dev/null

ready=
for _ in $(seq 1 30); do
  if docker exec "$server" wget -qO- http://127.0.0.1:8080/healthz >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
if [ -z "$ready" ]; then
  docker logs "$server" >&2
  echo "The Portal did not become healthy." >&2
  exit 1
fi

mkdir -p "$portal_dir/e2e/out"
# A full run starts from empty evidence folders, so nothing stale survives. A filtered run (arguments given) keeps the rest.
docker run --rm --network "container:$server" --ipc=host \
  -e CI="${CI:-}" -e E2E_STRICT="${E2E_STRICT:-}" -e BASE_URL=http://localhost:8080 \
  -v "$portal_dir:/work:ro" -v "$portal_dir/e2e/out:/work/e2e/out" \
  -w /work "$PLAYWRIGHT_IMAGE" \
  sh -c 'if [ "$#" -eq 0 ]; then rm -rf e2e/out/shots e2e/out/axe e2e/out/video; fi; exec npx playwright test "$@"' sh "$@"
