"""Planning a task: the Room lead picks saved agents, or drafts a new one for the Operator.

The model's answer is untrusted. It can only point at cards in the library and fill their
inputs, and every value and every draft is checked here before the Portal shows it. Planning
never saves anything.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

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
    """The Room lead's plan for a task, from the library of saved agents."""
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
                draft.why_not or reason or "The Room lead cannot do this task.", REASON_LIMIT
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
