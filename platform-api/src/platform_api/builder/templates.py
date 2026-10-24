import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from platform_api.orchestration import AnyApprover, ApprovalPolicy, ApprovalStep, Binding
from platform_api.wire import RepoName

TAG_PATTERN = r"^\d+\.\d+\.\d+$"
TICKET_PROJECT_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_repo_name = TypeAdapter(RepoName)


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


RELEASE_CHECK = Template(
    key="release_check",
    name="Release check",
    description="Watch a public GitHub repository and open a ticket when new releases appear.",
    blocks=(
        Block(
            "read_releases",
            "Read GitHub releases",
            "The Release checker reads the repository's releases.",
            "agent",
        ),
        Block(
            "approval_gate",
            "Approval gate",
            "An Approver reviews the proposed ticket in Teams before it is written.",
            "approval",
        ),
        Block(
            "create_ticket",
            "Create Jira ticket",
            "One ticket in the chosen project listing the new releases.",
            "write_action",
        ),
    ),
    params=(
        ParamSpec("repo", "GitHub repository, owner/name", "langchain-ai/langgraph"),
        ParamSpec("tag_pattern", "Regular expression a release tag must match", TAG_PATTERN),
        ParamSpec("ticket_project", "Jira project key", "MOCK"),
        ParamSpec(
            "last_seen_tag",
            "The last release tag already handled, for example 1.2.14. "
            "Leave empty to start from the newest release.",
            "1.2.14",
        ),
    ),
    workflow="release_check",
    tag_pattern=TAG_PATTERN,
    bindings={"create_ticket": BindingSpec("jira", "create_ticket", {"project": "ticket_project"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
    keywords=frozenset(
        {
            "release",
            "releases",
            "github",
            "repository",
            "repo",
            "tag",
            "version",
            "versions",
            "ticket",
            "jira",
        }
    ),
)

SOFTWARE_WATCHLIST = Template(
    key="software_watchlist",
    name="Software watchlist",
    description="Check every watched software for new releases and raise one upgrade ticket for "
    "each that is behind.",
    blocks=(
        Block(
            "read_versions",
            "Read every source",
            "The Release checker reads the newest release of each watched software.",
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
    workflow="release_check",
    tag_pattern=TAG_PATTERN,
    bindings={"create_ticket": BindingSpec("jira", "create_ticket", {"project": "ticket_project"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
    keywords=frozenset(),
    offered=False,
)

TEMPLATES: Mapping[str, Template] = {
    RELEASE_CHECK.key: RELEASE_CHECK,
    SOFTWARE_WATCHLIST.key: SOFTWARE_WATCHLIST,
}

WATCHLIST_NAME = "Software watchlist"
WATCHLIST_INSTRUCTION = (
    "Check the team's watched software for new releases and raise an upgrade ticket for each "
    "one that is behind."
)
WATCHLIST_PARAMS: Mapping[str, str] = {"ticket_project": "MOCK"}
WATCHLIST_LIMIT = 100


@dataclass(frozen=True)
class ValidParams:
    values: Mapping[str, str]


@dataclass(frozen=True)
class ParamErrors:
    errors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UnknownTemplate:
    key: str


@dataclass(frozen=True)
class TemplateNotOffered:
    key: str


def validate_params(template: Template, params: Mapping[str, str]) -> ValidParams | ParamErrors:
    errors: list[tuple[str, str]] = []
    values: dict[str, str] = {}
    known = {spec.name for spec in template.params}
    errors.extend((name, "Unknown parameter") for name in params if name not in known)

    repo = params.get("repo")
    if repo is None:
        errors.append(("repo", "Required. Use owner/name, for example langchain-ai/langgraph"))
    else:
        try:
            values["repo"] = _repo_name.validate_python(repo)
        except ValidationError:
            errors.append(
                (
                    "repo",
                    "Use owner/name, for example langchain-ai/langgraph.",
                )
            )

    project = params.get("ticket_project")
    if project is None:
        errors.append(("ticket_project", "Required. A Jira project key, for example MOCK"))
    elif TICKET_PROJECT_PATTERN.match(project) is None:
        errors.append(
            (
                "ticket_project",
                "Use 1 to 10 capital letters or digits, starting with a letter, for example MOCK",
            )
        )
    else:
        values["ticket_project"] = project

    if params.get("tag_pattern", template.tag_pattern) != template.tag_pattern:
        errors.append(("tag_pattern", f"Only {template.tag_pattern} is allowed"))
    values["tag_pattern"] = template.tag_pattern

    last_seen = params.get("last_seen_tag")
    if last_seen:
        if VERSION_PATTERN.match(last_seen) is None:
            errors.append(("last_seen_tag", "Use a plain version such as 1.2.14"))
        else:
            values["last_seen_tag"] = last_seen

    if errors:
        return ParamErrors(tuple(errors))
    return ValidParams(values)


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
