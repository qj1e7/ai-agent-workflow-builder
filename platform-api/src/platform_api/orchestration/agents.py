from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Final, Literal, Protocol, Self

import httpx
from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from platform_api.monitoring import AgentEvent, CauseSystem, FailureKind
from platform_api.orchestration.schedule import AT_PATTERN, Day
from platform_api.wire import (
    FoundBy,
    MavenCoordinate,
    NpmPackage,
    RepoName,
    SourceKind,
    WireModel,
)


class GithubSource(WireModel):
    kind: Literal["github"] = "github"
    ref: RepoName


class MavenSource(WireModel):
    kind: Literal["maven"] = "maven"
    ref: MavenCoordinate


class NpmSource(WireModel):
    kind: Literal["npm"] = "npm"
    ref: NpmPackage


type SoftwareSourceIn = Annotated[
    GithubSource | MavenSource | NpmSource, Field(discriminator="kind")
]


def source_in(kind: SourceKind, ref: str) -> GithubSource | MavenSource | NpmSource:
    """The source as the Agent API names it, from the kind and ref the builder saved."""
    match kind:
        case "github":
            return GithubSource(ref=ref)
        case "maven":
            return MavenSource(ref=ref)
        case "npm":
            return NpmSource(ref=ref)


class SoftwareToCheck(WireModel):
    id: str
    name: str
    source: SoftwareSourceIn
    our_version: str | None
    open_ticket: str | None = None
    awaiting_approval: bool = False
    from_first_check: bool = False


class WatchlistInputs(WireModel):
    kind: Literal["watchlist"] = "watchlist"
    tag_pattern: str
    software: list[SoftwareToCheck]


type CardToolId = Literal[
    "github.read_releases",
    "jira.search",
    "jira.read_ticket",
    "confluence.read_page",
    "jira.create_ticket",
]
"""The tools an agent card can use. The runtime gives each one to the model."""
type ToolId = Literal[
    "github.read_releases",
    "jira.search",
    "jira.read_ticket",
    "confluence.read_page",
    "jira.create_ticket",
    "packages.read_versions",
    "packages.find_vulnerabilities",
]
"""Every tool, including the two only the Software watchlist check runs (ADR 0025). No card and
no model can use those two."""
type ToolKind = Literal["read", "write"]
type InputKind = Literal["github_repo", "jira_project", "text"]


class CardInput(WireModel):
    name: str
    kind: InputKind
    what: str = ""
    example: str = ""


class CardBlock(WireModel):
    say: str
    tool: CardToolId | None


class CardSpec(WireModel):
    id: str
    version: int
    name: str
    purpose: str
    inputs: list[CardInput]
    blocks: list[CardBlock]


class CardToRun(WireModel):
    card: CardSpec
    values: dict[str, str]


class CardsInputs(WireModel):
    kind: Literal["cards"] = "cards"
    agents: list[CardToRun]


type TaskInputs = Annotated[WatchlistInputs | CardsInputs, Field(discriminator="kind")]


class CarryForward(WireModel):
    last_run_on: date | None = None


class Callback(WireModel):
    url: str = Field(
        description="Where the agent posts each event. It names only the run and the task."
    )
    token: str = Field(
        description="Sent back as the X-Callback-Token header, never in the URL. The handler "
        "must compare it in constant time, bind it to this run_id and task_id, and give it "
        "an expiry."
    )


type ModelStyle = Literal["anthropic", "openai"]


class ModelAccess(WireModel):
    style: ModelStyle
    base_url: str
    model: str
    api_key: str = Field(repr=False)


class TaskRequest(WireModel):
    task_id: str
    run_id: str
    instruction: str
    inputs: TaskInputs
    carry_forward: CarryForward
    time_zone: str
    callback: Callback
    model: ModelAccess | None = None


class ProposedIntentIn(WireModel):
    kind: str
    fields: dict[str, Any]
    reason: str
    subject: str | None = None


type FindingState = Literal[
    "behind", "up_to_date", "starting_point", "already_raised", "cant_check"
]


type Severity = Literal["critical", "high", "medium", "low", "unknown"]
type VulnerabilityCheck = Literal["not_checked", "checked", "could_not_check"]


class Vulnerability(WireModel):
    """A known vulnerability in our version, as the Version checker reported it (ADR 0025)."""

    id: str
    severity: Severity
    score: float | None = None
    summary: str = ""
    fixed_in: str | None = None
    reported_by: list[Literal["OSV", "NVD"]]
    url: str


class Finding(WireModel):
    software_id: str
    state: FindingState
    newest: str | None
    new_versions: list[str]
    detail: str
    full_name: RepoName | None = None
    not_found: bool = False
    vulnerability_check: VulnerabilityCheck = "not_checked"
    vulnerabilities: list[Vulnerability] = Field(default_factory=list[Vulnerability])
    vulnerabilities_complete: bool = True
    """False when OSV listed more than the check read, so there are more than these."""


class TaskOutput(WireModel):
    summary: str
    new_tags: list[str]
    proposed: list[ProposedIntentIn]
    carry_forward: CarryForward
    findings: list[Finding] = Field(default_factory=list[Finding])


class TaskError(WireModel):
    type: str
    message: str
    retryable: bool


class TaskFinished(WireModel):
    task_id: str
    status: Literal["finished"] = "finished"
    output: TaskOutput
    events: list[AgentEvent]


class TaskFailed(WireModel):
    task_id: str
    status: Literal["failed"] = "failed"
    error: TaskError
    events: list[AgentEvent]
    findings: list[Finding] = Field(default_factory=list[Finding])


type TaskResult = Annotated[TaskFinished | TaskFailed, Field(discriminator="status")]

task_result_adapter: TypeAdapter[TaskResult] = TypeAdapter(TaskResult)


class ConnectRequest(WireModel):
    base_url: str
    api_key: str = Field(repr=False)


class FoundModel(WireModel):
    id: str
    display: str
    suggested: bool


class Connected(WireModel):
    status: Literal["connected"] = "connected"
    style: ModelStyle
    base_url: str
    models: list[FoundModel]


type ProblemReason = Literal[
    "address_not_allowed",
    "unreachable",
    "key_refused",
    "not_a_model_api",
    "no_text_models",
    "model_not_found",
    "too_slow",
    "unusable_answer",
    "failed",
]


class ModelProblem(WireModel):
    status: Literal["problem"] = "problem"
    reason: ProblemReason
    message: str


type ConnectResult = Annotated[Connected | ModelProblem, Field(discriminator="status")]

connect_result_adapter: TypeAdapter[ConnectResult] = TypeAdapter(ConnectResult)


class ModelTestPassed(WireModel):
    status: Literal["passed"] = "passed"
    seconds: float
    text: str


type ModelTestResult = Annotated[ModelTestPassed | ModelProblem, Field(discriminator="status")]

model_test_result_adapter: TypeAdapter[ModelTestResult] = TypeAdapter(ModelTestResult)


class GitHubWorking(WireModel):
    status: Literal["working"] = "working"
    using_token: bool
    expires_at: datetime | None = None


class GitHubProblem(WireModel):
    status: Literal["problem"] = "problem"
    reason: Literal["token_refused", "unreachable", "unexpected_answer"]
    message: str


type GitHubCheckResult = Annotated[GitHubWorking | GitHubProblem, Field(discriminator="status")]

github_check_result_adapter: TypeAdapter[GitHubCheckResult] = TypeAdapter(GitHubCheckResult)


class ToolSpec(WireModel):
    id: CardToolId
    kind: ToolKind
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolList(WireModel):
    tools: list[ToolSpec]


class CapabilitySpec(WireModel):
    id: str
    plain: str
    kind: Literal["read", "write", "notify", "none"]
    system: str | None
    state: Literal["ready", "planned", "unsupported"]
    cant: str | None
    why: str | None
    connection: Literal["jira", "github", "teams", "confluence"] | None
    needs_model: bool
    platform: bool
    focus: bool
    tools: list[ToolId]
    short: str | None = None
    instead: str | None = None


class ExampleSpec(WireModel):
    text: str
    kind: Literal["automate", "monitor", "learn"]
    needs: list[str]


class CapabilityList(WireModel):
    capabilities: list[CapabilitySpec]
    examples: list[ExampleSpec]


class DraftRequest(WireModel):
    task: str
    model: ModelAccess


class DraftInput(WireModel):
    name: str
    kind: str
    what: str = ""
    example: str = ""


class DraftBlock(WireModel):
    say: str
    tool: str | None


class DraftApproval(WireModel):
    tool: str
    approvers: int
    why: str = ""


class MissingTool(WireModel):
    need: str
    why: str


class CardDraft(WireModel):
    can_do: bool
    why_not: str | None = None
    name: str
    purpose: str
    good_for: list[str] = Field(default_factory=list[str])
    inputs: list[DraftInput] = Field(default_factory=list[DraftInput])
    blocks: list[DraftBlock] = Field(default_factory=list[DraftBlock])
    approvals: list[DraftApproval] = Field(default_factory=list[DraftApproval])
    missing_tools: list[MissingTool] = Field(default_factory=list[MissingTool])
    questions: list[str] = Field(default_factory=list[str])


class Drafted(WireModel):
    status: Literal["drafted"] = "drafted"
    draft: CardDraft


type DraftResult = Annotated[Drafted | ModelProblem, Field(discriminator="status")]

draft_result_adapter: TypeAdapter[DraftResult] = TypeAdapter(DraftResult)


class LibraryInput(WireModel):
    name: str
    kind: InputKind


class LibraryCard(WireModel):
    card_id: str
    name: str
    purpose: str
    good_for: list[str] = Field(default_factory=list[str])
    inputs: list[LibraryInput] = Field(default_factory=list[LibraryInput])
    tools: list[CardToolId] = Field(default_factory=list[CardToolId])


class ChooseRequest(WireModel):
    task: str
    library: list[LibraryCard]
    model: ModelAccess


type ChoiceDecision = Literal["use_one", "use_several", "new_agent", "cannot_do"]


class ChosenAgent(WireModel):
    card_id: str
    part: str
    values: dict[str, str] = Field(default_factory=dict[str, str])


class Choice(WireModel):
    decision: ChoiceDecision
    agents: list[ChosenAgent] = Field(default_factory=list[ChosenAgent])
    new_agent: str | None = None
    reason: str
    questions: list[str] = Field(default_factory=list[str])


class Chosen(WireModel):
    status: Literal["chosen"] = "chosen"
    choice: Choice


type ChooseResult = Annotated[Chosen | ModelProblem, Field(discriminator="status")]

choose_result_adapter: TypeAdapter[ChooseResult] = TypeAdapter(ChooseResult)


type RowKind = Literal["schedule", "look_for", "do", "where"]
type RowState = Literal["understood", "changed", "missing", "cant_do"]
type WatchPart = Literal["schedule", "ticket"]


class UnderstoodRow(WireModel):
    kind: RowKind
    text: str = Field(max_length=200)
    state: RowState
    note: str | None = Field(default=None, max_length=300)


class FindSoftwareRequest(WireModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    tag_pattern: str


class SoftwareMatch(WireModel):
    kind: SourceKind = "github"
    repo: str
    what: str = Field(min_length=1, max_length=120)
    why: str = Field(max_length=300)
    releases: Literal["published", "none"]
    newest: str | None
    found_by: FoundBy = "reviewed_list"
    stars: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _fits_its_kind(self) -> SoftwareMatch:
        """The runtime names a package as its registry does, a project as GitHub does."""
        source_in(self.kind, self.repo)
        return self


class FoundSoftware(WireModel):
    status: Literal["found"] = "found"
    matches: list[SoftwareMatch] = Field(min_length=1, max_length=5)


class SoftwareNotKnown(WireModel):
    status: Literal["not_known"] = "not_known"
    message: str = Field(max_length=300)


class SoftwareNotChecked(WireModel):
    status: Literal["not_checked"] = "not_checked"
    message: str = Field(max_length=300)


type FindSoftwareResult = Annotated[
    FoundSoftware | SoftwareNotKnown | SoftwareNotChecked, Field(discriminator="status")
]

find_software_result_adapter: TypeAdapter[FindSoftwareResult] = TypeAdapter(FindSoftwareResult)


class ReadReleasesRequest(WireModel):
    repo: RepoName
    tag_pattern: str


class ReleaseRead(WireModel):
    tag: str
    name: str | None
    published_at: str | None


class ReleasesRead(WireModel):
    status: Literal["read"] = "read"
    releases: list[ReleaseRead] = Field(max_length=30)


class ReleasesNotRead(WireModel):
    status: Literal["not_read"] = "not_read"
    message: str = Field(max_length=300)
    retryable: bool


type ReadReleasesResult = Annotated[ReleasesRead | ReleasesNotRead, Field(discriminator="status")]

read_releases_result_adapter: TypeAdapter[ReadReleasesResult] = TypeAdapter(ReadReleasesResult)


type FactSection = Literal["watchlist", "workflows", "needs_you"]


NEWEST_VERSION_LIMIT: Final = 100


class WatchedFact(WireModel):
    name: str = Field(max_length=80)
    repo: str = Field(max_length=140)
    our_version: str | None = Field(max_length=40)
    newest_version: str | None = Field(max_length=NEWEST_VERSION_LIMIT)
    state: str = Field(max_length=40)
    checked_at: datetime | None = None
    open_ticket: str | None = Field(default=None, max_length=40)
    awaiting_approval: bool = False
    problem: str | None = Field(default=None, max_length=200)
    our_version_source: Literal["given", "first_check", "ticket_done"] | None = None
    our_version_ticket: str | None = Field(default=None, max_length=40)

    @field_validator("problem", mode="before")
    @classmethod
    def _cut_a_long_problem(cls, value: object) -> object:
        """A GitHub error can run long. It is cut, so one odd message does not drop the section."""
        return value[:200] if isinstance(value, str) else value

    @field_validator("newest_version", mode="before")
    @classmethod
    def _cut_a_long_tag(cls, value: object) -> object:
        """A raw tag such as `@langchain/langgraph-checkpoint-postgres@1.0.0` can run long. It is
        cut at the limit, so one odd tag does not drop the whole watchlist section."""
        return value[:NEWEST_VERSION_LIMIT] if isinstance(value, str) else value


WORKFLOW_FACTS: Final = 50
"""The workflows sent with their state and last run. The names of the rest are sent alone."""
OTHER_WORKFLOWS: Final = 250
"""At the 80-character limit, 250 names are about 21 KB of the question's facts, less than a full
watchlist section. Past it the facts count the names left out, and the Planner says it read only
some."""

type WorkflowName = Annotated[str, StringConstraints(max_length=80)]


class WorkflowFact(WireModel):
    name: WorkflowName
    state: Literal["draft", "on", "paused"]
    last_run: str | None = Field(max_length=40)
    last_run_at: datetime | None


class NeedsYouFact(WireModel):
    approvals: int = Field(ge=0)
    confirmations: int = Field(ge=0)
    stopped: int = Field(ge=0)
    connections: int = Field(ge=0)
    addresses: int = Field(ge=0)
    replies: int = Field(ge=0)
    declined: int = Field(ge=0)
    questions: int = Field(ge=0)
    fixes: int = Field(default=0, ge=0)
    setups: int = Field(default=0, ge=0)
    total: int = Field(ge=0)


class WatchlistScheduleFact(WireModel):
    day: Day
    at: str = Field(pattern=AT_PATTERN)


class PlannerFacts(WireModel):
    watchlist: list[WatchedFact] | None = Field(default=None, max_length=100)
    workflows: list[WorkflowFact] | None = Field(default=None, max_length=WORKFLOW_FACTS)
    # Left out of the payload when None, so a runtime from before them takes the facts while the
    # two services roll out.
    other_workflows: list[WorkflowName] | None = Field(
        default=None, max_length=OTHER_WORKFLOWS, exclude_if=lambda names: names is None
    )
    left_out_workflows: int | None = Field(
        default=None, gt=0, exclude_if=lambda count: count is None
    )
    needs_you: NeedsYouFact | None = None
    watchlist_schedule: WatchlistScheduleFact | None = None
    watchlist_project: str | None = Field(
        default=None, max_length=40, exclude_if=lambda project: project is None
    )


class PreviousTurn(WireModel):
    request: str = Field(max_length=2000)
    software: str | None = Field(default=None, max_length=80)
    answer: str | None = Field(default=None, max_length=600)
    kind: str | None = Field(default=None, max_length=40)


class TurnTrace(WireModel):
    """Where the runtime traces the turn (ADR 0050)."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    chat: str | None = Field(default=None, pattern=r"^[0-9a-f-]{1,36}$")
    person: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


type PlatformReady = Literal["workflows.simulate"]
"""A planned capability the platform turns on where it has what it needs, as Simulation mode
where there is a simulation n8n (ADR 0054)."""


class AnswerRequest(WireModel):
    task: str
    model: ModelAccess
    trace: TurnTrace | None = None
    facts: PlannerFacts | None = None
    previous: PreviousTurn | None = None
    changes_workflows: bool = True
    ready_here: list[PlatformReady] = Field(default_factory=list[PlatformReady])


type CantNeed = Literal["new_tool", "new_system"]


class CantRow(WireModel):
    kind: RowKind
    text: str = Field(max_length=200)
    note: str = Field(max_length=300)
    needs: CantNeed | None = None
    system: str | None = Field(default=None, max_length=40)
    instead: str | None = Field(default=None, max_length=200)
    unsupported: bool = False


class SetupCardAnswer(WireModel):
    kind: Literal["setup_card"] = "setup_card"
    name: str = Field(min_length=1, max_length=60)
    rows: list[UnderstoodRow] = Field(min_length=4, max_length=8)
    also: (
        Annotated[SetupCardAnswer | PartAnswer | CantAnswer, Field(discriminator="kind")] | None
    ) = None


class PartAnswer(WireModel):
    kind: Literal["part"] = "part"
    name: str = Field(min_length=1, max_length=60)
    rows: list[UnderstoodRow] = Field(min_length=4, max_length=8)
    cant: list[CantRow] = Field(min_length=1)


type Alternative = Annotated[SetupCardAnswer | WatchlistAnswer, Field(discriminator="kind")]


class CantAnswer(WireModel):
    kind: Literal["cant"] = "cant"
    cant: list[CantRow] = Field(min_length=1)
    alternative: Alternative | None = None


class WatchlistAnswer(WireModel):
    kind: Literal["watchlist"] = "watchlist"
    word: str = Field(min_length=1, max_length=80)
    software: str | None = Field(default=None, max_length=80)
    also: (
        Annotated[SetupCardAnswer | PartAnswer | CantAnswer, Field(discriminator="kind")] | None
    ) = None
    covers: list[WatchPart] = Field(default_factory=list[WatchPart])


CantAnswer.model_rebuild()
SetupCardAnswer.model_rebuild()


class WhichSoftwareAnswer(WireModel):
    kind: Literal["which_software"] = "which_software"
    word: str = Field(min_length=1, max_length=80)


class RefusedAnswer(WireModel):
    kind: Literal["refused"] = "refused"
    reason: Literal["skip_approval"] = "skip_approval"
    said: str = Field(max_length=200)
    rest: str = Field(max_length=2000)


class CheckWorkflowsAnswer(WireModel):
    kind: Literal["check_workflows"] = "check_workflows"
    workflow_words: str | None = Field(default=None, max_length=80)


class WhyStoppedAnswer(WireModel):
    kind: Literal["why_stopped"] = "why_stopped"
    workflow_words: str | None = Field(default=None, max_length=80)


class NeedsMeAnswer(WireModel):
    kind: Literal["needs_me"] = "needs_me"


class AbilitiesAnswer(WireModel):
    kind: Literal["abilities"] = "abilities"
    how_to_start: bool = False


class QuestionAnswer(WireModel):
    kind: Literal["question"] = "question"
    text: str = Field(min_length=1, max_length=600)
    looked_at: list[FactSection] = Field(max_length=3)
    about_software: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=3
    )


type ReplyForm = Literal["answer", "clarify", "cant"]


class ReplyOffer(WireModel):
    capability: str
    request: str = Field(min_length=1, max_length=2000)


type AboutSection = Literal["watchlist", "workflows"]
ABOUT_LIMIT: Final = 5


class ReplyAbout(WireModel):
    section: AboutSection
    name: str = Field(min_length=1, max_length=80)


class FreeReplyAnswer(WireModel):
    """The model's own reply to a message no other answer fits, checked by the runtime's guard
    before it is sent (ADR 0047)."""

    kind: Literal["reply"] = "reply"
    form: ReplyForm
    text: str = Field(min_length=1, max_length=600)
    choices: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list[str], max_length=4
    )
    offer: ReplyOffer | None = None
    looked_at: list[FactSection] = Field(default_factory=list[FactSection], max_length=3)
    # Left out when empty, so a runtime from before ADR 0049 still parses and re-serializes alike.
    about: list[ReplyAbout] = Field(
        default_factory=list[ReplyAbout],
        max_length=ABOUT_LIMIT,
        exclude_if=lambda about: not about,
    )
    # The one software the request named, which the Portal sends back as previous.software.
    software: str | None = Field(
        default=None, max_length=80, exclude_if=lambda software: software is None
    )

    @model_validator(mode="after")
    def _form_fits(self) -> Self:
        if (self.form == "clarify") != (len(self.choices) >= 2) or (
            self.form != "clarify" and self.choices
        ):
            raise ValueError("Only a clarifying question has choices, 2 to 4 of them")
        if self.offer is not None and self.form != "cant":
            raise ValueError("Only a can't offers something instead")
        return self


class DidntFollowAnswer(WireModel):
    kind: Literal["didnt_follow"] = "didnt_follow"


class _OnOrOff(WireModel):
    workflow_words: str | None = Field(default=None, max_length=80)
    software: str | None = Field(default=None, max_length=80)


class PauseAnswer(_OnOrOff):
    kind: Literal["pause"] = "pause"


class ResumeAnswer(_OnOrOff):
    kind: Literal["resume"] = "resume"


type EditCant = Literal["only_schedule", "how_often"]


class ScheduleChange(WireModel):
    """When a request asks a workflow to run. A part it doesn't name is None, so the saved one
    stays. `weekly` is once a week with no day named, and `hour` an hour with no am or pm."""

    day: Day | None = None
    weekly: bool = False
    at: str | None = Field(default=None, pattern=AT_PATTERN)
    hour: int | None = Field(default=None, ge=1, le=12)
    time_unclear: bool = False

    @model_validator(mode="after")
    def _one_of_each(self) -> Self:
        times = (self.at is not None, self.hour is not None, self.time_unclear)
        if (self.day is not None and self.weekly) or sum(times) > 1:
            raise ValueError("A day or a time is named once")
        return self


class EditAnswer(WireModel):
    kind: Literal["edit"] = "edit"
    workflow_words: str | None = Field(default=None, max_length=80)
    software: str | None = Field(default=None, max_length=80)
    schedule: ScheduleChange | None = None
    cant: EditCant | None = None
    holds_save: bool = False
    leaves_out_days: bool = False

    @model_validator(mode="after")
    def _a_cant_proposes_nothing(self) -> Self:
        if self.cant is not None and (self.schedule is not None or self.holds_save):
            raise ValueError("An edit the chat can't make proposes no schedule")
        if self.leaves_out_days and self.cant != "how_often":
            raise ValueError("Only a schedule it can't hold leaves out days")
        return self


class RemoveSoftwareAnswer(WireModel):
    """Software to take off the Software watchlist, named as the request wrote it, with the
    watchlist's own names for it."""

    kind: Literal["remove_software"] = "remove_software"
    software: str = Field(min_length=1, max_length=80)
    watched_as: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list[str], max_length=100
    )


class ExplainAnswer(WireModel):
    kind: Literal["explain"] = "explain"
    workflow_words: str | None = Field(default=None, max_length=80)


type PlannerAnswer = Annotated[
    SetupCardAnswer
    | PartAnswer
    | CantAnswer
    | WatchlistAnswer
    | WhichSoftwareAnswer
    | RefusedAnswer
    | CheckWorkflowsAnswer
    | WhyStoppedAnswer
    | NeedsMeAnswer
    | AbilitiesAnswer
    | QuestionAnswer
    | EditAnswer
    | PauseAnswer
    | ResumeAnswer
    | RemoveSoftwareAnswer
    | ExplainAnswer
    | FreeReplyAnswer
    | DidntFollowAnswer,
    Field(discriminator="kind"),
]


type PartMark = Literal["will_do", "cant", "question"]
type PartReason = Literal[
    "not_followed",
    "cant_do",
    "ask_on_its_own",
    "one_day",
    "one_time",
    "one_frequency",
    "own_time",
    "skip_approval",
    "with_a_yes",
    "needs_the_rest",
    "how_many_days",
    "only_schedule",
    "how_often",
    "which_software",
]


class RequestPart(WireModel):
    text: str = Field(max_length=200)
    mark: PartMark
    reason: PartReason | None = None
    note: str | None = Field(default=None, max_length=300)
    choices: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list[str])


class Answered(WireModel):
    status: Literal["answered"] = "answered"
    answer: PlannerAnswer
    parts: list[RequestPart] = Field(default_factory=list[RequestPart])


type AnswerResult = Annotated[Answered | ModelProblem, Field(discriminator="status")]

answer_result_adapter: TypeAdapter[AnswerResult] = TypeAdapter(AnswerResult)


class CheckPartRequest(WireModel):
    kind: RowKind
    text: str = Field(min_length=1, max_length=200)


class PartFits(WireModel):
    state: Literal["fits"] = "fits"


class PartCantDo(WireModel):
    state: Literal["cant_do"] = "cant_do"
    note: str = Field(max_length=300)
    needs: CantNeed
    system: str | None = Field(default=None, max_length=40)


type CheckPartResult = Annotated[PartFits | PartCantDo, Field(discriminator="state")]

check_part_result_adapter: TypeAdapter[CheckPartResult] = TypeAdapter(CheckPartResult)


type ExplainFactKind = Literal["runs", "reads", "writes", "posts", "changes"]


class ExplainFact(WireModel):
    kind: ExplainFactKind
    together: list[str] = Field(min_length=1, max_length=12)
    negated: bool


class CodeWording(WireModel):
    wording: str = Field(min_length=1, max_length=1200)
    facts: list[ExplainFact] = Field(max_length=40)


class ExplainWordingRequest(CodeWording):
    model: ModelAccess


class ExplainReworded(WireModel):
    kind: Literal["reworded"] = "reworded"
    text: str = Field(min_length=1, max_length=700)


class ExplainKept(WireModel):
    kind: Literal["kept"] = "kept"
    why: str


type ExplainWordingResult = ExplainReworded | ExplainKept | ModelProblem

explain_wording_result_adapter: TypeAdapter[ExplainWordingResult] = TypeAdapter(
    ExplainWordingResult
)


# The AI troubleshooter's model version (ADR 0032, ADR 0055 section 10): the runtime's
# POST /v1/troubleshooter/cause, as this side reads it. The runtime answers in fields, never words.

STOP_MESSAGE_LIMIT: Final = 2000
EVENT_SUMMARY_LIMIT: Final = 400
MOST_EVENTS: Final = 80
RUN_BLOCK_NAME_LIMIT: Final = 200
MOST_RUN_BLOCKS: Final = 100

type RunBlockName = Annotated[str, Field(min_length=1, max_length=RUN_BLOCK_NAME_LIMIT)]
type CauseDetail = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")
]
type CauseCheck = Literal[
    "call", "not_a_block", "not_where_it_stopped", "not_a_system", "not_a_detail"
]


class StoppedRun(WireModel):
    stage: str = Field(max_length=40)
    reason: str = Field(max_length=40)
    retryable: bool
    message: str = Field(max_length=STOP_MESSAGE_LIMIT)


class CauseRequest(WireModel):
    model: ModelAccess
    stop: StoppedRun
    events: list[Annotated[str, Field(max_length=EVENT_SUMMARY_LIMIT)]] = Field(
        max_length=MOST_EVENTS
    )
    blocks: list[RunBlockName] = Field(min_length=1, max_length=MOST_RUN_BLOCKS)
    stopped_at: list[RunBlockName] = Field(min_length=1, max_length=MOST_RUN_BLOCKS)
    within_seconds: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def _stopped_in_the_version(self) -> Self:
        if not set(self.stopped_at) <= set(self.blocks):
            raise ValueError("Every block in stopped_at must be one of blocks")
        return self


class CauseFound(WireModel):
    kind: Literal["found"] = "found"
    failed_part: list[RunBlockName] = Field(min_length=1, max_length=MOST_RUN_BLOCKS)
    system: CauseSystem | None
    failure_kind: FailureKind
    detail: CauseDetail | None


class CauseKept(WireModel):
    kind: Literal["kept"] = "kept"
    why: CauseCheck


type CauseResult = CauseFound | CauseKept | ModelProblem

cause_result_adapter: TypeAdapter[CauseResult] = TypeAdapter(CauseResult)


# Simulation mode (ADR 0054, section 5): the runtime's POST /v1/simulation/scenarios and
# POST /v1/simulation/explain, as this side reads them. Both answer in picks, never words.

type ScenarioKind = Literal[
    "happy_path", "nothing_new", "source_not_found", "timeout", "approver_says_no", "odd_data"
]
type ScenarioServe = Literal["recorded", "varied", "empty", "not_found", "too_slow"]
type ScenarioVariation = Literal["suffix", "empty_field", "long_text"]
type ScenarioRole = Literal[
    "start", "read", "agent", "propose", "ask", "write", "tell", "notice", "idle", "other"
]
type SampleAnswer = Literal["github.release", "read.release", "read.page", "jira.issue"]
type ScenarioEnding = Literal[
    "reached_yes",
    "finished",
    "nothing_new",
    "declined",
    "no_answer",
    "stopped",
    "failed",
    "wrong_write",
    "did_not_end",
]
type SampleId = Annotated[
    str, StringConstraints(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
]
type ScenarioCheck = Literal[
    "call",
    "too_big",
    "key_shape",
    "not_the_kinds",
    "not_a_read",
    "not_a_sample",
    "not_an_agent",
    "too_many",
]
type NoteKind = Literal["stopped", "went_on", "ended_early", "changes", "no_end", "unknown"]
type NoteCheck = Literal[
    "call",
    "too_big",
    "key_shape",
    "not_a_scenario",
    "twice",
    "not_a_block",
    "not_a_play",
    "not_a_detail",
]
MOST_SAMPLES: Final = 20
MOST_SAMPLE_ITEMS: Final = 3
MOST_FAILED: Final = 20
SCENARIO_NAME_LIMIT: Final = 80


class ScenarioBlock(WireModel):
    name: RunBlockName
    role: ScenarioRole
    answer: SampleAnswer | None = None
    plays: list[ScenarioServe] = Field(default_factory=list[ScenarioServe], max_length=5)
    varies: list[ScenarioVariation] = Field(default_factory=list[ScenarioVariation], max_length=3)


class ScenarioSample(WireModel):
    id: SampleId
    answer: SampleAnswer
    block: RunBlockName | None = None
    items: list[dict[str, JsonValue]] = Field(max_length=MOST_SAMPLE_ITEMS)


class CoverBlock(WireModel):
    """A block no scenario reached yet, with the blocks whose exits lead straight to it."""

    name: RunBlockName
    after: list[RunBlockName] = Field(default_factory=list[str], max_length=MOST_RUN_BLOCKS)


class ScenarioWriteRequest(WireModel):
    model: ModelAccess
    blocks: list[ScenarioBlock] = Field(min_length=1, max_length=MOST_RUN_BLOCKS)
    kinds: list[ScenarioKind] = Field(min_length=1, max_length=6)
    samples: list[ScenarioSample] = Field(
        default_factory=list[ScenarioSample], max_length=MOST_SAMPLES
    )
    within_seconds: float = Field(gt=0, le=30)
    cover: list[CoverBlock] = Field(default_factory=list[CoverBlock], max_length=MOST_RUN_BLOCKS)


class WrittenRead(WireModel):
    block: RunBlockName
    serve: ScenarioServe
    sample: SampleId | None = None
    vary: list[ScenarioVariation] = Field(default_factory=list[ScenarioVariation], max_length=3)


class WrittenScenario(WireModel):
    kind: ScenarioKind
    reads: list[WrittenRead] = Field(default_factory=list[WrittenRead], max_length=MOST_RUN_BLOCKS)
    slow_agents: list[RunBlockName] = Field(default_factory=list[str], max_length=MOST_RUN_BLOCKS)


class ScenariosWritten(WireModel):
    kind: Literal["written"] = "written"
    scenarios: list[WrittenScenario] = Field(min_length=1, max_length=6)


class ScenariosKept(WireModel):
    kind: Literal["kept"] = "kept"
    why: ScenarioCheck


type ScenarioWriteResult = ScenariosWritten | ScenariosKept | ModelProblem

scenario_write_result_adapter: TypeAdapter[ScenarioWriteResult] = TypeAdapter(ScenarioWriteResult)


class ScenarioPlay(WireModel):
    block: RunBlockName
    serve: ScenarioServe
    vary: list[ScenarioVariation] = Field(default_factory=list[ScenarioVariation], max_length=3)


class FailedScenario(WireModel):
    name: str = Field(min_length=1, max_length=SCENARIO_NAME_LIMIT)
    kind: ScenarioKind
    ending: ScenarioEnding | None
    stopped_at: RunBlockName | None
    expected: str = Field(max_length=300)
    happened: str = Field(max_length=STOP_MESSAGE_LIMIT)
    ran: list[RunBlockName] = Field(max_length=MOST_RUN_BLOCKS)
    plays: list[ScenarioPlay] = Field(max_length=MOST_RUN_BLOCKS)


class ScenarioExplainRequest(WireModel):
    model: ModelAccess
    failed: list[FailedScenario] = Field(min_length=1, max_length=MOST_FAILED)
    within_seconds: float = Field(gt=0, le=15)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [f.name for f in self.failed]
        if len(set(names)) != len(names):
            raise ValueError("Each failed scenario is named once")
        return self


class FailureNote(WireModel):
    scenario: str = Field(min_length=1, max_length=SCENARIO_NAME_LIMIT)
    block: RunBlockName
    kind: NoteKind
    source: RunBlockName | None
    detail: CauseDetail | None


class ScenariosExplained(WireModel):
    kind: Literal["explained"] = "explained"
    notes: list[FailureNote] = Field(max_length=MOST_FAILED)
    kept: list[NoteCheck] = Field(max_length=MOST_FAILED)


type ScenarioExplainResult = ScenariosExplained | ModelProblem

scenario_explain_result_adapter: TypeAdapter[ScenarioExplainResult] = TypeAdapter(
    ScenarioExplainResult
)


# The workflow drafter (ADR 0051): the runtime's POST /v1/workflows/draft, as this side reads it.

type SettingKind = Literal[
    "run_time", "jira_project", "channel", "address", "repository", "confluence_page", "text"
]
type SettingMark = Literal["filled", "guessed", "needed"]


class WriteKeyFact(WireModel):
    name: str
    system: str


class DrafterFacts(WireModel):
    """The team's facts the drafter may use. No Approver's name and no secret."""

    jira_projects: list[str] = Field(default_factory=list[str])
    confluence_pages: list[str] = Field(default_factory=list[str])
    repositories: list[str] = Field(default_factory=list[str])
    channels: list[str] = Field(default_factory=list[str])
    agent_cards: list[LibraryCard] = Field(default_factory=list[LibraryCard])
    write_keys: list[WriteKeyFact] = Field(default_factory=list[WriteKeyFact])


class PlanBlock(WireModel):
    name: str
    type: str
    version: float
    parameters: dict[str, Any]


class PlanWire(WireModel):
    from_block: str
    exit: str
    to_block: str
    exit_index: int = Field(ge=0)
    input_index: int = Field(ge=0)


class SettingPlace(WireModel):
    block: str
    parameter: str


class PlanSetting(WireModel):
    id: str
    kind: SettingKind
    label: str
    fills: list[SettingPlace]
    value: str | None
    mark: SettingMark


class WorkflowPlan(WireModel):
    name: str
    blocks: list[PlanBlock] = Field(min_length=1)
    wires: list[PlanWire]
    settings: list[PlanSetting]


class WorkflowDraftRequest(WireModel):
    words: str
    facts: DrafterFacts
    current: WorkflowPlan | None = None
    model: ModelAccess


class PlanProblem(WireModel):
    code: str
    block: str | None = None
    text: str


class SentBack(WireModel):
    problems: list[PlanProblem]


class WorkflowDrafted(WireModel):
    status: Literal["drafted"] = "drafted"
    plan: WorkflowPlan
    catalogue: str
    sent_back: list[SentBack]
    turns: int


class WorkflowNotDrafted(WireModel):
    status: Literal["not_drafted"] = "not_drafted"
    why: Literal["gave_up", "no_tool_call", "too_long", "failed"]
    message: str
    catalogue: str
    sent_back: list[SentBack]
    turns: int


class KeyPasted(WireModel):
    status: Literal["key_pasted"] = "key_pasted"
    message: str


type WorkflowDraftResult = Annotated[
    WorkflowDrafted | WorkflowNotDrafted | KeyPasted | ModelProblem,
    Field(discriminator="status"),
]

workflow_draft_result_adapter: TypeAdapter[WorkflowDraftResult] = TypeAdapter(WorkflowDraftResult)


# Fix it for me (ADR 0055, PR 6): the runtime's POST /v1/fixes, as this side sends it.
# platform-api wrote the fix's start and minted its token first. The runtime answers at once.

type FixIdText = Annotated[str, StringConstraints(pattern=r"^fix_[0-9A-Za-z]{1,40}$")]


class FixAsked(WireModel):
    """One press of Fix it for me, as the coordinator takes it."""

    fix_id: FixIdText
    asked_by: str = Field(min_length=1)
    asked_by_name: str = Field(min_length=1, max_length=80)
    ends_by: AwareDatetime
    stop: StoppedRun
    version: WorkflowPlan = Field(description="The stopped version, with each key kept out.")
    stopped_at: list[RunBlockName] = Field(min_length=1)


class FixStartRequest(WireModel):
    run_id: str
    request: FixAsked
    events: list[Annotated[str, Field(max_length=EVENT_SUMMARY_LIMIT)]] = Field(
        max_length=MOST_EVENTS
    )
    facts: DrafterFacts
    model: ModelAccess
    platform_url: str
    token: str


class CheckedCase(WireModel):
    """One case a drafted revision's Check failed, as code graded it."""

    kind: ScenarioKind
    step: RunBlockName | None = None
    why: str | None = Field(default=None, max_length=40)


class RefineAsked(WireModel):
    """A drafted workflow's Check to refine (ADR 0054, section 7), as the coordinator takes it.
    Its id has a fix's shape: the coordinator runs it as a fix of a draft."""

    fix_id: FixIdText
    asked_by: str = Field(min_length=1)
    ends_by: AwareDatetime
    version: WorkflowPlan = Field(description="The draft as the Check tried it.")
    failed: list[CheckedCase] = Field(default_factory=list[CheckedCase], max_length=10)
    not_reached: list[RunBlockName] = Field(default_factory=list[str], max_length=10)


class RefineStartRequest(WireModel):
    drafted_id: str
    request: RefineAsked
    facts: DrafterFacts
    model: ModelAccess
    platform_url: str
    token: str


class FixAccepted(WireModel):
    fix_id: FixIdText
    started: bool


fix_accepted_adapter: TypeAdapter[FixAccepted] = TypeAdapter(FixAccepted)
FIX_START_WAIT_SECONDS: Final = 10.0


class AgentCard(WireModel):
    id: str
    display: str
    description: str
    capabilities: list[str]


class AgentCards(WireModel):
    agents: list[AgentCard]


@dataclass(frozen=True)
class AgentUnavailable:
    detail: str


@dataclass(frozen=True)
class AgentRejected:
    detail: str


type AgentReply = TaskFinished | TaskFailed | AgentUnavailable | AgentRejected


class AgentRuntime(Protocol):
    async def run_task(self, request: TaskRequest) -> AgentReply: ...


AGENT_KEY_HEADER = "X-Agent-Key"
AGENT_TIMEOUT_SECONDS = 60.0
RUNTIME_SMOOTHS_IN_SECONDS = 8.0
RUNTIME_VERIFIES_IN_SECONDS = 8.0
EXPLAIN_WAIT_SECONDS = RUNTIME_SMOOTHS_IN_SECONDS + RUNTIME_VERIFIES_IN_SECONDS + 4.0
RUNTIME_ANSWERS_IN_SECONDS = 1.0
"""Past the time a cause request gives the runtime, for its answer to come back."""
DRAFT_WAIT_SECONDS = 200.0
"""The drafter stops itself at 170 seconds (ADR 0051, amended for step 5), with room to answer."""


class HttpAgentRuntime:
    def __init__(self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=AGENT_TIMEOUT_SECONDS)

    async def run_task(self, request: TaskRequest) -> AgentReply:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/tasks",
                json=request.model_dump(mode="json"),
                headers={AGENT_KEY_HEADER: self._api_key},
                timeout=AGENT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            return AgentUnavailable(f"The agent runtime did not answer: {error!r}")
        if response.status_code >= 500:
            return AgentUnavailable(f"The agent runtime answered {response.status_code}")
        if response.status_code >= 400:
            return AgentRejected(
                f"The agent runtime refused the task ({response.status_code}): "
                f"{response.text[:200]}"
            )
        try:
            return task_result_adapter.validate_json(response.content)
        except ValueError as error:
            return AgentRejected(f"The agent runtime's reply did not parse: {error}")

    async def connect_model(
        self, request: ConnectRequest
    ) -> ConnectResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/models/connect", request, connect_result_adapter)

    async def test_model(
        self, access: ModelAccess
    ) -> ModelTestResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/models/test", access, model_test_result_adapter)

    async def choose(
        self, request: ChooseRequest
    ) -> ChooseResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/planner/choose", request, choose_result_adapter)

    async def draft(self, request: DraftRequest) -> DraftResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/cards/draft", request, draft_result_adapter)

    async def find_software(
        self, request: FindSoftwareRequest
    ) -> FindSoftwareResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/software/find", request, find_software_result_adapter)

    async def read_releases(
        self, request: ReadReleasesRequest
    ) -> ReadReleasesResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/releases/read", request, read_releases_result_adapter)

    async def answer(
        self, request: AnswerRequest
    ) -> AnswerResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/planner/answer", request, answer_result_adapter)

    async def check_part(
        self, request: CheckPartRequest
    ) -> CheckPartResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/planner/check-part", request, check_part_result_adapter)

    async def explain_wording(
        self, request: ExplainWordingRequest
    ) -> ExplainWordingResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/workflows/explain",
            request,
            explain_wording_result_adapter,
            EXPLAIN_WAIT_SECONDS,
        )

    async def find_cause(
        self, request: CauseRequest
    ) -> CauseResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/troubleshooter/cause",
            request,
            cause_result_adapter,
            request.within_seconds + RUNTIME_ANSWERS_IN_SECONDS,
        )

    async def write_scenarios(
        self, request: ScenarioWriteRequest
    ) -> ScenarioWriteResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/simulation/scenarios",
            request,
            scenario_write_result_adapter,
            request.within_seconds + RUNTIME_ANSWERS_IN_SECONDS,
        )

    async def explain_scenarios(
        self, request: ScenarioExplainRequest
    ) -> ScenarioExplainResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/simulation/explain",
            request,
            scenario_explain_result_adapter,
            request.within_seconds + RUNTIME_ANSWERS_IN_SECONDS,
        )

    async def draft_workflow(
        self, request: WorkflowDraftRequest
    ) -> WorkflowDraftResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/workflows/draft", request, workflow_draft_result_adapter, DRAFT_WAIT_SECONDS
        )

    async def start_fix(
        self, request: FixStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/fixes", request, fix_accepted_adapter, FIX_START_WAIT_SECONDS
        )

    async def start_refinement(
        self, request: RefineStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/refinements", request, fix_accepted_adapter, FIX_START_WAIT_SECONDS
        )

    async def capabilities(self) -> CapabilityList | AgentUnavailable | AgentRejected:
        try:
            response = await self._client.get(
                f"{self._base_url}/v1/capabilities",
                headers={AGENT_KEY_HEADER: self._api_key},
                timeout=AGENT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            return AgentUnavailable(f"The agent runtime did not answer: {type(error).__name__}")
        if response.status_code >= 500:
            return AgentUnavailable(f"The agent runtime answered {response.status_code}")
        if response.status_code >= 400:
            return AgentRejected(f"The agent runtime refused the request ({response.status_code})")
        try:
            return CapabilityList.model_validate_json(response.content)
        except ValueError:
            return AgentRejected("The agent runtime's answer did not parse")

    async def check_github(self) -> GitHubCheckResult | AgentUnavailable | AgentRejected:
        return await self._model_call(
            "/v1/connections/github/check", None, github_check_result_adapter
        )

    async def _model_call[T](
        self,
        path: str,
        body: WireModel | None,
        adapter: TypeAdapter[T],
        timeout: float = AGENT_TIMEOUT_SECONDS,
    ) -> T | AgentUnavailable | AgentRejected:
        # The body holds a model key, and an error answer can echo the body, so no text is kept.
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=None if body is None else body.model_dump(mode="json"),
                headers={AGENT_KEY_HEADER: self._api_key},
                timeout=timeout,
            )
        except httpx.HTTPError as error:
            return AgentUnavailable(f"The agent runtime did not answer: {type(error).__name__}")
        if response.status_code >= 500:
            return AgentUnavailable(f"The agent runtime answered {response.status_code}")
        if response.status_code >= 400:
            return AgentRejected(f"The agent runtime refused the request ({response.status_code})")
        try:
            return adapter.validate_json(response.content)
        except ValueError:
            return AgentRejected("The agent runtime's answer did not parse")

    async def close(self) -> None:
        await self._client.aclose()
