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
WAB_NODE_KEY=$(secret)
WAB_START_SECRET=$(secret)
AGENT_API_KEY=$(secret)
CALLBACK_SIGNING_KEY=$(secret)
SETTINGS_ENCRYPTION_KEY=$(secret)
FIRST_OPERATOR=
FIRST_APPROVERS=
GITHUB_TOKEN=
TEAMS_TELL_WEBHOOK_URL=
TELL_EMAIL_TO=
CONFLUENCE_BASE_URL=
CONFLUENCE_EMAIL=
CONFLUENCE_API_TOKEN=
CONFLUENCE_PAGES=
GITHUB_API_BASE=https://api.github.com
AGENT_SUMMARY_MODEL=
AGENT_MODEL_BASE_URL=
AGENT_MODEL_API_KEY=
AGENT_MODEL_PRIVATE_HOSTS=
PORTAL_HOST_PORT=8080
PLATFORM_API_HOST_PORT=8000
N8N_HOST_PORT=5678
ENV
chmod 600 "$tmp"

# An existing .env keeps every value it has, because N8N_ENCRYPTION_KEY must not change while the
# volumes exist. It only gains the keys added since it was written.
if [ -e "$target" ] && [ "$force" -ne 1 ]; then
  added=""
  while IFS= read -r line; do
    name=${line%%=*}
    if ! grep -q "^$name=" "$target"; then
      printf '%s\n' "$line" >>"$target"
      added="$added $name"
    fi
  done <"$tmp"
  if [ -n "$added" ]; then
    echo "added to $target:$added"
  else
    echo "$target has every key. To replace it, run 'docker compose down -v', then make-env.sh --force."
  fi
  exit 0
fi

mv "$tmp" "$target"
trap - EXIT
echo "wrote $target"
