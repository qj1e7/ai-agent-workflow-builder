from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Final, Literal, Protocol, Self

import httpx
from pydantic import Field, StringConstraints, TypeAdapter, field_validator, model_validator

from platform_api.monitoring import AgentEvent
from platform_api.orchestration.schedule import AT_PATTERN, Day
from platform_api.wire import RepoName, WireModel


class GithubSource(WireModel):
    kind: Literal["github"] = "github"
    ref: RepoName


class SoftwareToCheck(WireModel):
    id: str
    name: str
    source: GithubSource
    our_version: str | None
    open_ticket: str | None = None
    awaiting_approval: bool = False
    from_first_check: bool = False


class WatchlistInputs(WireModel):
    kind: Literal["watchlist"] = "watchlist"
    tag_pattern: str
    software: list[SoftwareToCheck]


type ToolId = Literal[
    "github.read_releases", "jira.search", "jira.read_ticket", "jira.create_ticket"
]
type ToolKind = Literal["read", "write"]
type InputKind = Literal["github_repo", "jira_project", "text"]


class CardInput(WireModel):
    name: str
    kind: InputKind
    what: str = ""
    example: str = ""


class CardBlock(WireModel):
    say: str
    tool: ToolId | None


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


class Finding(WireModel):
    software_id: str
    state: FindingState
    newest: str | None
    new_versions: list[str]
    detail: str
    full_name: RepoName | None = None
    not_found: bool = False


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
    id: ToolId
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
    connection: Literal["jira", "github", "teams"] | None
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
    tools: list[ToolId] = Field(default_factory=list[ToolId])


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


class UnderstoodRow(WireModel):
    kind: RowKind
    text: str = Field(max_length=200)
    state: RowState
    note: str | None = Field(default=None, max_length=300)


class FindSoftwareRequest(WireModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    tag_pattern: str


class SoftwareMatch(WireModel):
    repo: RepoName
    what: str = Field(min_length=1, max_length=120)
    why: str = Field(max_length=300)
    releases: Literal["published", "none"]
    newest: str | None


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


class WorkflowFact(WireModel):
    name: str = Field(max_length=80)
    state: Literal["on", "paused"]
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
    total: int = Field(ge=0)


class WatchlistScheduleFact(WireModel):
    day: Day
    at: str = Field(pattern=AT_PATTERN)


class PlannerFacts(WireModel):
    watchlist: list[WatchedFact] | None = Field(default=None, max_length=100)
    workflows: list[WorkflowFact] | None = Field(default=None, max_length=50)
    needs_you: NeedsYouFact | None = None
    watchlist_schedule: WatchlistScheduleFact | None = None


class PreviousTurn(WireModel):
    request: str = Field(max_length=2000)
    software: str | None = Field(default=None, max_length=80)
    answer: str | None = Field(default=None, max_length=600)
    kind: str | None = Field(default=None, max_length=40)


class AnswerRequest(WireModel):
    task: str
    model: ModelAccess
    facts: PlannerFacts | None = None
    previous: PreviousTurn | None = None
    changes_workflows: bool = True


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


CantAnswer.model_rebuild()


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


class QuestionAnswer(WireModel):
    kind: Literal["question"] = "question"
    text: str = Field(min_length=1, max_length=600)
    looked_at: list[FactSection] = Field(max_length=3)
    about_software: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=3
    )


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

    @model_validator(mode="after")
    def _a_cant_proposes_nothing(self) -> Self:
        if self.cant is not None and (self.schedule is not None or self.holds_save):
            raise ValueError("An edit the chat can't make proposes no schedule")
        return self


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
    | ResumeAnswer,
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

    async def answer(
        self, request: AnswerRequest
    ) -> AnswerResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/planner/answer", request, answer_result_adapter)

    async def check_part(
        self, request: CheckPartRequest
    ) -> CheckPartResult | AgentUnavailable | AgentRejected:
        return await self._model_call("/v1/planner/check-part", request, check_part_result_adapter)

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
        self, path: str, body: WireModel | None, adapter: TypeAdapter[T]
    ) -> T | AgentUnavailable | AgentRejected:
        # The body holds a model key, and an error answer can echo the body, so no text is kept.
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=None if body is None else body.model_dump(mode="json"),
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
            return adapter.validate_json(response.content)
        except ValueError:
            return AgentRejected("The agent runtime's answer did not parse")

    async def close(self) -> None:
        await self._client.aclose()
