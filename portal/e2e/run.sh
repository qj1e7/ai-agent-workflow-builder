#!/bin/sh
# Builds the Portal image, serves it in demo mode and runs the Playwright specs in the same network namespace, so the page is at http://localhost:8080, a secure context.
# Needs only Docker. The specs run in the runner image, which holds the pinned Playwright and the locked dependencies.
set -eu

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

image="${PORTAL_E2E_IMAGE:-portal:e2e}"

runner=$("$portal_dir/e2e/runner-image.sh")
docker build -f "$portal_dir/Dockerfile" -t "$image" "$repo_dir"
docker network create "$network" >/dev/null
docker run -d --name "$server" --network "$network" --network-alias portal \
  -e PORTAL_MODE=demo "$image" >/dev/null

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
  -v "$portal_dir/e2e:/work/e2e:ro" -v "$portal_dir/playwright.config.ts:/work/playwright.config.ts:ro" \
  -v "$portal_dir/e2e/out:/work/e2e/out" \
  -w /work "$runner" \
  sh -c 'if [ "$#" -eq 0 ]; then rm -rf e2e/out/shots e2e/out/axe e2e/out/video; fi; exec npx playwright test "$@"' sh "$@"
