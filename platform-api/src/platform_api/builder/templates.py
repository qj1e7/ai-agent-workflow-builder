import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from platform_api.orchestration import AnyApprover, ApprovalPolicy, ApprovalStep, Binding

TAG_PATTERN = r"^[vV]?\d+\.\d+\.\d+$"
"""A plain version number, with or without one v in front, such as 1.2.14 or v2.14.2. The
Agent API takes only patterns from its fixed list, and this is one of them."""


@dataclass(frozen=True)
class Block:
    key: str
    name: str
    description: str
    kind: Literal["agent", "approval", "write_action"]


@dataclass(frozen=True)
class ParamSpec:
    name: str
    description: str
    example: str


@dataclass(frozen=True)
class BindingSpec:
    connector: str
    operation: str
    target_from_params: Mapping[str, str]

    def bind(self, params: Mapping[str, str]) -> Binding:
        return Binding(
            self.connector,
            self.operation,
            {key: params[name] for key, name in self.target_from_params.items()},
        )


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    blocks: tuple[Block, ...]
    params: tuple[ParamSpec, ...]
    workflow: str
    tag_pattern: str
    bindings: Mapping[str, BindingSpec]
    approval_policy: ApprovalPolicy
    keywords: frozenset[str]
    offered: bool = True
    """False when another page owns this template's use cases. The Builder lists it, because
    the live view draws a run from its template's blocks, but never suggests or makes one."""

    def bindings_for(self, params: Mapping[str, str]) -> Mapping[str, Binding]:
        return {kind: spec.bind(params) for kind, spec in self.bindings.items()}


SOFTWARE_WATCHLIST = Template(
    key="software_watchlist",
    name="Software watchlist",
    description="Check every watched software for new releases and raise one upgrade ticket for "
    "each that is behind.",
    blocks=(
        Block(
            "read_versions",
            "Read every source",
            "The Version checker reads the newest release of each watched software.",
            "agent",
        ),
        Block(
            "approval_gate",
            "Approval gate",
            "An Approver reviews all of the check's tickets in Teams with one decision.",
            "approval",
        ),
        Block(
            "create_tickets",
            "Create Jira tickets",
            "One upgrade ticket for each software that is behind.",
            "write_action",
        ),
    ),
    params=(ParamSpec("ticket_project", "Jira project key", "MOCK"),),
    workflow="run",
    tag_pattern=TAG_PATTERN,
    bindings={"create_ticket": BindingSpec("jira", "create_ticket", {"project": "ticket_project"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
    keywords=frozenset(),
    offered=False,
)

AGENT_CARDS = Template(
    key="agent_cards",
    name="Agents",
    description="Agents the Planner brings in, each described by an agent card.",
    blocks=(),
    params=(),
    workflow="run",
    tag_pattern=TAG_PATTERN,
    bindings={},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
    keywords=frozenset(),
    offered=False,
)
"""Use cases made on the Builder page from agent cards. They have no blocks of their own: each
run's line and its bindings come from its cards, and its approval steps from the tool rules
(ADR 0023), so nothing here is read for them. They run the same n8n workflow."""

TEMPLATES: Mapping[str, Template] = {
    SOFTWARE_WATCHLIST.key: SOFTWARE_WATCHLIST,
    AGENT_CARDS.key: AGENT_CARDS,
}

WATCHLIST_NAME = "Software watchlist"
WATCHLIST_INSTRUCTION = (
    "Check the team's watched software for new releases and raise an upgrade ticket for each "
    "one that is behind."
)
WATCHLIST_PROJECT = "MOCK"
"""The practice Jira's project. A deploy names another with WATCHLIST_JIRA_PROJECT (ADR 0035)."""
WATCHLIST_LIMIT = 100


_WORD = re.compile(r"[a-z0-9]+")


def suggest_template(text: str) -> tuple[Template | None, list[str]]:
    words = list(dict.fromkeys(_WORD.findall(text.lower())))
    best: Template | None = None
    best_terms: list[str] = []
    all_terms: set[str] = set()
    for template in TEMPLATES.values():
        if not template.offered:
            continue
        terms = [word for word in words if word in template.keywords]
        all_terms.update(terms)
        if len(terms) >= 2 and len(terms) > len(best_terms):
            best, best_terms = template, terms
    if best is not None:
        return best, best_terms
    return None, [word for word in words if word in all_terms]
