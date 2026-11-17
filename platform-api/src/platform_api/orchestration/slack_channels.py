"""The Slack channels the platform's Slack key can post in (ADR 0051, section 5). A drafted
workflow's channel question offers them, and a channel typed in the chat or in n8n counts only
when it is one of them, since a channel is never guessed.

The platform's key reads the list with its channels:read scope, which ADR 0045's check of what
the key may do allows. It asks for private channels too, which need groups:read, and when Slack
answers that the key lacks that scope it lists public channels only from then on. Only channels
Slack says the key is a member of are listed, as only those take its posts.

A list is kept for a minute, so a card that refreshes doesn't ask Slack each time. When Slack
doesn't answer, that is kept for half a minute, so a card read waits on Slack at most once in that
time, and the last list Slack gave is served, marked as possibly out of date. The key's secret goes
only in the request's header, never in a log."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

import httpx

from platform_api.settings import N8nKey

log = logging.getLogger(__name__)

KEPT_FOR: Final = timedelta(minutes=1)
FAILED_FOR: Final = timedelta(seconds=30)
WAITS: Final = 5.0
"""The longest a card read waits on Slack, in seconds."""
PAGES: Final = 5
"""At most this many pages of 200 channels."""
WITH_PRIVATE: Final = "public_channel,private_channel"
PUBLIC_ONLY: Final = "public_channel"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ChannelList:
    channels: list[str]
    """Each channel as "#name", sorted."""
    as_of: datetime | None
    """When Slack gave this list. None when it never has."""
    stale: bool
    """Slack didn't answer the last time it was asked, so this is the last list it gave."""


class SlackListFailed(Exception):
    """Slack answered, but not with a list."""


class SlackChannels:
    def __init__(
        self,
        key: N8nKey | None,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._key = key
        self._http = http
        self._clock = clock
        self._good: tuple[datetime, list[str]] | None = None
        self._failed_at: datetime | None = None
        self._types = WITH_PRIVATE

    async def visible(self) -> list[str]:
        """Each channel the key can post in, as "#name"; none at all when there is no key or
        Slack has never answered."""
        return (await self.listed()).channels

    async def listed(self) -> ChannelList:
        if self._key is None:
            return ChannelList([], None, False)
        now = self._clock()
        if self._good is not None and now - self._good[0] < KEPT_FOR:
            return ChannelList(list(self._good[1]), self._good[0], False)
        if self._failed_at is not None and now - self._failed_at < FAILED_FOR:
            return self._last(stale=True)
        try:
            channels = await self._list(self._key)
        except (httpx.HTTPError, SlackListFailed, ValueError) as error:
            log.warning("Slack did not list its channels: %s", type(error).__name__)
            self._failed_at = now
            return self._last(stale=True)
        self._good, self._failed_at = (now, channels), None
        return ChannelList(list(channels), now, False)

    def _last(self, stale: bool) -> ChannelList:
        if self._good is None:
            return ChannelList([], None, stale)
        return ChannelList(list(self._good[1]), self._good[0], stale)

    async def _list(self, key: N8nKey) -> list[str]:
        http = self._http or httpx.AsyncClient(timeout=WAITS)
        try:
            try:
                return await self._pages(http, key, self._types)
            except SlackListFailed as refused:
                if self._types == WITH_PRIVATE and str(refused) == "missing_scope":
                    self._types = PUBLIC_ONLY
                    return await self._pages(http, key, PUBLIC_ONLY)
                raise
        finally:
            if self._http is None:
                await http.aclose()

    async def _pages(self, http: httpx.AsyncClient, key: N8nKey, types: str) -> list[str]:
        names: set[str] = set()
        cursor = ""
        for _ in range(PAGES):
            response = await http.get(
                f"{key.asks}/conversations.list",
                params={
                    "types": types,
                    "exclude_archived": "true",
                    "limit": "200",
                    **({"cursor": cursor} if cursor else {}),
                },
                headers={"Authorization": f"Bearer {key.data['accessToken']}"},
            )
            response.raise_for_status()
            answer = cast(dict[str, Any], response.json())
            if answer.get("ok") is not True:
                raise SlackListFailed(str(answer.get("error", "not_ok")))
            for channel in cast(list[dict[str, Any]], answer.get("channels") or []):
                if channel.get("is_member") is True and channel.get("name"):
                    names.add(f"#{channel['name']}")
            meta = cast(dict[str, Any], answer.get("response_metadata") or {})
            cursor = str(meta.get("next_cursor") or "")
            if not cursor:
                break
        return sorted(names)
