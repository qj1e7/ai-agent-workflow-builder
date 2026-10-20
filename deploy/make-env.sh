#!/bin/sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
target="$here/.env"

force=0
case "${1-}" in
  "") ;;
  --force) force=1 ;;
  *) echo "usage: make-env.sh [--force]" >&2; exit 2 ;;
esac

if [ -e "$target" ] && [ "$force" -ne 1 ]; then
  echo "$target exists. Not overwriting. Pass --force to replace it (this also needs 'docker compose down -v')." >&2
  exit 1
fi

secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

tmp=$(mktemp "$here/.env.XXXXXX")
trap 'rm -f "$tmp"' EXIT
umask 077
cat > "$tmp" <<ENV
POSTGRES_PASSWORD=$(secret)
N8N_DB_PASSWORD=$(secret)
WAB_OWNER_PASSWORD=$(secret)
WAB_BUILDER_PASSWORD=$(secret)
WAB_ORCHESTRATION_PASSWORD=$(secret)
WAB_MONITORING_PASSWORD=$(secret)
N8N_ENCRYPTION_KEY=$(secret)
N8N_OWNER_EMAIL=owner@example.com
N8N_OWNER_PASSWORD=Aa1$(secret | head -c 20)
STEP_KEY=$(secret)
AGENT_API_KEY=$(secret)
CALLBACK_SIGNING_KEY=$(secret)
GITHUB_TOKEN=
GITHUB_API_BASE=https://api.github.com
PUBLIC_BASE_URL=http://localhost:8080
PLATFORM_API_HOST_PORT=8000
N8N_HOST_PORT=5678
ENV
chmod 600 "$tmp"
mv "$tmp" "$target"
trap - EXIT
echo "wrote $target"
