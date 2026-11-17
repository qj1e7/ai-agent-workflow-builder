"""The Slack channels the platform's Slack key can post in, which a drafted workflow's channel
question offers and a channel typed in the chat or in n8n must be one of (ADR 0051, section 5)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from platform_api.orchestration.slack_channels import SlackChannels
from platform_api.settings import N8nKey

pytestmark = pytest.mark.anyio

KEY = N8nKey("slackApi", {"accessToken": "xoxb-test-not-a-secret"}, "https://slack.test/api")
PAGES = {
    "": {
        "ok": True,
        "channels": [
            {"name": "support", "is_member": True},
            {"name": "random", "is_member": False},
        ],
        "response_metadata": {"next_cursor": "two"},
    },
    "two": {
        "ok": True,
        "channels": [{"name": "eng-housekeeping", "is_member": True}],
        "response_metadata": {"next_cursor": ""},
    },
}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 17, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def slack(asked: list[httpx.Request], down: bool = False) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if down:
            return httpx.Response(503)
        return httpx.Response(200, json=PAGES[request.url.params.get("cursor", "")])

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def test_it_lists_every_page_of_channels_the_key_can_post_in():
    asked: list[httpx.Request] = []
    channels = SlackChannels(KEY, slack(asked))

    assert await channels.visible() == ["#eng-housekeeping", "#support"]
    assert asked[0].url.path == "/api/conversations.list"
    assert asked[0].headers["Authorization"] == "Bearer xoxb-test-not-a-secret"
    assert asked[0].url.params["types"] == "public_channel,private_channel"


async def test_it_asks_slack_again_only_after_a_minute():
    asked: list[httpx.Request] = []
    clock = Clock()
    channels = SlackChannels(KEY, slack(asked), clock=clock)
    await channels.visible()
    await channels.visible()
    assert len(asked) == 2

    clock.now += timedelta(minutes=2)
    await channels.visible()
    assert len(asked) == 4


async def test_no_key_or_no_answer_offers_no_channel():
    assert await SlackChannels(None).visible() == []
    asked: list[httpx.Request] = []
    assert await SlackChannels(KEY, slack(asked, down=True)).visible() == []
