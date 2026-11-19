"""Planning a task: the Planner picks saved agents, or drafts a new one for the Operator.

The model's answer is untrusted. It can only point at cards in the library and fill their
inputs, and every value and every draft is checked here before the Portal shows it. Planning
never saves anything.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from typing import Final, Literal, Protocol

from platform_api.builder.cards import check_card, library_card
from platform_api.builder.draft_repair import (
    NotUsable,
    Repaired,
    TwoProjectInputs,
    TwoProjects,
    one_project_input,
    one_project_only,
    project_to_fill,
    repaired,
    theirs_to_change,
)
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
    StarterView,
    UseSaved,
)
from platform_api.orchestration import (
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
    check_value,
)

log = logging.getLogger(__name__)

MAX_AGENTS = 3
REASON_LIMIT = 500
QUESTION_LIMIT = 300
QUESTION_COUNT = 5
PART_LIMIT = 300
MISSING_COUNT = 5
NO_TOOL: Final = "No tool on the platform does this step yet."
NO_TOOL_FOR_ANY_STEP: Final = "No tool on the platform does any step of this yet."
MORE: Final = "and {} more"
MORE_WHY: Final = "The AI model listed more missing tools than the card shows."


class CardPlanner(Protocol):
    async def has_model(self) -> bool: ...

    async def choose(
        self, task: str, library: Sequence[LibraryCard]
    ) -> ChooseResult | NoModel | RuntimeDown: ...

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown: ...


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


def planned_agents(
    choice: Choice, library: Mapping[str, CardView], task: str, projects: Collection[str] = ()
) -> list[PlannedAgent]:
    """The chosen agents that are real: a card in the library, once, with only the values that
    belong to its inputs and fit their kinds. A Jira project decides where a ticket is written,
    so the model's value for one is kept only when it is the one project of the team's the
    words name as the place, as a drafted agent's is filled. What is not given is listed as
    missing, and the Portal asks for it."""
    project = project_to_fill(task, projects)
    agents: list[PlannedAgent] = []
    for chosen in choice.agents:
        card = library.get(chosen.card_id)
        if card is None or any(a.card.card_id == card.card_id for a in agents):
            continue
        values: dict[str, str] = {}
        for item in card.inputs:
            given = (chosen.values.get(item.name) or "").strip()
            if item.kind == "jira_project":
                given = project if project is not None and given.upper() == project else ""
            if given and check_value(item.kind, given) is None:
                values[item.name] = given
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


def _missing(draft: CardDraft, left_out: Sequence[str] = ()) -> list[MissingTool]:
    """Every step set aside, each in its own words, then the tools the model said are missing,
    as many as fit, and how many more there are, so no part is cut without a word."""
    steps = [MissingTool(need=_short(need, QUESTION_LIMIT), why=NO_TOOL) for need in left_out]
    told = {m.need.casefold() for m in steps}
    said = [
        MissingTool(need=_short(m.need, QUESTION_LIMIT), why=_short(m.why, QUESTION_LIMIT))
        for m in draft.missing_tools
    ]
    said = [m for m in said if m.need.casefold() not in told]
    room = max(0, MISSING_COUNT - len(steps))
    more = [MORE.format(len(said) - room)] if len(said) > room else []
    return [*steps, *said[:room], *(MissingTool(need=need, why=MORE_WHY) for need in more)]


async def plan(
    planner: CardPlanner, library: Sequence[CardView], task: str, projects: Collection[str] = ()
) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
    """The Planner's plan for a task, from the library of saved agents. The projects are those
    the team's Jira allows, so a key the task writes in small letters is read too."""
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
            agents = planned_agents(choice, by_id, task, projects)
            if agents:
                return UseSaved(
                    decision="use_one" if len(agents) == 1 else "use_several",
                    agents=agents,
                    reason=reason,
                    questions=questions,
                )
        case "new_agent":
            pass
    return await _draft(planner, task, reason, questions, projects)


async def _draft(
    planner: CardPlanner, task: str, reason: str, questions: list[str], projects: Collection[str]
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
    match repaired(_definition(draft), task, projects):
        case TwoProjects(keys=keys):
            return CannotDo(reason=one_project_only(keys), missing_tools=_missing(draft))
        case TwoProjectInputs(names=names):
            return CannotDo(reason=one_project_input(names), missing_tools=_missing(draft))
        case NotUsable(why=why):
            log.warning("A drafted card is unusable: %s", why)
            return ModelTrouble(message=PROBLEM_WORDS["unusable_answer"])
        case Repaired() as repair:
            pass
    missing = _missing(draft, repair.left_out)
    if not repair.card.blocks and repair.left_out:
        return CannotDo(reason=NO_TOOL_FOR_ANY_STEP, missing_tools=missing)
    checked = check_card(repair.card)
    if not all(theirs_to_change(problem, task) for problem in checked.problems):
        # What is left only the model can fix, such as a step too long to cut or no step at
        # all: a fresh draft is the way on, and the card's Try again asks for one.
        log.warning("A drafted card is unusable: %s", [p.field for p in checked.problems])
        return ModelTrouble(message=PROBLEM_WORDS["unusable_answer"])
    return NewAgent(
        draft=checked.card,
        approvals=checked.approvals,
        problems=checked.problems,
        reason=reason,
        missing_tools=missing,
        questions=_questions(questions, draft.questions),
        project=repair.project,
    )


def _trouble(problem: ModelProblem) -> ModelTrouble:
    return ModelTrouble(message=PROBLEM_WORDS.get(problem.reason, PROBLEM_WORDS["failed"]))


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
