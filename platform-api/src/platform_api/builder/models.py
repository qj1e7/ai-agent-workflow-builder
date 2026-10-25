from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from platform_api.builder.templates import TAG_PATTERN
from platform_api.orchestration import AT_PATTERN, Day, InputKind, Status, ToolId, ToolKind
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


class ApprovalView(WireModel):
    tool: str
    approvers: int


class CardDefinition(WireModel):
    """What an Operator or the Room lead writes. Nothing here is trusted until it is checked."""

    name: str
    purpose: str
    good_for: list[str] = Field(default_factory=list[str])
    inputs: list[CardInput] = Field(default_factory=list[CardInput])
    blocks: list[CardBlock] = Field(default_factory=list[CardBlock])
    approvals: list[ApprovalView] = Field(
        default_factory=list[ApprovalView],
        description="Approvers asked for each write tool. The platform raises them to the "
        "tool's minimum and drops tools the blocks do not use.",
    )


class CardProblem(WireModel):
    field: str | None = Field(description='For example "blocks.2.tool" or "inputs".')
    message: str


class CardChecked(WireModel):
    card: CardDefinition = Field(description="The definition cleaned up, as it would be saved.")
    approvals: list[ApprovalView] = Field(
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
    approvals: list[ApprovalView]
    tools: list[ToolId] = Field(description="The tools the blocks use, each once, in order.")


class CardList(WireModel):
    cards: list[CardView]


class PlanIn(WireModel):
    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class PlannedAgent(WireModel):
    card: CardView
    part: str
    values: dict[str, str] = Field(description="Values the Room lead took from the task.")
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
    approvals: list[ApprovalView]
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
