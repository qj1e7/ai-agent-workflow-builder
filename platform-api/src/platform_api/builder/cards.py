"""Agent cards: the starter card, the checks on a card, and how a card reads as other shapes.

Pure. The tables are in card_store.py. A card is data, not code (ADR 0023): blocks name tools
the runtime built, and this file decides what a card may ask for. Whatever the model drafts is
checked here before anyone can save it.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime

from platform_api.builder.models import (
    BlockView,
    CardApprovalView,
    CardBlock,
    CardBlockView,
    CardChecked,
    CardDefinition,
    CardInput,
    CardInputView,
    CardProblem,
    CardView,
    ToolList,
    ToolView,
)
from platform_api.orchestration import (
    INPUT_KINDS,
    KIND_EXAMPLES,
    MAX_APPROVERS,
    RULES,
    TOOL_RULES,
    CardSpec,
    LibraryCard,
    LibraryInput,
    ToolId,
    check_value,
    tools_used,
    write_tools_used,
)
from platform_api.orchestration import CardBlock as RuntimeBlock
from platform_api.orchestration import CardInput as RuntimeInput
from platform_api.shared import UserId

PLATFORM_OWNER = UserId("platform")
# How an Operator reads each input kind. The Portal calls inputs "details".
KIND_LABELS: Mapping[str, str] = {
    "github_repo": "GitHub repository",
    "jira_project": "Jira project",
    "text": "text",
}
STARTER_CREATED_AT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)

NAME_LIMIT = 60
PURPOSE_LIMIT = 300
GOOD_FOR_COUNT = 5
GOOD_FOR_LIMIT = 100
INPUT_COUNT = 8
WHAT_LIMIT = 200
EXAMPLE_LIMIT = 100
BLOCK_COUNT = 12
SAY_LIMIT = 300
LIBRARY_LIMIT = 50

OLD_NAMES = re.compile(
    r"\b(Flint|Forge|Striker|Spark\s+Map|Scout|Analyst|Messenger|Clerk|Fixer|Kindling|"
    r"Firebreak|Ember)\b",
    re.IGNORECASE,
)


def tool_list() -> ToolList:
    return ToolList(
        tools=[
            ToolView(
                id=rule.id,
                kind=rule.kind,
                name=rule.name,
                description=rule.description,
                target_input=rule.target_input,
                min_approvers=rule.min_approvers,
            )
            for rule in TOOL_RULES
        ]
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def check_card(card: CardDefinition) -> CardChecked:
    """Cleans a card up, works out its approvals and lists what stops it being saved.

    Saving needs no problems. The approvals are not problems: for each write tool the blocks
    use, they are what was asked for raised to the tool's minimum and capped at 2, and
    approvals for tools the blocks do not use are dropped.
    """
    problems: list[CardProblem] = []

    def problem(field: str | None, message: str) -> None:
        problems.append(CardProblem(field=field, message=message))

    def limited(text: str, limit: int, field: str, noun: str, minimum: int = 0) -> str:
        if len(text) > limit:
            problem(field, f"{noun} can be at most {limit} characters.")
        elif len(text) < minimum:
            problem(field, f"{noun} cannot be empty.")
        return text

    name = limited(_one_line(card.name), NAME_LIMIT, "name", "The name", 2)
    purpose = limited(_one_line(card.purpose), PURPOSE_LIMIT, "purpose", "The purpose", 1)
    good_for = [text for text in (_one_line(g) for g in card.good_for) if text]
    if len(good_for) > GOOD_FOR_COUNT:
        problem("good_for", f"Give at most {GOOD_FOR_COUNT} examples of requests.")
    for index, text in enumerate(good_for):
        limited(text, GOOD_FOR_LIMIT, f"good_for.{index}", "An example request")

    inputs: list[CardInput] = []
    if len(card.inputs) > INPUT_COUNT:
        problem("inputs", f"An agent can have at most {INPUT_COUNT} inputs.")
    seen: set[str] = set()
    for index, item in enumerate(card.inputs):
        input_name = limited(
            _one_line(item.name), NAME_LIMIT, f"inputs.{index}.name", "An input name", 1
        )
        kind = item.kind.strip()
        if kind not in INPUT_KINDS:
            problem(
                f"inputs.{index}.kind",
                f"The kind of {input_name or 'an input'} must be one of {', '.join(INPUT_KINDS)}.",
            )
        if input_name.lower() in seen:
            problem(f"inputs.{index}.name", f"Two inputs are called {input_name}.")
        seen.add(input_name.lower())
        what = limited(_one_line(item.what), WHAT_LIMIT, f"inputs.{index}.what", "The description")
        example = limited(
            _one_line(item.example), EXAMPLE_LIMIT, f"inputs.{index}.example", "The example"
        )
        inputs.append(CardInput(name=input_name, kind=kind, what=what, example=example))

    blocks: list[CardBlock] = []
    if not card.blocks:
        problem("blocks", "Add at least one block.")
    if len(card.blocks) > BLOCK_COUNT:
        problem("blocks", f"An agent can have at most {BLOCK_COUNT} blocks.")
    for index, item in enumerate(card.blocks):
        say = limited(_one_line(item.say), SAY_LIMIT, f"blocks.{index}.say", "A block", 1)
        tool = (item.tool or "").strip() or None
        if tool is not None and tool not in RULES:
            problem(f"blocks.{index}.tool", f"{tool} is not a tool the platform has.")
        blocks.append(CardBlock(say=say, tool=tool))

    used = tuple(dict.fromkeys(b.tool for b in blocks if b.tool is not None and b.tool in RULES))
    asked: set[str] = set()
    for tool in used:
        rule = RULES[tool]
        kind = rule.target_input or rule.scope_input
        if kind is None or kind in asked:
            continue
        asked.add(kind)
        matching = [item for item in inputs if item.kind == kind]
        label = KIND_LABELS.get(kind, kind)
        if not matching:
            why = (
                "so the platform knows where the agent writes"
                if rule.target_input
                else "so the agent knows which project it may read"
            )
            problem("inputs", f"Add a {label} detail, {why}.")
        elif len(matching) > 1:
            problem(
                "inputs",
                f"Keep only one {label} detail, because it sets where the agent reads and "
                "writes. Remove the others.",
            )

    for field, text in _words_of(name, purpose, good_for, inputs, blocks):
        found = OLD_NAMES.search(text)
        if found is not None:
            problem(
                field,
                f"{found.group(0)} is an old name that confused the sponsor. Use plain words.",
            )

    requested: dict[str, int] = {}
    for item in card.approvals:
        requested[item.tool] = max(requested.get(item.tool, 0), item.approvers)
    approvals = [
        CardApprovalView(
            tool=rule.id,
            approvers=min(MAX_APPROVERS, max(rule.min_approvers or 1, requested.get(rule.id, 0))),
        )
        for rule in write_tools_used(used)
    ]
    cleaned = CardDefinition(
        name=name,
        purpose=purpose,
        good_for=good_for,
        inputs=inputs,
        blocks=blocks,
        approvals=approvals,
    )
    return CardChecked(card=cleaned, approvals=approvals, problems=problems)


def _words_of(
    name: str,
    purpose: str,
    good_for: Sequence[str],
    inputs: Sequence[CardInput],
    blocks: Sequence[CardBlock],
) -> Iterable[tuple[str, str]]:
    yield "name", name
    yield "purpose", purpose
    for index, text in enumerate(good_for):
        yield f"good_for.{index}", text
    for index, item in enumerate(inputs):
        yield f"inputs.{index}.name", item.name
        yield f"inputs.{index}.what", item.what
        yield f"inputs.{index}.example", item.example
    for index, block in enumerate(blocks):
        yield f"blocks.{index}.say", block.say


def check_values(
    card: CardView, values: Mapping[str, str]
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """The values cleaned, and what is wrong with them as (input name, message).

    An agent runs with exactly one value for each of its inputs, and each value fits its
    input's kind. Text is trimmed first.
    """
    errors: list[tuple[str, str]] = []
    clean: dict[str, str] = {}
    known = {item.name for item in card.inputs}
    errors.extend((name, "This agent has no such input.") for name in values if name not in known)
    for item in card.inputs:
        raw = values.get(item.name)
        if raw is None or not raw.strip():
            errors.append((item.name, f"Required. {KIND_EXAMPLES[item.kind].capitalize()}."))
            continue
        value = raw.strip()
        why = check_value(item.kind, value)
        if why is not None:
            errors.append((item.name, why))
        else:
            clean[item.name] = value
    return clean, errors


def tools_of(card: CardView) -> list[ToolId]:
    return list(tools_used(card_spec(card)))


def card_spec(card: CardView) -> CardSpec:
    """The card as the runtime reads it: this version, pinned."""
    return CardSpec(
        id=card.card_id,
        version=card.version,
        name=card.name,
        purpose=card.purpose,
        inputs=[
            RuntimeInput(name=i.name, kind=i.kind, what=i.what, example=i.example)
            for i in card.inputs
        ],
        blocks=[RuntimeBlock(say=b.say, tool=b.tool) for b in card.blocks],
    )


def library_card(card: CardView) -> LibraryCard:
    return LibraryCard(
        card_id=card.card_id,
        name=card.name,
        purpose=card.purpose,
        good_for=card.good_for,
        inputs=[LibraryInput(name=i.name, kind=i.kind) for i in card.inputs],
        tools=card.tools,
    )


def card_view(
    *,
    card_id: str,
    version: int,
    starter: bool,
    owner: UserId,
    created_at: datetime,
    definition: CardDefinition,
) -> CardView:
    """A saved card as people read it. The definition has been through check_card, and a kind or
    a tool it does not know fails here instead of being saved."""
    view = CardView(
        card_id=card_id,
        version=version,
        starter=starter,
        owner=owner,
        created_at=created_at,
        name=definition.name,
        purpose=definition.purpose,
        good_for=definition.good_for,
        inputs=[CardInputView.model_validate(i.model_dump()) for i in definition.inputs],
        blocks=[CardBlockView.model_validate(b.model_dump()) for b in definition.blocks],
        approvals=definition.approvals,
        tools=[],
    )
    return view.model_copy(update={"tools": tools_of(view)})


VERSION_CHECKER_ID = "crd_version_checker"

VERSION_CHECKER = card_view(
    card_id=VERSION_CHECKER_ID,
    version=1,
    starter=True,
    owner=PLATFORM_OWNER,
    created_at=STARTER_CREATED_AT,
    definition=CardDefinition(
        name="Version checker",
        purpose="Checks a public GitHub repository for a new release and proposes a Jira "
        "ticket for it.",
        good_for=[
            "Check langchain-ai/langgraph for new releases",
            "Tell us when a new version of a public project comes out",
        ],
        inputs=[
            CardInput(
                name="GitHub repository",
                kind="github_repo",
                what="The public repository to watch, as owner/name.",
                example="langchain-ai/langgraph",
            ),
            CardInput(
                name="Jira project",
                kind="jira_project",
                what="The Jira project that gets the ticket.",
                example="MOCK",
            ),
        ],
        blocks=[
            CardBlock(
                say="Read the newest releases of the repository.", tool="github.read_releases"
            ),
            CardBlock(
                say="Look in Jira for a ticket about the newest release, so it is not raised "
                "twice.",
                tool="jira.search",
            ),
            CardBlock(
                say="If there is none, propose a ticket naming the release, its date and its link.",
                tool="jira.create_ticket",
            ),
        ],
        approvals=[CardApprovalView(tool="jira.create_ticket", approvers=1)],
    ),
)
STARTER_CARDS: tuple[CardView, ...] = (VERSION_CHECKER,)
STARTERS: Mapping[tuple[str, int], CardView] = {(c.card_id, c.version): c for c in STARTER_CARDS}


def sorted_for_library(starters: Iterable[CardView], saved: Iterable[CardView]) -> list[CardView]:
    """Starters first, then the team's cards by name."""
    return [*starters, *sorted(saved, key=lambda c: (c.name.lower(), c.card_id))]


APPROVAL_BLOCK = BlockView(
    key="approval_gate",
    name="Approval gate",
    description="An Approver reviews what the agents propose in Teams before anything is written.",
    kind="approval",
)


def plan_for_cards(cards: Sequence[CardView]) -> list[BlockView]:
    """The line a card run draws: one block for each agent, then, if any agent writes, the
    approval gate and one block for each kind of write."""
    blocks = [
        BlockView(key=card.card_id, name=card.name, description=card.purpose, kind="agent")
        for card in cards
    ]
    writes = write_tools_used(tool for card in cards for tool in card.tools)
    if writes:
        blocks.append(APPROVAL_BLOCK)
    blocks.extend(
        BlockView(
            key=rule.id.replace(".", "_"),
            name=rule.action_name or rule.name,
            description=f"{rule.name}, written only after approval.",
            kind="write_action",
        )
        for rule in writes
    )
    return blocks
