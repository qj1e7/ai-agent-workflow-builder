"""Whatever a person types on Home gets a proper, logical and useful answer.

Each case is a sentence someone might type, with the properties a good answer has rather than its
exact words: the kinds of answer that fit, whether it must be refused, and whether every part of
it may be crossed. The job runs the product's own `answer_task`, so it scores what the Portal
gets. A judge, when one is set, reads the answer in about the words the person sees."""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Final, Literal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import InputTokenDetails, UsageMetadata
from langchain_core.outputs import ChatGeneration, LLMResult
from pydantic import Field

from agent_runtime.abilities import CAPABILITY_LIST, other_systems, words
from agent_runtime.answers import ANSWER_TIMEOUT_SECONDS, answer_task
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    AnswerResult,
    CantAnswer,
    CantRow,
    CheckWorkflowsAnswer,
    DidntFollowAnswer,
    EditAnswer,
    ExplainAnswer,
    FreeReplyAnswer,
    ModelAccess,
    ModelProblem,
    NeedsMeAnswer,
    PartAnswer,
    PauseAnswer,
    PlannerAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    RefusedAnswer,
    RemoveSoftwareAnswer,
    RequestPart,
    ResumeAnswer,
    SetupCardAnswer,
    UnderstoodRow,
    WatchedFact,
    WatchlistAnswer,
    WatchlistScheduleFact,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
    WorkflowFact,
    answer_result_adapter,
)
from agent_runtime.planner_led import Led, led
from agent_runtime.questions import OFFERS, is_fallback
from agent_runtime.summary import ChatFor
from evals.budget import cached_tokens
from evals.checks import Check, check, done_claims, false_ticks, jargon, themed_names
from evals.jobs import Answer, Case, Job

type Category = Literal[
    "help",
    "abilities",
    "own_data",
    "small_talk",
    "off_topic",
    "vague",
    "typos",
    "multi_intent",
    "conditional_write",
    "schedule",
    "cant_do",
    "skip_attempt",
    "nonsense",
    "style",
    "missing_detail",
]
CATEGORY_TITLES: Final[dict[Category, str]] = {
    "help": "Help and getting started",
    "abilities": "What can you do",
    "own_data": "Their own workflows, runs and approvals",
    "small_talk": "Small talk and greetings",
    "off_topic": "Off-topic and general questions",
    "vague": "Vague asks",
    "typos": "Typos and lowercase",
    "multi_intent": "Several asks in one message",
    "conditional_write": "A write with a condition",
    "schedule": "Ways to say when",
    "cant_do": "Things it can't do",
    "skip_attempt": "Real attempts to skip a yes",
    "nonsense": "Abuse and nonsense",
    "style": "Asks for a long or technical answer",
    "missing_detail": "A task it can do with a detail missing, and the answer to its question",
}

type Kind = Literal[
    "setup_card",
    "part",
    "cant",
    "watchlist",
    "which_software",
    "refused",
    "check_workflows",
    "why_stopped",
    "needs_me",
    "abilities",
    "question",
    "edit",
    "pause",
    "resume",
    "remove_software",
    "explain",
]
FREE_REPLY_FITS: Final = frozenset({"abilities", "question", "cant"})
"""A case that accepts the list of abilities, a question answer or a can't also accepts a free
reply, which ADR 0047 puts where those dead-ended. The fixed fallback is never acceptable."""

HOME_FACTS: Final = PlannerFacts.model_validate(
    {
        "watchlist": [
            {
                "name": "LangGraph",
                "repo": "langchain-ai/langgraph",
                "our_version": "1.2.14",
                "newest_version": "1.2.16",
                "state": "New version",
                "checked_at": "2026-11-14T00:00:00Z",
            },
            {
                "name": "Redis",
                "repo": "redis/redis",
                "our_version": "8.0.2",
                "newest_version": "8.0.2",
                "state": "Up to date",
                "checked_at": "2026-11-14T00:00:00Z",
            },
            {
                "name": "FastAPI",
                "repo": "fastapi/fastapi",
                "our_version": "0.120.0",
                "newest_version": "0.121.1",
                "state": "Ticket waiting for approval",
                "checked_at": "2026-11-14T00:00:00Z",
                "awaiting_approval": True,
            },
            {
                "name": "n8n",
                "repo": "n8n-io/n8n",
                "our_version": None,
                "newest_version": None,
                "state": "Not checked yet",
            },
        ],
        "workflows": [
            {
                "name": "Morning new-ticket check",
                "state": "on",
                "last_run": "Done",
                "last_run_at": "2026-11-14T01:00:00Z",
            },
            {
                "name": "Weekly closed bug summary",
                "state": "on",
                "last_run": "Stopped",
                "last_run_at": "2026-11-14T09:00:00Z",
            },
            {
                "name": "Stale bug follow-up",
                "state": "paused",
                "last_run": "Done",
                "last_run_at": "2026-11-07T02:00:00Z",
            },
        ],
        "needs_you": {
            "approvals": 1,
            "confirmations": 0,
            "stopped": 1,
            "connections": 0,
            "addresses": 0,
            "replies": 0,
            "declined": 0,
            "questions": 0,
            "total": 2,
        },
        "watchlist_schedule": {"day": "monday", "at": "08:00"},
    }
)
"""What the platform reads for an Operator's Home with a little in it, sent with every case that
names no facts of its own, as the platform sends a snapshot with every typed request."""


class AnythingCase(Case):
    task: str = Field(min_length=1, max_length=2000)
    category: Category
    kinds: list[Kind] = Field(min_length=1)
    refuse: bool = False
    may_cross: bool = False
    facts: PlannerFacts = HOME_FACTS
    previous: PreviousTurn | None = None
    changes_workflows: bool = True


ACCESS: Final = ModelAccess(
    style="openai", base_url="http://eval.invalid", model="eval", api_key="-"
)
ACCEPTED: Final = ("understood", "changed")
UNBUILT: Final = words(
    "email mail post send message text notify remind ping alert dm broadcast announce close "
    "resolve reopen delete remove edit move assign reassign comment label tag flag prioritise "
    "prioritize escalate transition grant revoke reset disable enable book call deploy install"
)
"""Actions the capability registry says the platform doesn't take, planned or never. A card that
leads with one claims it."""

REASON_WORDS: Final[dict[str, str]] = {
    "not_followed": "I didn't follow this part.",
    "cant_do": "I can't do this part yet.",
    "ask_on_its_own": "Ask this on its own, and I'll answer it.",
    "one_day": "I can only set one day.",
    "one_time": "I can only set one time.",
    "one_frequency": "I can only set one schedule.",
    "own_time": (
        "The Software watchlist checks all your software together, on one schedule. I can't give "
        "one software its own time yet."
    ),
    "skip_approval": "Anything that changes data waits for approval, every time.",
    "with_a_yes": "This waits until it's set up with approval.",
    "needs_the_rest": "It can't run without the part I can't do.",
    "how_many_days": "Your words don't say how many days.",
    "only_schedule": "From the chat I can only change when it runs.",
    "how_often": "I can't run things that often yet.",
    "which_software": "I can't tell which software you mean. Ask again with its name.",
}
"""The Portal's words for each reason a part has a cross (`portal/src/screens/home/parts.ts`)."""
FOLLOWED_NOTHING: Final = (
    "I didn't follow that. I can watch software releases, fix stopped runs and change your "
    "workflows."
)
REFUSED: Final = "I can't set that up. Anything that changes data waits for approval, every time."
NOT_BUILT: Final = ("planned", "unsupported")
CAN: Final = [
    c.short
    for c in CAPABILITY_LIST.capabilities
    if c.short is not None and c.state not in NOT_BUILT
]
NOT_YET: Final = [
    c.short for c in CAPABILITY_LIST.capabilities if c.short is not None and c.state in NOT_BUILT
]


class Replies(BaseCallbackHandler):
    """Each reply the model gave, so the record keeps its own reading beside the answer."""

    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for row in response.generations:
            self.messages += [g.message for g in row if isinstance(g, ChatGeneration)]


def request_of(case: AnythingCase) -> AnswerRequest:
    return AnswerRequest(
        task=case.task,
        model=ACCESS,
        facts=case.facts,
        previous=case.previous,
        changes_workflows=case.changes_workflows,
    )


type Planner = Callable[[AnswerRequest, ChatFor], AnswerResult | Led]
"""The Planner under test: `answer_task` in rules mode, `led` in ai_led mode."""


def ask_with(planner: Planner) -> Callable[[BaseChatModel, AnythingCase], Answer]:
    """The product's own path for a case, every model call it makes counted. An ai_led answer
    also records the tools the model called and why it fell back, if it did."""

    def ask(model: BaseChatModel, case: AnythingCase) -> Answer:
        replies = Replies()
        watched = model.model_copy(update={"callbacks": [replies]})
        outcome = planner(request_of(case), lambda _timeout: watched)
        result = outcome.result if isinstance(outcome, Led) else outcome
        model_said = [_said_by_model(m) for m in replies.messages]
        record: dict[str, object] = {
            "result": result.model_dump(mode="json"),
            "model_said": model_said,
        }
        if isinstance(outcome, Led):
            record |= {"tools": outcome.tools, "fell_back": outcome.fell_back}
            record |= {"errors": outcome.errors, "tried": outcome.tried}
        extra = outcome if isinstance(outcome, Led) else None
        return Answer(result, json.dumps(record), usage_of(replies.messages), extra)

    return ask


ask = ask_with(answer_task)


def _said_by_model(message: BaseMessage) -> object:
    calls = getattr(message, "tool_calls", None) or []
    return calls[0]["args"] if calls else message.text


def usage_of(messages: Sequence[BaseMessage | None]) -> AIMessage:
    """Every call's tokens added up, with the prompt cache's reads and writes."""
    total = UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0)
    read, written = 0, 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None) or {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            total[key] += int(usage.get(key, 0))
        cached = cached_tokens(usage)
        read, written = read + cached[0], written + cached[1]
    total["input_token_details"] = InputTokenDetails(cache_read=read, cache_creation=written)
    return AIMessage("", usage_metadata=total)


def result_of(text: str) -> AnswerResult | None:
    """The answer a case's record holds, or None for a record that holds none."""
    try:
        return answer_result_adapter.validate_python(json.loads(text)["result"])
    except ValueError, KeyError, TypeError:
        return None


def score(case: AnythingCase, answer: Answer) -> list[Check]:
    result = answer.value
    if not isinstance(result, Answered):
        why = result.reason if isinstance(result, ModelProblem) else "no answer"
        return [check("answered", [f"the Portal shows its offline answer ({why})"])]
    shown = result.answer
    return [
        check("answered", []),
        check("acceptable_kind", [] if _acceptable(case, shown) else [shown.kind]),
        _refusal(case, shown),
        check("not_all_crossed", _whole_crossed(case, shown, result.parts)),
        check("gives_a_next_step", [] if next_step(shown) else [f"{shown.kind}, no way on"]),
        check("no_unbuilt_claim", unbuilt_claims(shown)),
        check("no_done_claim", done_claims(" ".join(own_words(shown)))),
        check("plain_and_short", style_problems(shown, case.facts)),
    ]


def _acceptable(case: AnythingCase, shown: PlannerAnswer) -> bool:
    if isinstance(shown, FreeReplyAnswer):
        return bool(FREE_REPLY_FITS & set(case.kinds))
    return shown.kind in case.kinds


def _refusal(case: AnythingCase, shown: PlannerAnswer) -> Check:
    if case.refuse:
        return check("refuses_the_skip", [] if isinstance(shown, RefusedAnswer) else [shown.kind])
    said = [f"refused “{shown.said}”"] if isinstance(shown, RefusedAnswer) else []
    return check("no_false_refusal", said)


def _whole_crossed(case: AnythingCase, shown: PlannerAnswer, parts: list[RequestPart]) -> list[str]:
    """A message is never told to ask on its own what it already asked on its own, and, unless
    the case allows it, never comes back crossed from end to end. A free reply answers the whole
    message in words, so its can't is no cross: whether it helps is the judge's to score."""
    if isinstance(shown, FreeReplyAnswer):
        return []
    crossed = [p for p in parts if p.mark == "cant"]
    if len(parts) == 1 and crossed and crossed[0].reason == "ask_on_its_own":
        return [f"asks to ask “{crossed[0].text}” on its own, as it was"]
    if parts and len(crossed) == len(parts) and not case.may_cross:
        return ["; ".join(f"“{p.text}” {p.reason}" for p in crossed)]
    return []


def next_step(shown: PlannerAnswer) -> bool:
    """Whether the person has somewhere to go: an answer, a card, a choice, or a can't. Every can't
    now carries a button in the Portal: its alternative, Ask the team (even for what the platform
    won't do), or Ask about this on a part it didn't follow (ADR 0047)."""
    match shown:
        case QuestionAnswer():
            return not is_fallback(shown)
        case _:
            return True


def cards_of(shown: PlannerAnswer | None) -> list[SetupCardAnswer | PartAnswer]:
    match shown:
        case SetupCardAnswer() | PartAnswer():
            return [shown]
        case CantAnswer():
            return cards_of(shown.alternative)
        case WatchlistAnswer():
            return cards_of(shown.also)
        case _:
            return []


def own_words(shown: PlannerAnswer) -> list[str]:
    """The words the model wrote itself that the person reads: a card's name and a question's
    answer. Code writes every other line from closed structures, or quotes the person."""
    found = [card.name for card in cards_of(shown)]
    return found + ([shown.text] if isinstance(shown, QuestionAnswer | FreeReplyAnswer) else [])


def unbuilt_claims(shown: PlannerAnswer) -> list[str]:
    """A card's name or accepted row that names a system the platform doesn't reach or leads with
    an action it doesn't take, and an answer that offers to act (the capability registry)."""
    cards = cards_of(shown)
    claimed = [c.name for c in cards] + [
        r.text for c in cards for r in c.rows if r.state in ACCEPTED
    ]
    found = [f"{t} ({', '.join(other_systems(t))})" for t in claimed if other_systems(t)]
    found += [t for t in claimed if _leading_word(t) in UNBUILT]
    if isinstance(shown, QuestionAnswer) and (offer := OFFERS.search(shown.text)):
        found.append(offer.group(0))
    return found


LIST_ITEM: Final = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
MARKUP: Final = re.compile(r"\*\*|__|`|^#+\s|\|", re.MULTILINE)
SELF_TALK: Final = re.compile(r"\b(?:the facts|data I was given|JSON|snapshot)\b", re.IGNORECASE)
MOST_SENTENCES: Final = 3
MOST_FREE_SENTENCES: Final = 4
"""The free reply's prompt allows four short sentences, the question answer's three."""
MOST_ITEMS: Final = 6
MOST_WORDS: Final = 80
NAME_WORDS: Final = range(2, 6)


def style_problems(shown: PlannerAnswer, facts: PlannerFacts) -> list[str]:
    """The Portal's style for the model's own words: a card name of 2 to 5 words, and an answer
    of at most three short sentences or a short list, in plain words with no markup, no long
    dash, no jargon beyond the person's own names, and no talk of the facts it was given."""
    found = [
        f"a name of {len(c.name.split())} words: {c.name}"
        for c in cards_of(shown)
        if len(c.name.split()) not in NAME_WORDS
    ]
    if not isinstance(shown, QuestionAnswer | FreeReplyAnswer):
        return found
    text = shown.text
    most = MOST_FREE_SENTENCES if isinstance(shown, FreeReplyAnswer) else MOST_SENTENCES
    lines = text.splitlines()
    items = [line for line in lines if LIST_ITEM.match(line)]
    prose = " ".join(line for line in lines if not LIST_ITEM.match(line))
    sentences = len(re.findall(r"[.!?](?:\s|$)", prose))
    if sentences > most:
        found.append(f"{sentences} sentences")
    if len(items) > MOST_ITEMS:
        found.append(f"{len(items)} list items")
    if len(text.split()) > MOST_WORDS:
        found.append(f"{len(text.split())} words")
    if "—" in text or "–" in text:
        found.append("a long dash")
    if MARKUP.search(text):
        found.append("markup")
    found += [said.group(0) for said in [SELF_TALK.search(text)] if said]
    own = " ".join([w.name for w in facts.watchlist or []] + facts.workflow_names()).lower()
    found += [f"jargon: {term}" for term in jargon(text) if term.lower() not in own]
    return found + themed_names(text)


def _leading_word(text: str) -> str:
    first = re.match(r"\s*([A-Za-z]+)", text)
    return first.group(1).lower() if first else ""


ANY_BLOCK: Final = "Build it with any n8n block"
"""The Portal's quiet link on a card, which sends the words to the drafter (drafted.ts)."""
DRAFTING: Final = "Drafting it as an n8n workflow"
"""The drafted workflow's card while the drafter works (DRAFTING_TITLE in drafted.ts)."""
START_LEAD: Final = (
    "This app runs repetitive work for you. Tell me the task and I'll draft it. Nothing is "
    "written until an Approver approves it."
)
"""How to start's first sentence (answers.ts)."""


def words_of(
    result: AnswerResult | None, facts: PlannerFacts = HOME_FACTS, operator: bool = False
) -> str:
    """About what the Portal shows for the answer: its card or sentence, with a state answer
    filled from the facts as the Portal fills it from the platform, then each part it crossed,
    in the Portal's words. The Portal's own layout decides the rest. `operator` adds what only
    an Operator sees: Watch it, the watchlist's time, the quiet link to the drafter and the
    drafter's card for a can't it takes."""
    if result is None:
        return "(no answer was recorded)"
    if isinstance(result, ModelProblem):
        return (
            f"(The Planner had no answer, so the Portal shows its offline answer: {result.message})"
        )
    shown, parts = result.answer, result.parts
    if operator and _to_the_drafter(shown):
        return DRAFTING
    followed_nothing = bool(parts) and all(p.reason == "not_followed" for p in parts)
    if isinstance(shown, AbilitiesAnswer) and followed_nothing:
        return FOLLOWED_NOTHING
    lines = _said(shown, facts, operator)
    # A free reply answers the whole message and the fallback card replaces the crosses, so the
    # Portal draws neither's (leftoverParts in parts.ts).
    whole = isinstance(shown, FreeReplyAnswer | DidntFollowAnswer)
    if not whole and (
        not isinstance(shown, RefusedAnswer | WhichSoftwareAnswer)
        or (isinstance(shown, RefusedAnswer) and not shown.rest)
    ):
        # A refusal that offers no set-up draws the rest's crosses; the card names the skip.
        named = ("cant_do", "needs_the_rest") if isinstance(shown, CantAnswer) else ()
        named += ("skip_approval",)
        crossed = [p for p in parts if p.mark != "will_do" and p.reason not in named]
        lines += [_cross(p, facts.watchlist_schedule) for p in crossed]
        offered = operator and _offers_the_watchlist_time(shown)
        lines += [_watchlist_runs(p) for p in crossed if offered and p.reason == "own_time"]
    return "\n".join(lines + _buttons(shown) + (_draft_offer(shown) if operator else []))


def _offers_the_watchlist_time(shown: PlannerAnswer) -> bool:
    """Whether the Portal offers the watchlist's time under a time of its own: in the crosses it
    draws above the answer (leftoverParts in parts.ts), with somewhere to send it. A set-up card
    or a part card holds its own crosses, and the troubleshooter's run card draws them with
    nowhere to send it (Thread.tsx)."""
    match shown:
        case (
            SetupCardAnswer()
            | WhyStoppedAnswer()
            | PartAnswer()
            | EditAnswer()
            | WhichSoftwareAnswer()
            | FreeReplyAnswer()
            | DidntFollowAnswer()
            | CantAnswer(alternative=SetupCardAnswer())
        ):
            return False
        case RefusedAnswer():
            return not shown.rest.strip()
        case _:
            return True


def _watchlist_runs(part: RequestPart) -> str:
    """The offer under a time one software can't have of its own (watchlistRuns in parts.ts)."""
    return f"[Make the Software watchlist run {part.text.strip()}]"


def _to_the_drafter(shown: PlannerAnswer) -> bool:
    """Whether the platform hands an Operator's can't to the drafter, so the Portal shows the
    drafted workflow's card in its place (ADR 0053, item 5, `to_the_drafter` in platform-api)."""
    return (
        isinstance(shown, CantAnswer)
        and shown.alternative is None
        and all(
            r.needs is not None and r.instead is not None and not r.unsupported for r in shown.cant
        )
    )


def _draft_offer(shown: PlannerAnswer) -> list[str]:
    """The quiet link the platform adds for an Operator to a card from our blocks, and to a can't
    or a part card unless every part is one it refuses outright (`_offer_draft` in
    platform-api)."""
    if isinstance(shown, SetupCardAnswer) or (
        isinstance(shown, CantAnswer | PartAnswer) and not all(r.unsupported for r in shown.cant)
    ):
        return [f"[{ANY_BLOCK}]"]
    return []


def _buttons(shown: PlannerAnswer) -> list[str]:
    """The card's own buttons, as the Portal draws them (SetupCard.tsx). A software card draws
    its own (`_software_card`)."""
    match shown:
        case SetupCardAnswer():
            return ["[Never mind] [Set up]"]
        case PartAnswer():
            return ["[Never mind] [Set up the part I can]"]
        case _:
            return []


VERSION_WORD: Final = re.compile(
    r"\b(?:versions?|releas(?:e|es|ed|ing)|upgrad(?:e|es|ed|ing)|patch(?:es|ed|ing)?)\b",
    re.IGNORECASE,
)
"""A word that asks about versions (VERSION_WORD in answers.ts)."""


def _software_card(shown: WatchlistAnswer, facts: PlannerFacts, operator: bool) -> list[str]:
    """The Portal's software card (SoftwareCard in AnswerCards.tsx). A software the watchlist
    holds, by its name with case and spaces aside, shows its pill, where it stands and Open it.
    One it doesn't hold says so, with Watch it for an Operator only. With no name, the card
    opens the Software watchlist."""
    if shown.software is None:
        return ["The Software watchlist [Open the Software watchlist]"]
    wanted = " ".join(shown.software.casefold().split())
    held = facts.watchlist or []
    listed = next((w for w in held if " ".join(w.name.casefold().split()) == wanted), None)
    if listed is not None:
        return [f"{listed.name} ({_pill(listed)}): {_where_it_stands(listed)} [Open it]"]
    said = (
        "It isn't on the watchlist, so I don't know which version you run."
        if VERSION_WORD.search(shown.word)
        else "It isn't on the watchlist yet."
    )
    return [f"{shown.software}: {said}{' [Watch it]' if operator else ''}"]


PILL_OF_STATE: Final[dict[str, str]] = {
    "Can’t check": "Can’t check",
    "Can't check": "Can’t check",
    "New version": "Newer out",
    "Ticket waiting for approval": "Newer out",
    "Ticket open": "Newer out",
    "Not checked yet": "Watching",
    "Nothing newer yet": "Watching",
}
"""The SoftwareCard's pill (stateOf in software.ts) for each state word the facts carry
(STATUS_WORDS in platform-api). The facts don't say whether GitHub can't find a software, so a
software that can't be checked shows Can't check, never Can't find."""


def _pill(row: WatchedFact) -> str:
    if row.state == "Up to date":
        return "Watching" if row.our_version is None else "Up to date"
    return PILL_OF_STATE.get(row.state, row.state)


def _where_it_stands(row: WatchedFact) -> str:
    """Where a watched software stands (sentenceFor in software.ts), from its facts."""
    newest, ours = row.newest_version, row.our_version
    if _pill(row) == "Can’t check":
        return (
            f"The last check stopped. The newest version it read was {newest}."
            if newest is not None
            else "The last check stopped before it read the newest version."
        )
    if newest is None:
        return "Not checked yet. The first check reads the newest release."
    if ours is None:
        return f"Newest is {newest}. The version you run isn't known yet."
    return (
        f"You run {ours}, the newest." if ours == newest else f"You run {ours}. Newest is {newest}."
    )


DAY_WORDS: Final[dict[str, str]] = {
    "every_day": "every day",
    "weekdays": "every weekday",
    "monday": "every Monday",
    "tuesday": "every Tuesday",
    "wednesday": "every Wednesday",
    "thursday": "every Thursday",
    "friday": "every Friday",
    "saturday": "every Saturday",
    "sunday": "every Sunday",
}
"""The Portal's words for when the Software watchlist checks (dayLabel in software.ts)."""


def _cross(part: RequestPart, watching: WatchlistScheduleFact | None = None) -> str:
    """A time one software can't have of its own names when the watchlist checks, as the Portal
    words it from the watchlist's schedule (crossWords in parts.ts)."""
    head = "Question" if part.mark == "question" else "Can't do"
    why = part.note or REASON_WORDS.get(part.reason or "", "")
    if part.reason == "own_time" and watching is not None:
        when = f"{DAY_WORDS[watching.day]} at {watching.at.removeprefix('0')}"
        why = (
            f"The Software watchlist checks all your software together, {when}. I can't give one "
            "software its own time yet."
        )
    return f"{head}: “{part.text}” {why}".rstrip()


def _how_to_start() -> list[str]:
    """The Portal's How to start card (startSteps and startingPoints in answers.ts)."""
    examples = [e.text for e in CAPABILITY_LIST.examples if e.kind != "learn"]
    teams = any(c.id == "teams.ask" and c.state == "ready" for c in CAPABILITY_LIST.capabilities)
    first = f", like “{examples[0]}”" if examples else ""
    steps = [
        f"Tell me what should run by itself, in your own words{first}.",
        "Check the card I make, and change anything I guessed.",
        "Press Set up. I do a test run, which writes nothing.",
        "If the test passes, press Turn it on.",
        f"Nothing is written until an Approver approves it{' in Teams' if teams else ''}.",
    ]
    numbered = [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    return ["How to start:", START_LEAD, *numbered, " ".join(f"[{text}]" for text in examples)]


def _said(shown: PlannerAnswer, facts: PlannerFacts, operator: bool = False) -> list[str]:
    match shown:
        case SetupCardAnswer() | PartAnswer():
            lines = [f"Here's what I understood. A workflow named “{shown.name}”:"]
            lines += [_row(row) for row in shown.rows]
            return lines + (
                [_cant_line(c) for c in shown.cant] if isinstance(shown, PartAnswer) else []
            )
        case CantAnswer():
            lines = [_cant_line(c) for c in shown.cant]
            match shown.alternative:
                case SetupCardAnswer() as card:
                    lines += ["What I can do instead:", *_said(card, facts), *_buttons(card)]
                case WatchlistAnswer() as watch:
                    lines += _said(watch, facts, operator)
                case None:
                    lines.append("[Ask the team]")
            return lines
        case WatchlistAnswer():
            lines = _software_card(shown, facts, operator)
            if shown.also is None:
                return lines
            return [*lines, "The rest of your request:", *_said(shown.also, facts, operator)]
        case WhichSoftwareAnswer():
            return [f"Which software should I watch? (from “{shown.word}”)"]
        case RefusedAnswer():
            lines = [f"{REFUSED} (“{shown.said}”)"]
            return lines + ([f"Set it up with approval: “{shown.rest}”"] if shown.rest else [])
        case CheckWorkflowsAnswer():
            return _workflows(facts, shown.workflow_words, operator)
        case WhyStoppedAnswer():
            named = _named(facts, shown.workflow_words)
            which = f"“{named[0].name}”" if len(named) == 1 else "the run you pick"
            return [
                f"[The AI troubleshooter opens the last run of {which}: what went wrong, in plain "
                "words, whether a retry is safe, and Retry.]"
            ]
        case NeedsMeAnswer():
            return _needs(facts)
        case AbilitiesAnswer(how_to_start=True):
            return _how_to_start()
        case AbilitiesAnswer():
            return [f"What I can do: {'; '.join(CAN)}. Not yet: {', '.join(NOT_YET)}."]
        case QuestionAnswer():
            return [shown.text]
        case EditAnswer():
            change = shown.cant or (
                shown.schedule.model_dump_json(exclude_defaults=True)
                if shown.schedule
                else "nothing"
            )
            return [f"Change {_which(shown.workflow_words)}: {change}."]
        case PauseAnswer() | ResumeAnswer():
            return [f"{shown.kind.capitalize()} {_which(shown.workflow_words)}, one of yours."]
        case RemoveSoftwareAnswer():
            return _removal(shown, facts)
        case ExplainAnswer():
            return _explained(shown, facts, operator)
        case FreeReplyAnswer():
            taps = [f"[{choice}]" for choice in shown.choices]
            if shown.form == "cant":
                taps.append(f"[Try “{shown.offer.request}”]" if shown.offer else "[Ask the team]")
            return [shown.text, *taps]
        case DidntFollowAnswer():
            return ["I didn't follow that. [Say it another way]"]


def _removal(shown: RemoveSoftwareAnswer, facts: PlannerFacts) -> list[str]:
    """The Portal's card for software to take off the watchlist."""
    if not shown.watched_as:
        held = ", ".join(w.name for w in facts.watchlist or []) or "nothing"
        return [f"{shown.software} isn't on your Watchlist. It holds {held}."]
    return [
        f"Remove {name} from the Watchlist? [Remove from watchlist]" for name in shown.watched_as
    ]


SENTENCE: Final = (
    "[the sentence its page shows, built by code: when it runs, what it checks, and what it does "
    "when it finds something, as creating a ticket after approval] [Open the workflow]"
)
"""The Portal's explain card (ADR 0051, amended 26 Nov 2026), which the judge can't open."""


def _explained(shown: ExplainAnswer, facts: PlannerFacts, operator: bool) -> list[str]:
    """The Portal's explain card, for each workflow whose name holds every word the answer
    gives. Words that name none explain the only workflow, and ask which of several, as a new
    chat with nothing in focus does. With no workflow, the platform says they have none."""
    words = shown.workflow_words
    if words is None and facts.workflows_in_all() == 0:
        return _workflows(facts, None, operator)
    rows = list(facts.workflows or [])
    if words is not None:
        said = set(re.findall(r"\w+", words.casefold())) - {"the", "my", "our"}
        rows = [w for w in rows if said <= set(re.findall(r"\w+", w.name.casefold()))]
        if not rows:
            return [
                f"I can't find a workflow called that. I looked for “{words}”. [Check my workflows]"
            ]
    if len(rows) != 1 or (words is None and facts.workflows_in_all() != 1):
        return ["Which workflow?", " ".join(f"[Explain the {w.name}]" for w in rows)]
    return [f"“{rows[0].name}”: {SENTENCE}"]


def _named(facts: PlannerFacts, workflow_words: str | None) -> list[WorkflowFact]:
    """The workflows the words name by whole words, or all of them when they name none."""
    rows = facts.workflows or []
    said = set(re.findall(r"\w+", (workflow_words or "").casefold())) - {"the", "my", "our"}
    named = [w for w in rows if said and set(re.findall(r"\w+", w.name.casefold())) <= said]
    return named or rows


def _workflows(facts: PlannerFacts, workflow_words: str | None, operator: bool) -> list[str]:
    rows = _named(facts, workflow_words)
    if not rows:
        # workflowsSay in answers.ts, with the Open Workflows link under it.
        none = (
            "You have no workflows yet."
            if operator
            else ("There are no workflows yet. Operators set them up.")
        )
        return [f"{none} [Open Workflows]"]
    every = len(rows) == len(facts.workflows or [])
    if len(rows) == 1 and (not every or facts.workflows_in_all() == 1):
        return [_one_workflow(rows[0])]
    stopped = sum(w.last_run == "Stopped" for w in rows)
    paused = sum(w.state == "paused" for w in rows)
    counts = [f"{stopped} stopped" if stopped else "", f"{paused} paused" if paused else ""]
    head = f"You have {len(rows)} workflow{'s' if len(rows) != 1 else ''}."
    lines = [" ".join([head, ", ".join(c for c in counts if c) + "."]).replace(" .", "")]
    return lines + [f"- {w.name}: {w.state}, last run {w.last_run or 'none'}" for w in rows]


def _one_workflow(row: WorkflowFact) -> str:
    """The Portal's sentence about one workflow (oneWorkflowSay in answers.ts). The facts carry no
    next run, so it is left out here."""
    life = "a draft" if row.state == "draft" else row.state
    at = row.last_run_at
    day = "" if at is None else f" {at:%a} {at.day} {at:%b}"
    last = row.last_run
    ran = "It hasn't run yet." if last is None else f"Last run{day}, {last.lower()}."
    return f"“{row.name}” is {life}. {ran}"


NEEDS_WORDS: Final = {
    "approvals": "waiting for approval",
    "confirmations": "test run to confirm",
    "stopped": "stopped run",
    "connections": "connection to set up",
    "addresses": "address to allow",
    "replies": "reply to read",
    "declined": "declined test run",
    "questions": "question from an Approver",
}


def _needs(facts: PlannerFacts) -> list[str]:
    needs = facts.needs_you
    if needs is None or needs.total == 0:
        return ["Nothing needs you right now."]
    counts = needs.model_dump(exclude={"total"})
    lines = [f"{needs.total} things need you:"]
    return lines + [f"- {n} {NEEDS_WORDS[name]}" for name, n in counts.items() if n]


def _which(workflow_words: str | None) -> str:
    return f"“{workflow_words}”" if workflow_words else "your workflows"


def _row(row: UnderstoodRow) -> str:
    state = "" if row.state == "understood" else f" ({row.state})"
    note = f" {row.note}" if row.note else ""
    return f"- {row.kind}: {row.text or '(empty)'}{state}{note}"


def _cant_line(row: CantRow) -> str:
    instead = f" Instead: {row.instead}" if row.instead else ""
    return f"Can't: {row.text}. {row.note}{instead}"


def judge_question(case: AnythingCase, answer: str) -> str:
    can = "; ".join(c.plain for c in CAPABILITY_LIST.capabilities if c.state == "ready")
    not_yet = "; ".join(c.plain for c in CAPABILITY_LIST.capabilities if c.state == "planned")
    never = "; ".join(c.plain for c in CAPABILITY_LIST.capabilities if c.state == "unsupported")
    return (
        "You check one reply of the Planner, the assistant in the box on the Home page of a work "
        "platform. Its users are support staff who are not technical. They type anything into "
        "the box, and expect a proper, logical and useful reply.\n\n"
        f"What the platform can do: {can}.\nWhat it can't do yet: {not_yet}.\n"
        f"What it never does: {never}.\nEvery change, such as a new Jira ticket, waits for an "
        "Approver's yes in Teams. A request to skip that yes must be refused.\n\n"
        f"The person typed:\n{case.task}\n\n"
        f"The Planner showed them (cards and buttons are described in brackets or as lines):\n"
        f"{words_of(result_of(answer), case.facts, case.changes_workflows)}\n\n"
        "Score how proper, logical and useful this reply is for exactly what they typed:\n"
        "5: it answers or does what they asked, or says plainly what it can't do and gives a "
        "way forward.\n4: useful, with a small gap.\n3: partly useful; the person has to guess "
        "what to do next.\n2: it mostly misses what they asked, or is confusing.\n"
        "1: useless, wrong or self-contradicting, or it refuses something harmless.\n"
        "Refusing a real request to skip the yes is correct, however short. Judge the reply "
        "only, not the platform's limits."
    )


ANYTHING = Job(
    name="anything",
    title="Answer anything a person types on Home",
    case_type=AnythingCase,
    prompt=lambda case: case.task,
    schema=None,
    score=score,
    judged=True,
    time_limit_s=ANSWER_TIMEOUT_SECONDS,
    product_call=ask,
    judge_question=judge_question,
    most_calls=2,
)


def score_led(case: AnythingCase, answer: Answer) -> list[Check]:
    """The same checks, and no tick on a clause the call's arguments don't reach (ADR 0049)."""
    found = score(case, answer)
    if isinstance(answer.extra, Led):
        found.append(check("ticks_reached", false_ticks(answer.extra)))
    return found


ANYTHING_LED = replace(ANYTHING, product_call=ask_with(led), score=score_led, most_calls=6)
"""The same set on the AI-led Planner: its turn, the rules' reading beside it, a second turn
when the first call can't be used, a second reading for a joined request, and the verifier."""
