#!/usr/bin/env bash
# Writes contracts/n8n/catalogue.json, the catalogue of n8n's blocks that the workflow drafter
# reads (ADR 0051, section 8), from what the image serves, stamped with the n8n pin in
# infra/public-images.json. It also runs section 2's pin check: it reads each block's code and the
# blocks' shared helpers in the image, and fails on code that reaches n8n's environment, its disk,
# code it runs or another workflow when ADR 0051 doesn't name it for that, and on a package the
# blocks read in that nobody has looked at (platform_api.n8n_code_check). And it reads n8n's
# defaults and the runner image's own config, which spike P9's verdicts rest on, and fails when a
# new pin changes them (platform_api.n8n_defaults_check, ADR 0051 build step 12).
#   scripts/n8n-catalogue.sh          runs pack smoke, which starts the image once and calls this
#                                     script back with what n8n served, and writes the file
#   scripts/n8n-catalogue.sh --check  the same, but fails when the committed file differs
#   scripts/n8n-catalogue.sh [--check] <served nodes.json> <image>
#                                     what pack smoke calls
# Needs Docker, jq and uv. PACK_SMOKE_IMAGE names an image already built, as for pack smoke.
set -euo pipefail
cd "$(dirname "$0")/.."

mode=write
if [ "${1:-}" = "--check" ]; then
  mode=check
  shift
fi
case $# in
  0) PACK_SMOKE_CATALOGUE=$mode exec scripts/pack-smoke.sh ;;
  2) ;;
  *) echo "usage: scripts/n8n-catalogue.sh [--check] [<served nodes.json> <image>]" >&2; exit 2 ;;
esac

served="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
image=$2
file=contracts/n8n/catalogue.json
pin=$(jq -r '.n8n | "\(.repository):\(.tag)@\(.digest)"' infra/public-images.json)
work=$(mktemp -d)
box="n8n-catalogue-$$"
trap 'docker rm -f "$box" "$box-runners" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

version=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image")
if [ "$version" != "$(jq -r .n8n.tag infra/public-images.json)" ]; then
  echo "$image is n8n $version, not the pin $pin." >&2
  exit 1
fi

# The code of n8n's blocks, as the image holds it, for the pin check. Nothing starts.
docker create --name "$box" "$image" >/dev/null
modules=/usr/local/lib/node_modules/n8n/node_modules
for package in n8n-nodes-base @n8n/n8n-nodes-langchain; do
  mkdir -p "$work/sources/$package/dist"
  for part in known nodes utils; do
    docker cp --quiet "$box:$modules/$package/dist/$part" "$work/sources/$package/dist/$part"
  done
done
# The defaults and the runner's own config that spike P9's verdicts rest on, and the pins, for
# platform_api.n8n_defaults_check. Nothing starts here either.
mkdir -p "$work/sources/config" "$work/sources/runners"
docker cp --quiet "$box:$modules/@n8n/config/dist/configs" "$work/sources/config/configs"
runners=$(jq -r '."n8n-runners" | "\(.repository):\(.tag)@\(.digest)"' infra/public-images.json)
docker create --name "$box-runners" "$runners" >/dev/null
docker cp --quiet "$box-runners:/etc/n8n-task-runners.json" "$work/sources/runners/n8n-task-runners.json"
cp infra/public-images.json "$work/sources/public-images.json"

status=0
(cd platform-api && uv run --locked --quiet python -m platform_api.n8n_catalogue \
  "$served" "$pin" "$work/sources") >"$work/catalogue.json" || status=1
if [ ! -s "$work/catalogue.json" ]; then
  exit 1
fi
blocks=$(jq '.blocks | length' "$work/catalogue.json")
size=$(wc -c <"$work/catalogue.json" | tr -d ' ')

if [ "$mode" = write ]; then
  cp "$work/catalogue.json" "$file"
  echo "Wrote $file: $blocks blocks in $size bytes, from $pin."
elif cmp -s "$work/catalogue.json" "$file"; then
  echo "$file holds the $blocks blocks $pin serves."
else
  # One block a line, so the lines that differ name the blocks.
  diff "$file" "$work/catalogue.json" | grep -E '^[<>]' | cut -c1-100 | head -n 20 >&2 || true
  echo "$file is not what $pin serves. Run scripts/n8n-catalogue.sh and commit the file." >&2
  status=1
fi
exit "$status"
