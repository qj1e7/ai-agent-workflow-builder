"""The approval request as an Adaptive Card, and the two places it can go (ADR 0036).

One function builds the card. The practice copy stores it, and the Workflows webhook posts it to a
real Teams channel, so both show the same card. The card has one button, "Open in AI Workflow
Builder", and the Approver decides on our approval page under their own sign-in (ADR 0009).

Text we did not write, such as the agents' summary, the workflow's name and people's names, goes
only in a TextRun, which Teams shows as it is: a TextRun has no markdown. Its web addresses and
markdown links are also broken, so none can become a link. Our own fixed words go in a
TextBlock. The card holds only what the notice holds, so no token or key can reach a channel.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

import httpx
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from platform_api.db import Database, json
from platform_api.orchestration.dispatch import (
    ApprovalNotice,
    ApprovalOutcome,
    AskedStep,
    DispatchFailure,
    MessageRef,
)
from platform_api.orchestration.runs import sentence
from platform_api.orchestration.write_actions import listed, one_line
from platform_api.shared import ApprovalId, RunId, new_id
from platform_api.wire import WireModel

CARD_VERSION = "1.4"
"""Teams renders up to 1.6 for a bot, and the Workflows webhook is known to render 1.4. The card
uses nothing newer than 1.2."""
OPEN_IN = "Open in AI Workflow Builder"
FALLBACK = "An approval request is waiting in AI Workflow Builder."
TEAMS_MESSAGE_LIMIT = 28 * 1024
"""Teams refuses a webhook message over 28 KB."""
LINES_SHOWN = 10
LINE_LIMIT = 300
SUMMARY_LIMIT = 300
OUTCOME_ID = "outcome"

type Weight = Literal["default", "bolder"]
type Color = Literal["default", "good", "attention"]


class CardPart(WireModel):
    """A part of a card. A property left unset is left out, as Teams expects, wherever the card
    is written: to Teams, to the practice copy's API and to the contract fixtures."""

    # No return annotation: one would replace the part's JSON schema with a plain object.
    @model_serializer(mode="wrap")
    def _leave_out_unset(self, handler: SerializerFunctionWrapHandler):
        return {key: value for key, value in handler(self).items() if value is not None}


class TextRun(CardPart):
    """Text shown as it is. Teams applies no markdown to a TextRun."""

    type: Literal["TextRun"] = "TextRun"
    text: str
    weight: Weight | None = None
    color: Color | None = None


class RichTextBlock(CardPart):
    type: Literal["RichTextBlock"] = "RichTextBlock"
    id: str | None = None
    inlines: list[TextRun]


class TextBlock(CardPart):
    """Our own fixed words only: Teams reads a TextBlock's text as markdown."""

    type: Literal["TextBlock"] = "TextBlock"
    id: str | None = None
    text: str
    wrap: bool = True
    weight: Weight | None = None


type CardElement = Annotated[RichTextBlock | TextBlock, Field(discriminator="type")]


class OpenUrl(CardPart):
    type: Literal["Action.OpenUrl"] = "Action.OpenUrl"
    title: str
    url: str


class AdaptiveCard(CardPart):
    """The subset of the Adaptive Card schema our cards use, and the Portal draws."""

    type: Literal["AdaptiveCard"] = "AdaptiveCard"
    version: str = CARD_VERSION
    fallbackText: str = FALLBACK
    body: list[CardElement]
    actions: list[OpenUrl]

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _runs(*runs: TextRun) -> RichTextBlock:
    return RichTextBlock(inlines=list(runs))


_IGNORABLE_MARKS = frozenset("\u034f\u115f\u1160\u17b4\u17b5\u3164\uffa0")
"""Characters shown as nothing that are not format characters (Unicode category Cf)."""
_TOKEN = r"[^\s<>()\[\]]*"
_AFTER_SCHEME = re.compile(r"://(" + _TOKEN + ")")
_WWW_HOST = re.compile(r"(?i)(?<![/.])(www)\.(?=[^\W_])(" + _TOKEN + ")")


def _visible(text: str) -> str:
    """text without the characters shown as nothing: every format character (Cf), such as a
    zero-width space or a direction mark, plus a few others, and variation selectors."""
    return "".join(
        c
        for c in text
        if unicodedata.category(c) != "Cf"
        and c not in _IGNORABLE_MARKS
        and not ("\ufe00" <= c <= "\ufe0f" or "\U000e0100" <= c <= "\U000e01ef")
    )


def inert(text: str) -> str:
    """text with nothing a reader could follow (ADR 0036). Characters shown as nothing go first,
    so none can split a marker. Then:

    - every "://" becomes "[:]//", and the dots of the address after it are broken,
    - "www." that starts a host becomes "www[.]", with the host's dots broken. It starts a host
      unless a "/" or "." comes before it, as in a path or a longer name, and a letter or digit
      comes after it. A word character before it does not stop it, so "_www.evil.example" is
      broken too,
    - every "mailto:" loses its colon, and a markdown link loses its "](".

    Any case counts. Teams says every card text field takes basic markdown, and nothing says
    whether it links a bare address in a TextRun, so text we did not write never holds a link."""
    text = _visible(text)
    text = _AFTER_SCHEME.sub(lambda m: "[:]//" + m.group(1).replace(".", "[.]"), text)
    text = _WWW_HOST.sub(lambda m: m.group(1) + "[.]" + m.group(2).replace(".", "[.]"), text)
    text = re.sub(r"(?i)mailto:", lambda m: m.group(0)[:6] + "[:]", text)
    return text.replace("](", "] (")


def _plain(
    text: str, limit: int = LINE_LIMIT, weight: Weight | None = None, color: Color | None = None
) -> TextRun:
    """Text we did not write: on one line, cut to length, and with no working link."""
    return TextRun(text=one_line(inert(text), limit), weight=weight, color=color)


def _either(names: tuple[str, ...]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]


def _who(step: AskedStep) -> str:
    return _either(step.who) if step.who else "Any Approver"


def _changes(count: int) -> str:
    return "1 change" if count == 1 else f"{count} changes"


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _what(notice: ApprovalNotice) -> list[CardElement]:
    lines = notice.lines or tuple(_first_upper(a) for a in notice.actions)
    shown: list[CardElement] = [_runs(_plain(f"• {line}")) for line in lines[:LINES_SHOWN]]
    more = len(lines) - LINES_SHOWN
    if more > 0:
        shown.append(_runs(TextRun(text=f"And {more} more. Open the request to see them all.")))
    return [
        _runs(
            _plain(notice.use_case_name, weight="bolder"),
            TextRun(
                text=f" wants to make {_changes(len(lines))}. "
                "Nothing is written until an Approver says yes."
            ),
        ),
        *shown,
    ]


def _found(notice: ApprovalNotice) -> list[CardElement]:
    said = one_line(notice.summary, SUMMARY_LIMIT)
    if not said:
        return []
    return [
        TextBlock(text="What the agents found", weight="bolder"),
        _runs(_plain(notice.summary, SUMMARY_LIMIT)),
    ]


def _deciders(notice: ApprovalNotice) -> list[CardElement]:
    steps = notice.steps
    if not steps:
        return [
            TextBlock(text="Who can decide", weight="bolder"),
            _runs(TextRun(text="Any Approver who is not part of this run")),
        ]
    if len(steps) == 1:
        who: list[CardElement] = [
            TextBlock(text="Who can decide", weight="bolder"),
            _runs(_plain(_who(steps[0]))),
        ]
    else:
        who = [
            TextBlock(text="Who can decide, one after the other", weight="bolder"),
            *(_runs(_plain(f"{n}. {s.label}: {_who(s)}")) for n, s in enumerate(steps, 1)),
        ]
    if notice.not_deciding:
        who.append(
            _runs(
                _plain(
                    _first_upper(
                        f"{listed(notice.not_deciding)} can’t decide, "
                        "because this run is their own work."
                    )
                )
            )
        )
    return who


def approval_card(notice: ApprovalNotice) -> AdaptiveCard:
    return AdaptiveCard(
        body=[*_what(notice), *_found(notice), *_deciders(notice)],
        actions=[OpenUrl(title=OPEN_IN, url=notice.open_url)],
    )


def _decided(outcome: ApprovalOutcome) -> str:
    verb = "Approved" if outcome.verdict == "approved" else "Declined"
    return f"{verb} by {listed(outcome.by)}"


def _outcome_block(outcome: ApprovalOutcome) -> RichTextBlock:
    color: Color = "good" if outcome.verdict == "approved" else "attention"
    return RichTextBlock(
        id=OUTCOME_ID,
        inlines=[_plain(_decided(outcome), weight="bolder", color=color)],
    )


def with_outcome(card: AdaptiveCard, outcome: ApprovalOutcome) -> AdaptiveCard:
    """The card as a bot would edit it once the request is decided: the outcome on top."""
    rest = [element for element in card.body if element.id != OUTCOME_ID]
    return card.model_copy(update={"body": [_outcome_block(outcome), *rest]})


def outcome_card(outcome: ApprovalOutcome) -> AdaptiveCard:
    """A second card with the outcome, for a channel that cannot edit the card it posted."""
    after = "." if outcome.verdict == "approved" else ". Nothing was written."
    return AdaptiveCard(
        body=[
            _runs(
                _plain(outcome.use_case_name, weight="bolder"),
                _plain(f": {_decided(outcome).lower()}{after}"),
            )
        ],
        actions=[OpenUrl(title=OPEN_IN, url=outcome.open_url)],
    )


def webhook_message(card: AdaptiveCard) -> dict[str, Any]:
    """The body a Teams Workflows webhook takes: one message with the card as its attachment."""
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card.as_json(),
            }
        ],
    }


CHECK_NOTICE = ApprovalNotice(
    run_id=RunId("run_check"),
    approval_id=ApprovalId("apr_check"),
    use_case_name="**Card check** [open](https://example.com)",
    actions=("create a Jira ticket",),
    link="/approvals/apr_check",
    open_url="https://example.com/approvals/apr_check",
    summary=(
        "**Approve now** [here](https://example.com) or https://example.com or www.example.com "
        "or mailto:someone@example.com. <at>Bob</at> _ok_ # Heading - item 1. item"
    ),
    lines=(
        "Create Jira ticket in MOCK: **bold** [link](https://example.com) www.example.com",
        # inert() leaves these as written. The check shows whether Teams links them.
        "A bare name: example.com/approve, and a longer one: sub.example.com",
        "A bare email: someone@example.com",
        "A look-alike name: аррӏе.com, and with a scheme: https://аррӏе.com",
    ),
    steps=(AskedStep("Approver"),),
    not_deciding=("**Alice** [x](https://example.com)",),
)
"""A card full of text that must show as typed, with no bold, no heading and no link but the
button. It also holds what inert() leaves alone: a bare name, a longer name, a bare email and a
look-alike name in Cyrillic letters. infra/README.md says to post it to a test channel once,
before TEAMS_WEBHOOK_URL is set, and look at whether Teams links any of them."""


def check_card() -> AdaptiveCard:
    return approval_card(CHECK_NOTICE)


def _agents_said(summary: str) -> str:
    """The agents' summary, labelled, on one line and cut to length.

    It is model text, so it goes last: nothing the platform says can follow it and be mistaken
    for it, and it cannot pose as the action line above it.
    """
    flat = one_line(summary, SUMMARY_LIMIT)
    return f" The agents said: {sentence(flat)}" if flat else ""


def practice_text(notice: ApprovalNotice) -> str:
    """The message in plain words, kept beside the card in the practice copy."""
    return (
        f"A run of the {notice.use_case_name} needs an Approver. "
        f"It would {listed(notice.actions)}. "
        f"Open the approval page to decide.{_agents_said(notice.summary)}"
    )


@dataclass(frozen=True)
class TeamsMessage:
    id: str
    ts: datetime
    channel: str
    text: str
    link: str
    run_id: RunId
    approval_id: ApprovalId
    card: AdaptiveCard | None
    """None only for a message posted before cards (migration 0009)."""


class TeamsStub:
    """The practice copy of Teams. It keeps the card a real channel gets, and edits it to show
    the outcome, as a bot will."""

    def __init__(self, db: Database, channel: str) -> None:
        self._db = db
        self._channel = channel

    @property
    def name(self) -> str:
        return self._channel

    @property
    def adapter(self) -> str:
        return "practice"

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        card = approval_card(notice).as_json()
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.teams_stub_messages "
                "(id, ts, channel, text, link, run_id, approval_id, card) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (approval_id) DO NOTHING",
                (
                    new_id("tm"),
                    uow.now,
                    self._channel,
                    practice_text(notice),
                    notice.link,
                    notice.run_id,
                    notice.approval_id,
                    json(card),
                ),
            )
            row = await (
                await uow.conn.execute(
                    "SELECT id, channel FROM orchestration.teams_stub_messages "
                    "WHERE approval_id = %s",
                    (notice.approval_id,),
                )
            ).fetchone()
        assert row is not None
        return MessageRef(channel=row["channel"], id=row["id"], adapter=self.adapter)

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT card FROM orchestration.teams_stub_messages WHERE id = %s FOR UPDATE",
                    (ref.id,),
                )
            ).fetchone()
            if row is None:
                raise DispatchFailure(f"the practice Teams copy has no message {ref.id}")
            # A message posted before cards keeps no card, only its outcome.
            card = (
                None
                if row["card"] is None
                else json(with_outcome(AdaptiveCard.model_validate(row["card"]), outcome).as_json())
            )
            await uow.conn.execute(
                "UPDATE orchestration.teams_stub_messages SET card = %s, outcome = %s "
                "WHERE id = %s",
                (card, json({"verdict": outcome.verdict, "by": list(outcome.by)}), ref.id),
            )

    async def messages(self) -> list[TeamsMessage]:
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT id, ts, channel, text, link, run_id, approval_id, card "
                    "FROM orchestration.teams_stub_messages ORDER BY ts, id"
                )
            ).fetchall()
        return [
            TeamsMessage(
                id=row["id"],
                ts=row["ts"],
                channel=row["channel"],
                text=row["text"],
                link=row["link"],
                run_id=RunId(row["run_id"]),
                approval_id=ApprovalId(row["approval_id"]),
                card=None if row["card"] is None else AdaptiveCard.model_validate(row["card"]),
            )
            for row in rows
        ]


class TeamsWorkflowsWebhook:
    """A real Teams channel, through a Workflows (Power Automate) webhook (ADR 0036).

    The webhook's address carries its own signature, so it is a secret: it is read from Key
    Vault, and no error message, log line or card ever holds it. A Workflows webhook cannot edit
    a card it posted, so the outcome goes to the channel as a second, short card.
    """

    def __init__(self, url: str, channel: str, client: httpx.AsyncClient | None = None) -> None:
        # httpx logs each request's full address at INFO, and this address is a secret. The
        # wiring quiets httpx when it builds this adapter (approval_channel in wiring.py).
        self._url = url
        self._channel = channel
        self._client = client or httpx.AsyncClient(timeout=10.0)

    @property
    def name(self) -> str:
        return self._channel

    @property
    def adapter(self) -> str:
        return "teams_workflows"

    @property
    def closed(self) -> bool:
        return self._client.is_closed

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        await self._post(approval_card(notice))
        return MessageRef(channel=self._channel, id=notice.approval_id, adapter=self.adapter)

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        await self._post(outcome_card(outcome))

    async def _post(self, card: AdaptiveCard) -> None:
        try:
            response = await self._client.post(self._url, json=webhook_message(card))
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # Both name the address in their message, so neither goes any further.
            raise DispatchFailure(f"Teams did not answer ({type(error).__name__})") from None
        if not response.is_success:
            raise DispatchFailure(f"Teams answered {response.status_code}")

    async def close(self) -> None:
        await self._client.aclose()
