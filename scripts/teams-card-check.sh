#!/bin/sh
# The one-time check before real Teams (ADR 0036, infra/README.md). Posts a card full of hostile
# text to a TEST Teams channel through its Workflows webhook. In Teams, every text must show as
# typed, with no bold, no heading and no link except the button. Only then set TEAMS_WEBHOOK_URL.
# The address comes from the environment, because it carries the webhook's own signature.
# Usage: TEAMS_TEST_WEBHOOK_URL='<a test channel's Workflows webhook address>' scripts/teams-card-check.sh
set -eu

: "${TEAMS_TEST_WEBHOOK_URL:?Set TEAMS_TEST_WEBHOOK_URL to the Workflows webhook address of a test channel.}"
cd "$(dirname "$0")/../platform-api"

uv run --quiet python -c '
import json
from platform_api.orchestration.teams import check_card, webhook_message
print(json.dumps(webhook_message(check_card())))
' | curl --silent --show-error --fail --output /dev/null --write-out 'Teams answered %{http_code}\n' \
  --header 'Content-Type: application/json' --data-binary @- "$TEAMS_TEST_WEBHOOK_URL"
