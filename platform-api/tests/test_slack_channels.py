"""The Slack channels the platform's Slack key can post in, which a drafted workflow's channel
question offers and a channel typed in the chat or in n8n must be one of (ADR 0051, section 5)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from platform_api.orchestration.slack_channels import ChannelList, SlackChannels
from platform_api.settings import N8nKey

pytestmark = pytest.mark.anyio

KEY = N8nKey("slackApi", {"accessToken": "xoxb-test-not-a-secret"}, "https://slack.test/api")
PAGES = {
    "": {
        "ok": True,
        "channels": [
            {"name": "support", "is_member": True},
            {"name": "random", "is_member": False},
            {"name": "unsaid"},
        ],
        "response_metadata": {"next_cursor": "two"},
    },
    "two": {
        "ok": True,
        "channels": [{"name": "eng-housekeeping", "is_member": True}],
        "response_metadata": {"next_cursor": ""},
    },
}
MISSING_SCOPE = {"ok": False, "error": "missing_scope", "needed": "groups:read"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 17, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Slack:
    """Slack's conversations.list, which can be down, or refuse private channels to a key
    without groups:read, as Slack does."""

    def __init__(self) -> None:
        self.asked: list[httpx.Request] = []
        self.down = False
        self.private_refused = False

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.down:
            raise httpx.ConnectError("down", request=request)
        if self.private_refused and "private_channel" in request.url.params.get("types", ""):
            return httpx.Response(200, json=MISSING_SCOPE)
        return httpx.Response(200, json=PAGES[request.url.params.get("cursor", "")])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.answer))


async def test_it_lists_every_page_of_channels_the_key_is_a_member_of():
    slack = Slack()
    channels = SlackChannels(KEY, slack.client())

    assert await channels.visible() == ["#eng-housekeeping", "#support"]
    assert slack.asked[0].url.path == "/api/conversations.list"
    assert slack.asked[0].headers["Authorization"] == "Bearer xoxb-test-not-a-secret"
    assert slack.asked[0].url.params["types"] == "public_channel,private_channel"


async def test_it_asks_slack_again_only_after_a_minute():
    slack, clock = Slack(), Clock()
    channels = SlackChannels(KEY, slack.client(), clock=clock)
    await channels.visible()
    await channels.visible()
    assert len(slack.asked) == 2

    clock.now += timedelta(minutes=2)
    await channels.visible()
    assert len(slack.asked) == 4


async def test_no_key_or_no_answer_ever_offers_no_channel():
    assert await SlackChannels(None).visible() == []
    slack = Slack()
    slack.down = True
    assert await SlackChannels(KEY, slack.client()).visible() == []


async def test_while_slack_doesn_t_answer_it_asks_once_a_window_and_keeps_the_last_list():
    slack, clock = Slack(), Clock()
    channels = SlackChannels(KEY, slack.client(), clock=clock)
    assert await channels.listed() == ChannelList(
        ["#eng-housekeeping", "#support"], clock.now, False
    )
    listed_at = clock.now

    slack.down = True
    clock.now += timedelta(minutes=2)
    for _ in range(3):
        assert await channels.listed() == ChannelList(
            ["#eng-housekeeping", "#support"], listed_at, True
        )
    asked = len(slack.asked)
    assert asked == 3, "one failed try in the window, not one for each card read"

    clock.now += timedelta(seconds=40)
    await channels.listed()
    assert len(slack.asked) == asked + 1, "asked again once the window is over"


async def test_a_key_without_groups_read_lists_the_public_channels():
    slack = Slack()
    slack.private_refused = True
    clock = Clock()
    channels = SlackChannels(KEY, slack.client(), clock=clock)

    assert await channels.visible() == ["#eng-housekeeping", "#support"]
    clock.now += timedelta(minutes=2)
    before = len(slack.asked)
    await channels.visible()
    assert [r.url.params["types"] for r in slack.asked[before:]] == ["public_channel"] * 2, (
        "it remembers the key can't list private channels"
    )
