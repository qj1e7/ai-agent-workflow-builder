from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

from platform_api.builder.templates import TAG_PATTERN
from platform_api.orchestration import (
    AT_PATTERN,
    Day,
    InputKind,
    RowKind,
    RowState,
    Status,
    ToolId,
    ToolKind,
)
from platform_api.shared import ApprovalId, RunId, SoftwareId, UserId
from platform_api.wire import RepoName, WireModel
from platform_api.wire import RunState as RunStateName

type BlockKind = Literal["agent", "approval", "write_action"]


class BlockView(WireModel):
    key: str
    name: str
    description: str
    kind: BlockKind


class ParamSpec(WireModel):
    name: str
    description: str
    example: str


class TemplateView(WireModel):
    key: str
    name: str
    description: str
    blocks: list[BlockView]
    params: list[ParamSpec]


class TemplateList(WireModel):
    templates: list[TemplateView]


class CreateUseCase(WireModel):
    template: str
    name: str
    instruction: str
    params: dict[str, str]


class UseCaseCreated(WireModel):
    use_case_id: str
    version: int


class UseCaseAgentView(WireModel):
    card_id: str
    card_version: int
    name: str
    values: dict[str, str]


class UseCaseView(WireModel):
    use_case_id: str
    version: int
    template: str
    name: str
    instruction: str
    params: dict[str, str]
    owner: UserId
    created_at: datetime
    plan: list[BlockView] = Field(
        description="The blocks a run of this use case draws, in order. A template use case "
        "has its template's blocks. An agent use case has one agent block for each agent, "
        "then the approval gate and one write action for each kind of write."
    )
    agents: list[UseCaseAgentView] = Field(
        description="The agents of an agent use case, with the values they run with. "
        "Empty for a template use case."
    )


class UseCaseList(WireModel):
    use_cases: list[UseCaseView]


class SuggestIn(WireModel):
    text: str


class SuggestOut(WireModel):
    template: TemplateView | None
    matched_terms: list[str]


class RunStarted(WireModel):
    run_id: RunId
    state: Literal["pending"] = "pending"
    events_url: str


type SoftwareName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
type Version = Annotated[str, Field(pattern=TAG_PATTERN)]


class AddSoftware(WireModel):
    name: SoftwareName
    repo: RepoName
    our_version: Version | None = Field(
        default=None,
        description="The version the team runs now, such as 1.2.14. Leave it out to take the "
        "newest release at the first check as ours.",
    )


class SourceView(WireModel):
    kind: Literal["github"]
    ref: str
    url: str


type VersionSourceKind = Literal["given", "first_check", "ticket_done"]


class VersionSourceView(WireModel):
    kind: VersionSourceKind
    at: datetime
    ticket: str | None


class WatchedSoftwareView(WireModel):
    id: SoftwareId
    name: str
    source: SourceView
    our_version: str | None
    our_version_source: VersionSourceView | None
    newest_version: str | None
    checked_at: datetime | None
    status: Status
    problem: str | None
    open_ticket: str | None
    approval_id: ApprovalId | None
    added_by: UserId
    added_at: datetime


class LastCheckView(WireModel):
    run_id: RunId
    state: RunStateName
    started_at: datetime


type ClockTime = Annotated[str, Field(pattern=AT_PATTERN, examples=["09:00"])]


class ScheduleIn(WireModel):
    day: Day
    at: ClockTime = Field(description="Time of day in Singapore, HH:MM on a 5-minute step.")


class ScheduleView(WireModel):
    day: Day
    at: ClockTime
    time_zone: str
    owner: UserId = Field(description="The schedule owner. Only another Approver can approve.")
    owner_name: str
    saved_at: datetime
    next_at: datetime = Field(description="The next time a check starts.")


class WatchlistView(WireModel):
    use_case_id: str
    version: int
    ticket_project: str
    software: list[WatchedSoftwareView] = Field(
        description="Rows that need a person first: cannot check, behind, awaiting approval, "
        "ticket open, not checked; then up to date. Rows with one status sort by name."
    )
    last_check: LastCheckView | None
    schedule: ScheduleView | None = Field(description="Null when the schedule is turned off.")


class WatchlistOut(WireModel):
    watchlist: WatchlistView | None


class ToolView(WireModel):
    id: ToolId
    kind: ToolKind
    name: str
    description: str
    target_input: InputKind | None = Field(
        description="For a write, the kind of the agent's one input that says where it writes."
    )
    min_approvers: int | None = Field(description="For a write, the fewest Approvers it needs.")


class ToolList(WireModel):
    tools: list[ToolView]


class CardInput(WireModel):
    name: str
    kind: str = Field(description="github_repo, jira_project or text.")
    what: str = ""
    example: str = ""


class CardBlock(WireModel):
    say: str
    tool: str | None = Field(default=None, description="A tool id from GET /tools, or null.")


class CardApprovalView(WireModel):
    tool: str
    approvers: int


class CardDefinition(WireModel):
    """What an Operator or the Planner writes. Nothing here is trusted until it is checked."""

    name: str
    purpose: str
    good_for: list[str] = Field(default_factory=list[str])
    inputs: list[CardInput] = Field(default_factory=list[CardInput])
    blocks: list[CardBlock] = Field(default_factory=list[CardBlock])
    approvals: list[CardApprovalView] = Field(
        default_factory=list[CardApprovalView],
        description="Approvers asked for each write tool. The platform raises them to the "
        "tool's minimum and drops tools the blocks do not use.",
    )


class CardProblem(WireModel):
    field: str | None = Field(description='For example "blocks.2.tool" or "inputs".')
    message: str


class CardChecked(WireModel):
    card: CardDefinition = Field(description="The definition cleaned up, as it would be saved.")
    approvals: list[CardApprovalView] = Field(
        description="The approvals that apply: one for each write tool the blocks use."
    )
    problems: list[CardProblem]


class CardRefused(WireModel):
    problems: list[CardProblem]


class CardInputView(WireModel):
    name: str
    kind: InputKind
    what: str
    example: str


class CardBlockView(WireModel):
    say: str
    tool: ToolId | None


class CardView(WireModel):
    card_id: str
    version: int
    starter: bool
    owner: UserId
    created_at: datetime
    name: str
    purpose: str
    good_for: list[str]
    inputs: list[CardInputView]
    blocks: list[CardBlockView]
    approvals: list[CardApprovalView]
    tools: list[ToolId] = Field(description="The tools the blocks use, each once, in order.")


class CardList(WireModel):
    cards: list[CardView]


class PlanIn(WireModel):
    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class PlannedAgent(WireModel):
    card: CardView
    part: str
    values: dict[str, str] = Field(description="Values the Planner took from the task.")
    missing: list[str] = Field(description="Names of inputs that still need a value.")


class MissingTool(WireModel):
    need: str
    why: str


class UseSaved(WireModel):
    decision: Literal["use_one", "use_several"]
    agents: list[PlannedAgent]
    reason: str
    questions: list[str]


class NewAgent(WireModel):
    decision: Literal["new_agent"] = "new_agent"
    draft: CardDefinition
    approvals: list[CardApprovalView]
    problems: list[CardProblem]
    reason: str
    missing_tools: list[MissingTool]
    questions: list[str]


class CannotDo(WireModel):
    decision: Literal["cannot_do"] = "cannot_do"
    reason: str
    missing_tools: list[MissingTool]


class ModelTrouble(WireModel):
    decision: Literal["model_problem"] = "model_problem"
    message: str


type PlanOut = Annotated[
    UseSaved | NewAgent | CannotDo | ModelTrouble, Field(discriminator="decision")
]


class AgentChoice(WireModel):
    card_id: str
    values: dict[str, str]


class CreateAgentUseCase(WireModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    agents: Annotated[list[AgentChoice], Field(min_length=1, max_length=3)]


NUL_IN_TEXT = "This text holds a NUL character (\\u0000). Remove it."


class UnderstandIn(WireModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @field_validator("text")
    @classmethod
    def _no_nul(cls, text: str) -> str:
        if "\x00" in text:
            raise PydanticCustomError("nul_character", NUL_IN_TEXT)
        return text


class UnderstoodRowView(WireModel):
    kind: RowKind = Field(
        description="schedule: when it runs. look_for: what to look for. do: what to do with "
        "it. where: where the result goes."
    )
    text: str = Field(
        description="What the Planner read, in plain words. Empty when missing, and can be empty "
        "when cant_do."
    )
    state: RowState = Field(
        description="understood: from the task's words. changed: the Planner read something "
        "into the words, and the note says what the task said. missing: the task does not say. "
        "cant_do: no tool does it yet, and the note says why."
    )
    note: str | None


class UnderstoodRows(WireModel):
    answer: Literal["rows"] = "rows"
    rows: list[UnderstoodRowView] = Field(
        description="One schedule row, then at least one row for what to look for, what to do "
        "and where, in that order. At most 8."
    )


class WatchlistRedirect(WireModel):
    answer: Literal["watchlist"] = "watchlist"
    word: str = Field(description="The word in the task that made the Planner think so.")
    software: str | None = Field(description="The software the task names, as it wrote it.")
    note: str = Field(description="What the Planner says, in plain words.")


class StarterView(WireModel):
    name: str
    what: str
    task: str | None = Field(
        description="The task to start New workflow with. Null when the starter opens a page."
    )
    opens: Literal["software_watchlist"] | None = Field(
        description="The page this starter opens instead of a task."
    )


class Starters(WireModel):
    answer: Literal["starters"] = "starters"
    message: str = Field(description="Why the Planner could not read the task, in plain words.")
    starters: list[StarterView]


type UnderstandOut = Annotated[
    UnderstoodRows | WatchlistRedirect | Starters, Field(discriminator="answer")
]
