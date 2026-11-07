"""The card a new team request puts in the team's Teams channel (ADR 0038).

It is a nudge. It names who asked and what kind of request it is, and has one button that opens
the app. It does not hold the person's words, because a note may hold something that should
stay in the app, and nothing can be answered in Teams. The channel is the one the approval card
uses, or TEAMS_REQUESTS_WEBHOOK_URL when that is set.
"""

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from platform_api.orchestration.teams import (
    OPEN_IN,
    AdaptiveCard,
    OpenUrl,
    TextBlock,
    TextRun,
    _plain,  # pyright: ignore[reportPrivateUsage]
    _runs,  # pyright: ignore[reportPrivateUsage]
    webhook_message,
)

logger = logging.getLogger(__name__)

type RequestKind = Literal["ask_the_team", "support"]
type TeamsPost = Literal["posted", "no_channel", "failed"]

FALLBACK = "A new request for the team is waiting in AI Workflow Builder."


@dataclass(frozen=True)
class RequestNotice:
    kind: RequestKind
    asked_by_name: str
    open_url: str


def request_card(notice: RequestNotice) -> AdaptiveCard:
    if notice.kind == "support":
        title, what = "Platform problem reported", " reported a problem with the platform."
    else:
        title, what = "New request for the team", " asked the team for something."
    return AdaptiveCard(
        fallbackText=FALLBACK,
        body=[
            TextBlock(text=title, weight="bolder"),
            _runs(
                _plain(notice.asked_by_name, weight="bolder"),
                TextRun(text=what),
            ),
            TextBlock(text="Open the request to read it. Nothing can be answered in Teams."),
        ],
        actions=[OpenUrl(title=OPEN_IN, url=notice.open_url)],
    )


class TeamsRequestChannel:
    """Posts new-request cards to a Teams Workflows webhook. With no address it posts nothing and
    says so. The address carries its own signature, so no log line or error holds it."""

    def __init__(self, url: str | None, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._client = client or (httpx.AsyncClient(timeout=10.0) if url else None)

    async def post(self, notice: RequestNotice) -> TeamsPost:
        if self._url is None or self._client is None:
            return "no_channel"
        try:
            response = await self._client.post(
                self._url, json=webhook_message(request_card(notice))
            )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            logger.warning("A team request card was not posted (%s)", type(error).__name__)
            return "failed"
        if not response.is_success:
            logger.warning(
                "A team request card was not posted (Teams answered %s)", response.status_code
            )
            return "failed"
        return "posted"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


__all__ = ["RequestKind", "RequestNotice", "TeamsPost", "TeamsRequestChannel", "request_card"]
