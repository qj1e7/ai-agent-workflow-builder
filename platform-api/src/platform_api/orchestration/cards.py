"""What the platform decides about agent cards, apart from what the model drafts or says.

The runtime owns the tools' code and the schema the model sees. This file owns the rules for
writes (ADR 0023): which tools write, where a write lands, how many Approvers it needs, and how
the platform reads the agents' proposals. The model never sends a write's target or names an
Approver, so both come only from here and from the card's saved values.

Pure. The run itself is in service.py.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import get_args

from pydantic import TypeAdapter, ValidationError

from platform_api.orchestration.agents import (
    CardSpec,
    InputKind,
    ProposedIntentIn,
    ToolId,
    ToolKind,
)
from platform_api.orchestration.approvals import AnyApprover, ApprovalPolicy, ApprovalStep
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.watch import Unusable
from platform_api.orchestration.write_actions import (
    Binding,
    ProposedIntent,
    UnboundIntent,
    WriteAction,
    bind,
)
from platform_api.shared import JIRA_PROJECT_PATTERN
from platform_api.wire import RepoName

TEXT_LIMIT = 200
TITLE_LIMIT = 200
BODY_LIMIT = 5000
MAX_PROPOSED = 10
MAX_APPROVERS = 2
APPROVER_LABELS = ("Team approver", "Second approver")

_repo_name = TypeAdapter(RepoName)


@dataclass(frozen=True)
class ToolRule:
    id: ToolId
    kind: ToolKind
    name: str
    description: str
    target_input: InputKind | None = None
    """For a write: the kind of the card's one input that names where the write lands."""
    min_approvers: int | None = None
    connector: str | None = None
    operation: str | None = None
    target_key: str | None = None
    action_name: str | None = None
    """How the run line words the write, such as "Create Jira tickets"."""
    scope_input: InputKind | None = None
    """For a read: the kind of the card's one input that limits what the tool may read."""


TOOL_RULES: tuple[ToolRule, ...] = (
    ToolRule(
        "github.read_releases",
        "read",
        "Read GitHub releases",
        "Reads the newest releases of a public GitHub repository.",
    ),
    ToolRule(
        "jira.search",
        "read",
        "Search Jira",
        "Finds tickets in a Jira project by words, status or the day they were done.",
        scope_input="jira_project",
    ),
    ToolRule(
        "jira.read_ticket",
        "read",
        "Read a Jira ticket",
        "Reads one Jira ticket.",
        scope_input="jira_project",
    ),
    ToolRule(
        "jira.create_ticket",
        "write",
        "Create a Jira ticket",
        "Proposes a ticket. It is created only after an Approver approves it.",
        target_input="jira_project",
        min_approvers=1,
        connector="jira",
        operation="create_ticket",
        target_key="project",
        action_name="Create Jira tickets",
    ),
)
RULES: Mapping[str, ToolRule] = {rule.id: rule for rule in TOOL_RULES}
TOOL_IDS: tuple[str, ...] = get_args(ToolId.__value__)
INPUT_KINDS: tuple[str, ...] = get_args(InputKind.__value__)

KIND_EXAMPLES: Mapping[str, str] = {
    "github_repo": "owner/name, for example langchain-ai/langgraph",
    "jira_project": (
        "a capital letter, then capital letters, digits or underscores, for example MOCK or AB_1"
    ),
    "text": f"one line of 1 to {TEXT_LIMIT} characters",
}


def check_value(kind: str, value: str) -> str | None:
    """Why value does not fit its input kind, in plain words, or None when it fits."""
    match kind:
        case "github_repo":
            try:
                _repo_name.validate_python(value)
            except ValidationError:
                return f"Use {KIND_EXAMPLES[kind]}."
        case "jira_project":
            if JIRA_PROJECT_PATTERN.match(value) is None:
                return f"Use {KIND_EXAMPLES[kind]}."
        case "text":
            if not 1 <= len(value) <= TEXT_LIMIT or not value.isprintable():
                return f"Use {KIND_EXAMPLES[kind]}."
        case _:
            return "This kind of input is not known."
    return None


def tools_used(card: CardSpec) -> tuple[ToolId, ...]:
    """The card's tools, each once, in block order."""
    return tuple(dict.fromkeys(block.tool for block in card.blocks if block.tool is not None))


def write_tools_used(tools: Iterable[str | None]) -> tuple[ToolRule, ...]:
    """The write rules among tool ids, each once, in the order given. Unknown ids and None are
    skipped."""
    rules = (RULES.get(tool) for tool in dict.fromkeys(tool for tool in tools if tool))
    return tuple(rule for rule in rules if rule is not None and rule.kind == "write")


def card_bindings(card: CardSpec, values: Mapping[str, str]) -> Mapping[str, Binding]:
    """Where each of the card's write tools lands, from the tool rules and the card's values.

    Raises ValueError when the card cannot name a target. The builder checks values by kind
    before a run is made, so this is a second line of defence, not the first.
    """
    bindings: dict[str, Binding] = {}
    for rule in write_tools_used(tools_used(card)):
        assert rule.target_input and rule.connector and rule.operation and rule.target_key
        names = [i.name for i in card.inputs if i.kind == rule.target_input]
        if len(names) != 1:
            raise ValueError(f"{card.name} needs exactly one {rule.target_input} input")
        value = values.get(names[0])
        if value is None or check_value(rule.target_input, value) is not None:
            raise ValueError(f"{card.name} has no valid value for {names[0]}")
        bindings[rule.id] = Binding(rule.connector, rule.operation, {rule.target_key: value})
    return bindings


def approvers_needed(cards: Iterable[CardSpec], requested: int = 1) -> int:
    """Approvers one run needs: the most any write tool on its cards needs, and never fewer than
    the rules' minimum, at least 1 and at most 2."""
    needed = max(1, requested)
    for card in cards:
        for rule in write_tools_used(tools_used(card)):
            needed = max(needed, rule.min_approvers or 1)
    return min(MAX_APPROVERS, needed)


def cards_policy(cards: Iterable[CardSpec], requested: int = 1) -> ApprovalPolicy:
    count = approvers_needed(cards, requested)
    return ApprovalPolicy(
        tuple(ApprovalStep(label, AnyApprover()) for label in APPROVER_LABELS[:count])
    )


@dataclass(frozen=True)
class CardIntent:
    card_id: str
    intent: ProposedIntent


@dataclass(frozen=True)
class ReviewedCards:
    intents: tuple[CardIntent, ...]


def _fields_problem(tool: str, fields: Mapping[str, object]) -> str | None:
    """Why fields are not the tool's argument shape, or None when they are."""
    match tool:
        case "jira.create_ticket":
            if set(fields) != {"title", "body"}:
                return "its fields are not exactly a title and a body"
            title, body = fields["title"], fields["body"]
            if not isinstance(title, str) or not isinstance(body, str):
                return "its title or body is not text"
            if not title.strip() or len(title) > TITLE_LIMIT:
                return f"its title is empty or longer than {TITLE_LIMIT} characters"
            if len(body) > BODY_LIMIT:
                return f"its body is longer than {BODY_LIMIT} characters"
            return None
        case _:
            return "the platform has no rule for its fields"


def review_cards(task: CardsTask, proposed: Sequence[ProposedIntentIn]) -> ReviewedCards | Unusable:
    """Reads the agents' proposals against the cards the run was given.

    The agents' words are untrusted input (ADR 0008), so nothing is kept until it fits: each
    proposal names a card in the run, is a write tool that card's blocks use, and has exactly
    the tool's fields. Where the write lands is not read from here at all. It comes from the
    card's binding.
    """
    if len(proposed) > MAX_PROPOSED:
        return Unusable(
            f"The agents proposed {len(proposed)} actions, and {MAX_PROPOSED} is the most"
        )
    cards = {run.card.id: run.card for run in task.agents}
    reviewed: list[CardIntent] = []
    for item in proposed:
        card = None if item.subject is None else cards.get(item.subject)
        if card is None:
            return Unusable("The agents proposed an action for an agent that is not in this run")
        rule = RULES.get(item.kind)
        if rule is None or rule.kind != "write" or item.kind not in tools_used(card):
            return Unusable(f"{card.name} proposed an action its card does not allow")
        problem = _fields_problem(item.kind, item.fields)
        if problem is not None:
            return Unusable(f"{card.name} proposed a {rule.name.lower()} but {problem}")
        reviewed.append(
            CardIntent(card.id, ProposedIntent(item.kind, dict(item.fields), item.reason))
        )
    return ReviewedCards(tuple(reviewed))


def bind_cards(task: CardsTask, reviewed: ReviewedCards) -> tuple[WriteAction, ...] | UnboundIntent:
    """Binds each proposal with its own card's bindings, in the order proposed, so two cards can
    write to two projects."""
    by_card = {run.card.id: run.bindings for run in task.agents}
    actions: list[WriteAction] = []
    unbound: list[str] = []
    for item in reviewed.intents:
        match bind([item.intent], by_card[item.card_id]):
            case UnboundIntent(kinds):
                unbound.extend(kind for kind in kinds if kind not in unbound)
            case bound:
                actions.extend(bound)
    return UnboundIntent(tuple(unbound)) if unbound else tuple(actions)


def read_projects(task: CardsTask) -> frozenset[str]:
    """The Jira projects the run's agents may read: the jira_project values of its cards."""
    return frozenset(
        run.values[item.name]
        for run in task.agents
        for item in run.card.inputs
        if item.kind == "jira_project" and item.name in run.values
    )
