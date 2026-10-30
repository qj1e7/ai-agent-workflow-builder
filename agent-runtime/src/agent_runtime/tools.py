"""The tools an agent card can use. Four, all built and tested by us. A card names tools by id,
and a running agent is offered exactly the tools its card names (ADR 0023)."""

import re
from datetime import date
from typing import Annotated, Any, Final, Literal, cast, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from agent_runtime.contract import (
    JIRA_PROJECT_PATTERN,
    REPO_PATTERN,
    InputKind,
    JiraProject,
    RepoName,
    ToolId,
    ToolKind,
    ToolList,
    ToolSpec,
)

JIRA_KEY_PATTERN = r"^[A-Z][A-Z0-9]{0,9}-[0-9]{1,9}$"
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TEXT_INPUT_MAX = 200
TITLE_MAX = 200
BODY_MAX = 5000

type JiraKey = Annotated[str, Field(pattern=JIRA_KEY_PATTERN)]


def _real_date(text: str) -> str:
    date.fromisoformat(text)
    return text


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadReleasesArguments(_Arguments):
    repo: RepoName = Field(
        description="The repository, as owner/name, such as langchain-ai/langgraph."
    )


class JiraSearchArguments(_Arguments):
    project: JiraProject = Field(description="The Jira project key, such as MOCK.")
    text: Annotated[str, StringConstraints(max_length=200)] | None = Field(
        default=None, description="Words to look for in the title or body of a ticket."
    )
    status: Literal["To Do", "Done"] | None = Field(
        default=None, description="Only tickets in this status."
    )
    done_since: Annotated[str, Field(pattern=DATE_PATTERN), AfterValidator(_real_date)] | None = (
        Field(default=None, description="Only tickets finished on or after this date, YYYY-MM-DD.")
    )


class JiraReadArguments(_Arguments):
    key: JiraKey = Field(description="The ticket key, such as MOCK-7.")


class JiraCreateArguments(_Arguments):
    title: Annotated[str, StringConstraints(min_length=1, max_length=TITLE_MAX)] = Field(
        description="One line saying what the ticket is for."
    )
    body: Annotated[str, StringConstraints(max_length=BODY_MAX)] = Field(
        description="The details. Plain text."
    )


def _plain(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema the model sees: references inlined, no titles, and an optional argument is
    simply left out of `required` instead of being typed as a choice with null."""
    defs: dict[str, dict[str, Any]] = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in cast(list[Any], node)]
        if not isinstance(node, dict):
            return node
        fields = cast(dict[str, Any], node)
        if "$ref" in fields:
            target = defs[str(fields["$ref"]).rsplit("/", 1)[-1]]
            return walk({**target, **{k: v for k, v in fields.items() if k != "$ref"}})
        options = fields.get("anyOf")
        if isinstance(options, list):
            kept = [o for o in cast(list[Any], options) if o != {"type": "null"}]
            if len(kept) == 1:
                rest = {k: v for k, v in fields.items() if k not in {"anyOf", "default"}}
                return walk({**cast(dict[str, Any], kept[0]), **rest})
        out: dict[str, Any] = {}
        for key, value in fields.items():
            if key == "title" and isinstance(value, str):
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: walk(prop) for name, prop in cast(dict[str, Any], value).items()}
            else:
                out[key] = walk(value)
        return out

    return cast(dict[str, Any], walk(schema))


class Tool:
    def __init__(
        self,
        id: ToolId,
        kind: ToolKind,
        name: str,
        description: str,
        arguments: type[_Arguments],
        target_kind: InputKind | None = None,
    ) -> None:
        self.id: Final = id
        self.kind: Final = kind
        self.name: Final = name
        self.description: Final = description
        self.arguments: Final = arguments
        self.target_kind: Final = target_kind

    @property
    def model_name(self) -> str:
        """Anthropic tool names allow only letters, digits, - and _, so a dot becomes _."""
        return self.id.replace(".", "_")

    @property
    def input_schema(self) -> dict[str, Any]:
        return _plain(self.arguments.model_json_schema())

    def parse(self, raw: object) -> _Arguments:
        """Raises pydantic.ValidationError when the model's arguments do not fit."""
        return self.arguments.model_validate(raw)


TOOLS: Final = (
    Tool(
        "github.read_releases",
        "read",
        "Read GitHub releases",
        "Read the newest releases of a public GitHub repository: tag, name, date and notes.",
        ReadReleasesArguments,
    ),
    Tool(
        "jira.search",
        "read",
        "Search Jira",
        "Find Jira tickets in one project. Filters are optional: words in the title or body, "
        "status, and finished on or after a date.",
        JiraSearchArguments,
    ),
    Tool(
        "jira.read_ticket",
        "read",
        "Read a Jira ticket",
        "Read one Jira ticket with its body.",
        JiraReadArguments,
    ),
    Tool(
        "jira.create_ticket",
        "write",
        "Create a Jira ticket",
        "Propose a new Jira ticket. Nothing is created until an Approver approves it in Teams. "
        "The platform puts it in the Jira project saved on the agent, so you do not name one.",
        JiraCreateArguments,
        target_kind="jira_project",
    ),
)
TOOL_IDS: Final = frozenset(get_args(ToolId.__value__))
BY_ID: Final = {tool.id: tool for tool in TOOLS}
BY_MODEL_NAME: Final = {tool.model_name: tool for tool in TOOLS}


def tool_list() -> ToolList:
    return ToolList(
        tools=[
            ToolSpec(
                id=tool.id,
                kind=tool.kind,
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in TOOLS
        ]
    )


def tools_text() -> str:
    return "\n".join(f"- {tool.id} ({tool.kind}): {tool.description}" for tool in TOOLS)


_REPO = re.compile(REPO_PATTERN)
_PROJECT = re.compile(JIRA_PROJECT_PATTERN)
_REPO_VALUE = TypeAdapter(RepoName)


def value_problem(kind: InputKind, value: str) -> str | None:
    """Why a value does not fit its input kind, or None when it fits."""
    match kind:
        case "github_repo":
            try:
                _REPO_VALUE.validate_python(value)
            except ValueError:
                return "is not a GitHub repository written as owner/name"
        case "jira_project":
            if not _PROJECT.fullmatch(value):
                return "is not a Jira project key such as MOCK"
        case "text":
            if not 1 <= len(value) <= TEXT_INPUT_MAX or "\n" in value or "\r" in value:
                return f"is not one line of 1 to {TEXT_INPUT_MAX} characters"
    return None
