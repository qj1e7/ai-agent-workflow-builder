from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import Field, TypeAdapter

from platform_api.monitoring import AgentEvent
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
    pass


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


class ToolSpec(WireModel):
    id: ToolId
    kind: ToolKind
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolList(WireModel):
    tools: list[ToolSpec]


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


class UnderstandRequest(WireModel):
    task: str
    model: ModelAccess


type RowKind = Literal["schedule", "look_for", "do", "where"]
type RowState = Literal["understood", "changed", "missing", "cant_do"]


class UnderstoodRow(WireModel):
    kind: RowKind
    text: str = Field(max_length=200)
    state: RowState
    note: str | None = Field(default=None, max_length=300)


class Understood(WireModel):
    status: Literal["understood"] = "understood"
    rows: list[UnderstoodRow] = Field(min_length=4, max_length=8)


class BelongsOnWatchlist(WireModel):
    status: Literal["watchlist"] = "watchlist"
    word: str = Field(min_length=1, max_length=80)
    software: str | None = Field(default=None, max_length=80)


type UnderstandResult = Annotated[
    Understood | BelongsOnWatchlist | ModelProblem, Field(discriminator="status")
]

understand_result_adapter: TypeAdapter[UnderstandResult] = TypeAdapter(UnderstandResult)


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

    async def _model_call[T](
        self, path: str, body: WireModel, adapter: TypeAdapter[T]
    ) -> T | AgentUnavailable | AgentRejected:
        # The body holds a model key, and an error answer can echo the body, so no text is kept.
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=body.model_dump(mode="json"),
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
