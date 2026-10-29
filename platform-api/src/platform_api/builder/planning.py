"""Planning a task: the Planner picks saved agents, or drafts a new one for the Operator.

The model's answer is untrusted. It can only point at cards in the library and fill their
inputs, and every value and every draft is checked here before the Portal shows it. Planning
never saves anything.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Final, Literal, Protocol

from platform_api.builder.cards import check_card, library_card
from platform_api.builder.models import (
    CannotDo,
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CardView,
    MissingTool,
    ModelTrouble,
    NewAgent,
    PlannedAgent,
    PlanOut,
    Starters,
    StarterView,
    UnderstandOut,
    UnderstoodRows,
    UnderstoodRowView,
    UseSaved,
    WatchlistRedirect,
)
from platform_api.orchestration import (
    BelongsOnWatchlist,
    CardDraft,
    Choice,
    ChooseResult,
    Chosen,
    Drafted,
    DraftResult,
    LibraryCard,
    ModelProblem,
    NoModel,
    RuntimeDown,
    UnderstandResult,
    Understood,
    check_value,
)

log = logging.getLogger(__name__)

MAX_AGENTS = 3
REASON_LIMIT = 500
QUESTION_LIMIT = 300
QUESTION_COUNT = 5
PART_LIMIT = 300
MISSING_COUNT = 5


class CardPlanner(Protocol):
    async def has_model(self) -> bool: ...

    async def choose(
        self, task: str, library: Sequence[LibraryCard]
    ) -> ChooseResult | NoModel | RuntimeDown: ...

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown: ...


class TaskReader(Protocol):
    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown: ...


class Planning(CardPlanner, TaskReader, Protocol): ...


class NoPlanner:
    """Stands in until a planner is wired, so nothing can be planned or run."""

    async def has_model(self) -> bool:
        return False

    async def choose(
        self, task: str, library: Sequence[LibraryCard]
    ) -> ChooseResult | NoModel | RuntimeDown:
        return NoModel()

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown:
        return NoModel()

    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown:
        return NoModel()


class NoModelConnected:
    """Planning needs an AI model, and none is connected."""


class RuntimeNotAnswering:
    """The agent runtime did not give a usable answer."""


PROBLEM_WORDS: Mapping[str, str] = {
    "address_not_allowed": "The AI model's address is not allowed. Check it in Settings.",
    "unreachable": "The AI model could not be reached. Try again, or check Settings.",
    "key_refused": "The AI model refused the key. Check the key in Settings.",
    "not_a_model_api": "The address in Settings does not look like an AI model service.",
    "no_text_models": "The AI model service has no model that can write text. Check Settings.",
    "model_not_found": "The saved AI model was not found at its address. Check Settings.",
    "too_slow": "The AI model answered too slowly. Try again.",
    "unusable_answer": "The AI model gave an answer the platform could not use. Try again.",
    "failed": "The AI model did not work. Try again, or check Settings.",
}


def _short(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _questions(*groups: Sequence[str]) -> list[str]:
    """The model's questions: plain one-liners, no repeats, a few of them."""
    kept = dict.fromkeys(
        _short(text, QUESTION_LIMIT) for group in groups for text in group if text.strip()
    )
    return list(kept)[:QUESTION_COUNT]


def planned_agents(choice: Choice, library: Mapping[str, CardView]) -> list[PlannedAgent]:
    """The chosen agents that are real: a card in the library, once, with only the values that
    belong to its inputs and fit their kinds. What is not given is listed as missing."""
    agents: list[PlannedAgent] = []
    for chosen in choice.agents:
        card = library.get(chosen.card_id)
        if card is None or any(a.card.card_id == card.card_id for a in agents):
            continue
        values: dict[str, str] = {}
        for item in card.inputs:
            given = chosen.values.get(item.name)
            if given is None:
                continue
            if check_value(item.kind, given.strip()) is None:
                values[item.name] = given.strip()
        missing = [item.name for item in card.inputs if item.name not in values]
        agents.append(
            PlannedAgent(
                card=card, part=_short(chosen.part, PART_LIMIT), values=values, missing=missing
            )
        )
    return agents[:MAX_AGENTS]


def _definition(draft: CardDraft) -> CardDefinition:
    return CardDefinition(
        name=draft.name,
        purpose=draft.purpose,
        good_for=draft.good_for,
        inputs=[
            CardInput(name=i.name, kind=i.kind, what=i.what, example=i.example)
            for i in draft.inputs
        ],
        blocks=[CardBlock(say=b.say, tool=b.tool) for b in draft.blocks],
        approvals=[CardApprovalView(tool=a.tool, approvers=a.approvers) for a in draft.approvals],
    )


def _missing(draft: CardDraft) -> list[MissingTool]:
    return [
        MissingTool(need=_short(m.need, QUESTION_LIMIT), why=_short(m.why, QUESTION_LIMIT))
        for m in draft.missing_tools[:MISSING_COUNT]
    ]


async def plan(
    planner: CardPlanner, library: Sequence[CardView], task: str
) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
    """The Planner's plan for a task, from the library of saved agents."""
    by_id = {card.card_id: card for card in library}
    chosen = await planner.choose(task, [library_card(card) for card in library])
    match chosen:
        case NoModel():
            return NoModelConnected()
        case RuntimeDown():
            return RuntimeNotAnswering()
        case ModelProblem() as problem:
            return _trouble(problem)
        case Chosen(choice=choice):
            pass
    reason = _short(choice.reason, REASON_LIMIT)
    questions = _questions(choice.questions)
    match choice.decision:
        case "cannot_do":
            return CannotDo(reason=reason, missing_tools=[])
        case "use_one" | "use_several":
            agents = planned_agents(choice, by_id)
            if agents:
                return UseSaved(
                    decision="use_one" if len(agents) == 1 else "use_several",
                    agents=agents,
                    reason=reason,
                    questions=questions,
                )
        case "new_agent":
            pass
    return await _draft(planner, task, reason, questions)


async def _draft(
    planner: CardPlanner, task: str, reason: str, questions: list[str]
) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
    drafted = await planner.draft(task)
    match drafted:
        case NoModel():
            return NoModelConnected()
        case RuntimeDown():
            return RuntimeNotAnswering()
        case ModelProblem() as problem:
            return _trouble(problem)
        case Drafted(draft=draft):
            pass
    if not draft.can_do:
        return CannotDo(
            reason=_short(
                draft.why_not or reason or "The Planner cannot do this task.", REASON_LIMIT
            ),
            missing_tools=_missing(draft),
        )
    checked = check_card(_definition(draft))
    return NewAgent(
        draft=checked.card,
        approvals=checked.approvals,
        problems=checked.problems,
        reason=reason,
        missing_tools=_missing(draft),
        questions=_questions(questions, draft.questions),
    )


def _trouble(problem: ModelProblem) -> ModelTrouble:
    return ModelTrouble(message=PROBLEM_WORDS.get(problem.reason, PROBLEM_WORDS["failed"]))


UNDERSTAND_LIMIT_SECONDS: Final = 10.0
FOLLOW_UP_TASK: Final = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)
STARTERS: Final = (
    StarterView(
        name="Keep our software up to date",
        what="Add the software your team runs. The Software watchlist checks each one for new "
        "releases, with one approval for all the upgrade tickets.",
        task=None,
        opens="software_watchlist",
    ),
    StarterView(
        name="Weekly summary of closed tickets",
        what="Sum up the Jira tickets closed this week in one new ticket for the team.",
        task="Every Friday at 4pm, find the tickets in MOCK closed this week and create one "
        "ticket that sums them up",
        opens=None,
    ),
    StarterView(
        name="Follow up stale bug tickets",
        what="Find bug tickets with no update for 10 days and list them in one follow-up ticket.",
        task=FOLLOW_UP_TASK,
        opens=None,
    ),
)
type FallbackWhy = Literal["no_model", "too_slow", "trouble"]
FALLBACK_WORDS: Final[Mapping[FallbackWhy, str]] = {
    "no_model": "No AI model is connected, so the Planner can't read your task yet. Start from "
    "one of these, or connect a model in Settings.",
    "too_slow": "The Planner took too long to read your task. Start from one of these, or try "
    "again.",
    "trouble": "The Planner couldn't read your task just now. Start from one of these, or try "
    "again.",
}


def watchlist_note(word: str) -> str:
    return (
        f"You mentioned “{word}”, so I think this is about the software your team runs. It "
        "belongs on the Software watchlist, where your team keeps all its software and checks "
        "it for new releases. You don't need a new workflow."
    )


def starters(why: FallbackWhy) -> Starters:
    return Starters(message=FALLBACK_WORDS[why], starters=list(STARTERS))


def _fall_back(why: FallbackWhy, detail: str) -> Starters:
    log.warning("The Planner's reading fell back to the starter workflows: %s", detail)
    return starters(why)


def understood_out(answer: UnderstandResult | NoModel | RuntimeDown) -> UnderstandOut:
    match answer:
        case NoModel():
            return _fall_back("no_model", "no AI model is connected")
        case RuntimeDown(detail=detail):
            return _fall_back("trouble", detail)
        case ModelProblem(reason=reason):
            why: FallbackWhy = "too_slow" if reason == "too_slow" else "trouble"
            return _fall_back(why, f"the model's answer was {reason}")
        case BelongsOnWatchlist(word=word, software=software):
            return WatchlistRedirect(word=word, software=software, note=watchlist_note(word))
        case Understood(rows=rows):
            return UnderstoodRows(
                rows=[
                    UnderstoodRowView(kind=r.kind, text=r.text, state=r.state, note=r.note)
                    for r in rows
                ]
            )


async def understand(planner: TaskReader, text: str) -> UnderstandOut:
    """What the Planner understood of a task. Model trouble answers the starters: no model
    connected, the runtime down or refusing, a model problem, or no answer within the limit. A
    failure to read the model settings from the database is not model trouble, so it is raised
    and the route answers 500."""
    limit = UNDERSTAND_LIMIT_SECONDS
    try:
        async with asyncio.timeout(limit):
            answer = await planner.understand(text)
    except TimeoutError:
        return _fall_back("too_slow", f"no answer within {limit:g} seconds")
    return understood_out(answer)
