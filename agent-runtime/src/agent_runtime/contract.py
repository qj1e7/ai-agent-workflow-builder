from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRef(WireModel):
    id: str
    display: str


class AgentAddressee(WireModel):
    kind: Literal["agent"] = "agent"
    id: str
    display: str


class RoomAddressee(WireModel):
    kind: Literal["room"] = "room"


type Addressee = Annotated[AgentAddressee | RoomAddressee, Field(discriminator="kind")]


class AgentJoinedData(WireModel):
    agent: AgentRef
    reason: str


class AgentStepStartedData(WireModel):
    step: str


class AgentStepFinishedData(WireModel):
    step: str
    result: dict[str, Any]


class AgentFailedData(WireModel):
    step: str | None
    error_type: str
    message: str
    retryable: bool


class AgentMessageData(WireModel):
    speaker: AgentRef
    addressee: Addressee
    text: str


class _AgentEnvelope(WireModel):
    agent_seq: int = Field(ge=1)
    ts: datetime
    agent: AgentRef
    summary: str


class AgentJoinedEvent(_AgentEnvelope):
    kind: Literal["agent_joined"] = "agent_joined"
    data: AgentJoinedData


class AgentStepStartedEvent(_AgentEnvelope):
    kind: Literal["agent_step_started"] = "agent_step_started"
    data: AgentStepStartedData


class AgentStepFinishedEvent(_AgentEnvelope):
    kind: Literal["agent_step_finished"] = "agent_step_finished"
    data: AgentStepFinishedData


class AgentFailedEvent(_AgentEnvelope):
    kind: Literal["agent_failed"] = "agent_failed"
    data: AgentFailedData


class AgentMessageEvent(_AgentEnvelope):
    kind: Literal["agent_message"] = "agent_message"
    data: AgentMessageData


type AgentEvent = Annotated[
    AgentJoinedEvent
    | AgentStepStartedEvent
    | AgentStepFinishedEvent
    | AgentFailedEvent
    | AgentMessageEvent,
    Field(discriminator="kind"),
]

agent_event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


class AgentEventPost(WireModel):
    task_id: str
    event: AgentEvent


REPO_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"


def _not_a_dot_segment(repo: str) -> str:
    if repo.split("/")[-1] in {".", ".."}:
        raise ValueError("repo must not be . or ..")
    return repo


type RepoName = Annotated[str, Field(pattern=REPO_PATTERN), AfterValidator(_not_a_dot_segment)]


SEMVER_TAG_PATTERN = r"^\d+\.\d+\.\d+$"
VETTED_TAG_PATTERNS = frozenset({SEMVER_TAG_PATTERN})


def _vetted_tag_pattern(pattern: str) -> str:
    if pattern not in VETTED_TAG_PATTERNS:
        raise ValueError(f"tag_pattern must be one of {sorted(VETTED_TAG_PATTERNS)}")
    return pattern


def _allowed_list() -> str:
    return ", ".join(f"`{pattern}`" for pattern in sorted(VETTED_TAG_PATTERNS))


type TagPattern = Annotated[
    str,
    AfterValidator(_vetted_tag_pattern),
    Field(
        description="Which release tags count. Only a pattern from a fixed list is accepted, "
        f"never one the caller writes. Allowed values: {_allowed_list()}."
    ),
]


SOFTWARE_ID_PATTERN = r"^sw_[0-9A-Z]{26}$"


class GithubSource(WireModel):
    kind: Literal["github"] = "github"
    ref: RepoName = Field(description="The repository whose releases are read, as owner/name.")


class SoftwareToCheck(WireModel):
    id: str = Field(pattern=SOFTWARE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    source: GithubSource
    our_version: str | None = Field(
        description="The version the team runs now. None means the newest release becomes the "
        "starting point."
    )
    open_ticket: str | None = Field(
        default=None,
        description="The ticket already raised for this software and not yet done, such as "
        "MOCK-7. While there is one, no new ticket is proposed.",
    )
    awaiting_approval: bool = Field(
        default=False,
        description="True while an earlier check's ticket for this software waits for an "
        "Approver. No new ticket is proposed meanwhile.",
    )


def _distinct_ids(software: list[SoftwareToCheck]) -> list[SoftwareToCheck]:
    ids = [item.id for item in software]
    if len(set(ids)) < len(ids):
        raise ValueError("each software id must appear once")
    return software


class WatchlistInputs(WireModel):
    kind: Literal["watchlist"] = "watchlist"
    tag_pattern: TagPattern
    software: Annotated[
        list[SoftwareToCheck], Field(min_length=1, max_length=100), AfterValidator(_distinct_ids)
    ]


type ToolId = Literal[
    "github.read_releases", "jira.search", "jira.read_ticket", "jira.create_ticket"
]
type ToolKind = Literal["read", "write"]
type InputKind = Literal["github_repo", "jira_project", "text"]

CARD_ID_PATTERN = r"^crd_[0-9A-Za-z_]{1,40}$"


class CardInput(WireModel):
    name: str = Field(min_length=1, max_length=60)
    kind: InputKind = Field(
        description="What the value is. A write tool's target comes from the card's one input "
        "of the kind that tool needs, such as jira_project for jira.create_ticket."
    )
    what: str = Field(default="", max_length=200)
    example: str = Field(default="", max_length=100)


class CardBlock(WireModel):
    say: str = Field(min_length=1, max_length=300, description="The step in plain English.")
    tool: ToolId | None = Field(
        description="The one tool this block uses, or None for a block that only thinks."
    )


def _distinct_input_names(inputs: list[CardInput]) -> list[CardInput]:
    names = [item.name.casefold() for item in inputs]
    if len(set(names)) < len(names):
        raise ValueError("each input name must appear once")
    return inputs


class CardSpec(WireModel):
    id: str = Field(pattern=CARD_ID_PATTERN)
    version: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=60)
    purpose: str = Field(min_length=1, max_length=300)
    inputs: Annotated[list[CardInput], Field(max_length=8), AfterValidator(_distinct_input_names)]
    blocks: Annotated[list[CardBlock], Field(min_length=1, max_length=12)]


def _values_name_the_inputs(agent: CardToRun) -> CardToRun:
    if set(agent.values) != {item.name for item in agent.card.inputs}:
        raise ValueError("values must name exactly the card's inputs")
    return agent


class CardToRun(WireModel):
    card: CardSpec
    values: dict[str, str] = Field(description="One value for each of the card's inputs, by name.")


type CheckedCardToRun = Annotated[CardToRun, AfterValidator(_values_name_the_inputs)]


def _distinct_cards(agents: list[CardToRun]) -> list[CardToRun]:
    ids = [agent.card.id for agent in agents]
    if len(set(ids)) < len(ids):
        raise ValueError("each card may run once in a task")
    return agents


class CardsInputs(WireModel):
    kind: Literal["cards"] = "cards"
    agents: Annotated[
        list[CheckedCardToRun], Field(min_length=1, max_length=3), AfterValidator(_distinct_cards)
    ] = Field(description="The agents the Planner brings in, in the order they work.")


type TaskInputs = Annotated[WatchlistInputs | CardsInputs, Field(discriminator="kind")]


class CarryForward(WireModel):
    """What a run hands to the next run of its use case. Nothing yet."""


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
    style: ModelStyle = Field(
        description="How to call the model: Anthropic's Messages API or OpenAI's Chat Completions "
        "API."
    )
    base_url: str = Field(description="The address the chat client calls, as Connect found it.")
    model: str
    api_key: str = Field(
        repr=False, description="Used for this call only. The runtime never stores or logs it."
    )


class TaskRequest(WireModel):
    task_id: str
    run_id: str
    instruction: str
    inputs: TaskInputs
    carry_forward: CarryForward
    callback: Callback
    model: ModelAccess | None = Field(
        default=None,
        description="The model that writes the summary. Without one, the runtime uses its own "
        "settings, then its template. A reused task_id is matched without this field, so a key "
        "replaced between two tries of one task does not make it a different task.",
    )


class ProposedIntent(WireModel):
    kind: str
    fields: dict[str, Any]
    reason: str
    subject: str | None = Field(
        default=None,
        description="The id of the input this write is about, such as a watched software's id. "
        "The platform uses it to follow the write once it is done.",
    )


type FindingState = Literal[
    "behind", "up_to_date", "starting_point", "already_raised", "cant_check"
]


class Finding(WireModel):
    software_id: str
    state: FindingState
    newest: str | None = Field(
        description="The newest release at the source that matches the tag pattern. None when "
        "the source could not be read or has no such release."
    )
    new_versions: list[str] = Field(
        description="Releases newer than our version, newest first. Empty unless the state is "
        "behind or already_raised."
    )
    detail: str = Field(description="One plain sentence for people about this software.")


class TaskOutput(WireModel):
    summary: str
    new_tags: list[str]
    proposed: list[ProposedIntent]
    carry_forward: CarryForward
    findings: list[Finding] = Field(
        default_factory=list[Finding],
        description="One per watched software, in the order of the inputs. Empty for a card run.",
    )


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
    suggested: bool = Field(
        description="True when the name suggests a fast model, which suits summaries."
    )


class Connected(WireModel):
    status: Literal["connected"] = "connected"
    style: ModelStyle
    base_url: str = Field(description="The address to send with this style in a ModelAccess.")
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
    message: str = Field(
        description="Plain words for an Operator. Never the provider's own error text, which can "
        "quote the address or the key."
    )


type ConnectResult = Annotated[Connected | ModelProblem, Field(discriminator="status")]


class ModelTestPassed(WireModel):
    status: Literal["passed"] = "passed"
    seconds: float
    text: str


type ModelTestResult = Annotated[ModelTestPassed | ModelProblem, Field(discriminator="status")]


class ToolSpec(WireModel):
    id: ToolId
    kind: ToolKind
    name: str
    description: str
    input_schema: dict[str, Any] = Field(
        description="The arguments the model sends. A write tool never takes its target."
    )


class ToolList(WireModel):
    tools: list[ToolSpec]


class DraftRequest(WireModel):
    task: str = Field(min_length=1, max_length=2000)
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
    """What the model drafted, unchecked. Tool ids and input kinds are plain text here, because
    the platform checks the draft and shows an Operator every problem before it can be saved."""

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


class LibraryInput(WireModel):
    name: str
    kind: InputKind


class LibraryCard(WireModel):
    card_id: str = Field(pattern=CARD_ID_PATTERN)
    name: str
    purpose: str
    good_for: list[str] = Field(default_factory=list[str])
    inputs: list[LibraryInput] = Field(default_factory=list[LibraryInput])
    tools: list[ToolId] = Field(default_factory=list[ToolId])


class ChooseRequest(WireModel):
    task: str = Field(min_length=1, max_length=2000)
    library: list[LibraryCard] = Field(max_length=50)
    model: ModelAccess


type ChoiceDecision = Literal["use_one", "use_several", "new_agent", "cannot_do"]


class ChosenAgent(WireModel):
    card_id: str
    part: str
    values: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="Only values the task itself says, by input name. Never invented.",
    )


class Choice(WireModel):
    decision: ChoiceDecision
    agents: list[ChosenAgent] = Field(default_factory=list[ChosenAgent], max_length=3)
    new_agent: str | None = None
    reason: str
    questions: list[str] = Field(default_factory=list[str])


class Chosen(WireModel):
    status: Literal["chosen"] = "chosen"
    choice: Choice


type ChooseResult = Annotated[Chosen | ModelProblem, Field(discriminator="status")]


class AgentCard(WireModel):
    id: str
    display: str
    description: str
    capabilities: list[str]


class AgentCards(WireModel):
    agents: list[AgentCard]


class Health(WireModel):
    status: Literal["ok"] = "ok"


class AgentApiSchema(WireModel):
    task_request: TaskRequest
    task_result: TaskResult
    callback: AgentEventPost
    agent_cards: AgentCards
    model_connect_request: ConnectRequest
    model_connect_result: ConnectResult
    model_test_request: ModelAccess
    model_test_result: ModelTestResult
    tool_list: ToolList
    card_draft_request: DraftRequest
    card_draft_result: DraftResult
    planner_choose_request: ChooseRequest
    planner_choose_result: ChooseResult
