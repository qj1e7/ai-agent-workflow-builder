"""Tell: a notice of what a run read, sent with no yes under the Tell rule (ADR 0026,
ENGINE-PLAN 2.3.12 and D19).

A Tell goes out only when all three parts of the rule hold:

- Its recipients are fixed. The block picks the team's channel, the email list or both, never an
  address. The one Tell flow (TEAMS_TELL_WEBHOOK_URL) holds where each goes.
- Its content is composed here from the run's own stored reads and agent results, never from text
  a block sends. It lists no write, so it never claims a change.
- The Portal says what it does: the registry's "Posts in Teams and emails", planned until E13.

The flow takes one body, the Teams message with the card plus the email's subject and HTML, as
the team's cert reminder already posts it. Text we did not write goes through teams.inert, so
none of it is a link, and the email escapes it as well.
"""

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import httpx

from platform_api.db import Database, json
from platform_api.orchestration.teams import (
    LINES_SHOWN,
    SUMMARY_LIMIT,
    AdaptiveCard,
    CardElement,
    TextBlock,
    TextRun,
    _plain,  # pyright: ignore[reportPrivateUsage]
    _runs,  # pyright: ignore[reportPrivateUsage]
    inert,
    webhook_message,
)
from platform_api.orchestration.write_actions import one_line
from platform_api.shared import RunId, new_id

type TellWhere = Literal["channel", "email", "both"]
type TellWhat = Literal["result", "only_when_something_to_report"]
type TellStatus = Literal[
    "sent", "sending", "not_confirmed", "would_have_sent", "nothing_to_report"
]

FALLBACK = "A notice from AI Workflow Builder."
SIGN_OFF = "A notice from AI Workflow Builder. It asks for nothing."
SUBJECT_LIMIT = 200
LABEL_LIMIT = 200
THE_LIST = "the team's list"


@dataclass(frozen=True)
class Reach:
    card: bool
    email: bool


REACH: Mapping[TellWhere, Reach] = {
    "channel": Reach(card=True, email=False),
    "email": Reach(card=False, email=True),
    "both": Reach(card=True, email=True),
}


@dataclass(frozen=True)
class BlockResult:
    """What one Read or Agent block of the run answered, as our API stored it."""

    block: str
    kind: Literal["read", "agent"]
    items: tuple[Mapping[str, Any], ...]
    cut_off: bool = False


@dataclass(frozen=True)
class NoticePart:
    """One block's share of the notice. Every field is text we did not write."""

    block: str
    lead: str
    lines: tuple[str, ...]


def _label(item: Mapping[str, Any]) -> str:
    named = [str(item[key]) for key in ("id", "title", "name") if item.get(key)]
    return " ".join(dict.fromkeys(named)) or str(item.get("kind") or "An item")


def _findings(item: Mapping[str, Any]) -> tuple[str, ...]:
    """The details of an agent's findings, as the agent block stored them."""
    found = cast(list[Mapping[str, Any]], item.get("findings") or [])
    return tuple(str(f["detail"]) for f in found if f.get("detail"))


def notice_parts(results: Sequence[BlockResult]) -> tuple[NoticePart, ...]:
    parts: list[NoticePart] = []
    for result in results:
        if result.kind == "agent":
            for item in result.items:
                parts.append(
                    NoticePart(result.block, str(item.get("summary") or ""), _findings(item))
                )
        else:
            count = len(result.items)
            lead = f"{count} read" + (", where the read stops" if result.cut_off else "")
            parts.append(NoticePart(result.block, lead, tuple(_label(i) for i in result.items)))
    return tuple(parts)


def something_to_report(results: Sequence[BlockResult]) -> bool:
    """An agent's findings, or what was read when no agent ran."""
    agents = [r for r in results if r.kind == "agent"]
    if agents:
        return any(_findings(item) for r in agents for item in r.items)
    return any(r.items for r in results)


@dataclass(frozen=True)
class Email:
    subject: str
    html: str


@dataclass(frozen=True)
class TellMessage:
    card: AdaptiveCard | None
    email: Email | None

    def body(self) -> dict[str, Any]:
        """What the Tell flow takes: a Teams message, with the email beside it."""
        body: dict[str, Any] = (
            webhook_message(self.card)
            if self.card is not None
            else {"type": "message", "attachments": []}
        )
        if self.email is not None:
            body["emailSubject"] = self.email.subject
            body["emailHtml"] = self.email.html
        return body


def _card(use_case_name: str, parts: Sequence[NoticePart]) -> AdaptiveCard:
    body: list[CardElement] = [
        _runs(_plain(use_case_name, weight="bolder"), TextRun(text=": what this run found."))
    ]
    for part in parts:
        body.append(_runs(_plain(part.block, weight="bolder"), _plain(f": {part.lead}")))
        body.extend(_runs(_plain(f"• {line}", LABEL_LIMIT)) for line in part.lines[:LINES_SHOWN])
        more = len(part.lines) - LINES_SHOWN
        if more > 0:
            body.append(_runs(TextRun(text=f"And {more} more.")))
    body.append(TextBlock(text=SIGN_OFF))
    return AdaptiveCard(fallbackText=FALLBACK, body=body, actions=[])


def _escaped(text: str, limit: int = SUMMARY_LIMIT) -> str:
    return html.escape(one_line(inert(text), limit))


def _email(use_case_name: str, parts: Sequence[NoticePart]) -> Email:
    subject = one_line(inert(f"{use_case_name}: what this run found"), SUBJECT_LIMIT)
    sections: list[str] = [f"<h2>{_escaped(use_case_name)}</h2>", "<p>What this run found.</p>"]
    for part in parts:
        sections.append(f"<p><b>{_escaped(part.block)}</b>: {_escaped(part.lead)}</p>")
        if part.lines:
            items = "".join(f"<li>{_escaped(line, LABEL_LIMIT)}</li>" for line in part.lines)
            sections.append(f"<ul>{items}</ul>")
    sections.append(f"<p>{SIGN_OFF}</p>")
    return Email(subject, "".join(sections))


def compose(use_case_name: str, results: Sequence[BlockResult], reach: Reach) -> TellMessage:
    """The notice, from the run's stored results only."""
    parts = notice_parts(results)
    return TellMessage(
        _card(use_case_name, parts) if reach.card else None,
        _email(use_case_name, parts) if reach.email else None,
    )


def _where(reach: Reach, channel: str) -> tuple[str, str]:
    """How the notice's places read after "posted to" and "emailed"."""
    return (channel if reach.card else "", THE_LIST if reach.email else "")


def sent_line(reach: Reach, channel: str) -> str:
    posted, emailed = _where(reach, channel)
    said = [f"Posted to {posted}" if posted else "", f"emailed {emailed}" if emailed else ""]
    line = " and ".join(s for s in said if s)
    return f"{line[0].upper()}{line[1:]}."


def would_have_line(reach: Reach, channel: str) -> str:
    posted, emailed = _where(reach, channel)
    said = [f"posted to {posted}" if posted else "", f"emailed {emailed}" if emailed else ""]
    return f"Would have {' and '.join(s for s in said if s)}. Nothing was sent in a test run."


SENDING_LINE = "Sending, not confirmed. It is not sent again."
NOTHING_TO_REPORT = "Nothing to report, so nothing was sent."


def not_confirmed_line(why: str) -> str:
    return f"Not confirmed: {why}. It is not sent again."


@dataclass(frozen=True)
class Told:
    """What a Tell block did, kept as its one answer."""

    status: TellStatus
    line: str


class NotConfirmed(Exception):
    """The notice may or may not have gone. Its message names no address."""


class TellOutlet(Protocol):
    @property
    def channel(self) -> str:
        """The team's channel, by the name people know it."""
        ...

    async def send(self, run_id: RunId, block: str, message: TellMessage) -> None: ...


class TellPractice:
    """The practice copy of the Tell flow. It keeps each notice as the flow would get it."""

    def __init__(self, db: Database, channel: str) -> None:
        self._db = db
        self._channel = channel

    @property
    def channel(self) -> str:
        return self._channel

    async def send(self, run_id: RunId, block: str, message: TellMessage) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.tell_practice_messages (id, ts, run_id, block, body) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (run_id, block) DO NOTHING",
                (new_id("tell"), uow.now, run_id, block, json(message.body())),
            )

    async def messages(self) -> list[dict[str, Any]]:
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT run_id, block, body FROM orchestration.tell_practice_messages "
                    "ORDER BY ts, id"
                )
            ).fetchall()
        return [dict(row) for row in rows]


class TellFlow:
    """The team's Tell flow in Power Automate, which posts the card and sends the email (D1).

    Its address carries its own signature, so it comes from Key Vault, and no error or log line
    holds it.
    """

    def __init__(self, url: str, channel: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._channel = channel
        self._client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)

    @property
    def channel(self) -> str:
        return self._channel

    async def send(self, run_id: RunId, block: str, message: TellMessage) -> None:
        try:
            response = await self._client.post(self._url, json=message.body())
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise NotConfirmed(f"the Tell flow did not answer ({type(error).__name__})") from None
        if not response.is_success:
            raise NotConfirmed(f"the Tell flow answered {response.status_code}")

    async def close(self) -> None:
        await self._client.aclose()
