"""The Slack channels the platform's Slack key can post in (ADR 0051, section 5). A drafted
workflow's channel question offers them, and a channel typed in the chat or in n8n counts only
when it is one of them, since a channel is never guessed.

The platform's key reads the list with its channels:read scope, which ADR 0045's check of what
the key may do allows. Only channels the key is a member of are listed, as only those take its
posts. The list is kept for a minute, so a card that refreshes doesn't ask Slack each time. The
key's secret goes only in the request's header, never in a log."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

import httpx

from platform_api.settings import N8nKey

log = logging.getLogger(__name__)

KEPT_FOR: Final = timedelta(minutes=1)
PAGES: Final = 5
"""At most this many pages of 200 channels."""


def _now() -> datetime:
    return datetime.now(UTC)


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
        self._kept: tuple[datetime, list[str]] | None = None

    async def visible(self) -> list[str]:
        """Each channel as "#name", sorted. None at all when there is no key or Slack doesn't
        answer."""
        if self._key is None:
            return []
        now = self._clock()
        if self._kept is not None and now - self._kept[0] < KEPT_FOR:
            return list(self._kept[1])
        try:
            listed = await self._list(self._key)
        except (httpx.HTTPError, ValueError) as error:
            log.warning("Slack did not list its channels: %s", type(error).__name__)
            return []
        self._kept = (now, listed)
        return list(listed)

    async def _list(self, key: N8nKey) -> list[str]:
        http = self._http or httpx.AsyncClient(timeout=10)
        try:
            names: set[str] = set()
            cursor = ""
            for _ in range(PAGES):
                response = await http.get(
                    f"{key.asks}/conversations.list",
                    params={
                        "types": "public_channel,private_channel",
                        "exclude_archived": "true",
                        "limit": "200",
                        **({"cursor": cursor} if cursor else {}),
                    },
                    headers={"Authorization": f"Bearer {key.data['accessToken']}"},
                )
                response.raise_for_status()
                answer = cast(dict[str, Any], response.json())
                if answer.get("ok") is not True:
                    raise ValueError(str(answer.get("error", "not ok")))
                for channel in cast(list[dict[str, Any]], answer.get("channels") or []):
                    if channel.get("is_member", True) and channel.get("name"):
                        names.add(f"#{channel['name']}")
                meta = cast(dict[str, Any], answer.get("response_metadata") or {})
                cursor = str(meta.get("next_cursor") or "")
                if not cursor:
                    break
            return sorted(names)
        finally:
            if self._http is None:
                await http.aclose()
