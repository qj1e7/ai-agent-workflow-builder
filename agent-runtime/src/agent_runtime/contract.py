from datetime import date, datetime
from typing import Annotated, Any, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter


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


RELEASE_TAG_PATTERN = r"^(?:[vV]|docker-v|n8n@|langchain==)?\d+\.\d+\.\d+$"
"""A version number, with or without one v in front, such as 1.2.14 or v2.14.2, or with the
prefix three projects put on the tags of their main product: moby's docker-v29.1.0, n8n's
n8n@2.4.2 and LangChain's langchain==0.3.1. The same project's other tags, such as
langchain-core==0.3.1 or cli==0.4.37, do not count."""
V_TAG_PATTERN = r"^[vV]?\d+\.\d+\.\d+$"
"""The pattern from before those prefixes counted. Runs saved with it still send it."""
PLAIN_TAG_PATTERN = r"^\d+\.\d+\.\d+$"
"""The pattern from before v tags counted. Runs saved with it still send it."""
VETTED_TAG_PATTERNS = frozenset({RELEASE_TAG_PATTERN, V_TAG_PATTERN, PLAIN_TAG_PATTERN})


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
    from_first_check: bool = Field(
        default=False,
        description="True when our_version is only the newest release an earlier first check "
        "read, not a version anyone gave. A ticket then says so instead of calling it the "
        "version the team runs.",
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
    """What a run hands to the next run of its use case."""

    last_run_on: date | None = Field(
        default=None,
        description="The day the workflow's last finished run started, in the task's time_zone, "
        "so it is the day the run list shows. None when it has no finished run yet. The platform "
        "sets it on a task. It is empty in a task's output.",
    )


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


def _known_zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ValueError, ZoneInfoNotFoundError:
        raise ValueError("not a time zone name, such as Asia/Singapore") from None
    return name


class TaskRequest(WireModel):
    task_id: str
    run_id: str
    instruction: str
    inputs: TaskInputs
    carry_forward: CarryForward
    time_zone: Annotated[str, AfterValidator(_known_zone)] = Field(
        description="The zone the team works in, such as Asia/Singapore. The agents' today and "
        "every plain day they read or send, last_run_on included, are days in it."
    )
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
    full_name: RepoName | None = Field(
        default=None,
        description="The owner/name GitHub answered for the saved repository at this check. It "
        "differs from the saved one when GitHub renamed or moved the repository and redirects "
        "the old name. None when GitHub was not asked or did not answer.",
    )
    not_found: bool = Field(
        default=False,
        description="True when GitHub answered that the saved repository does not exist (404). "
        "Nothing says where it went.",
    )


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
    findings: list[Finding] = Field(
        default_factory=list[Finding],
        description="When a watchlist check could read none of its software: one finding for "
        "each, with its own reason. Empty for any other failure.",
    )


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


class GitHubWorking(WireModel):
    status: Literal["working"] = "working"
    using_token: bool = Field(
        description="False when no token is set and GitHub is read anonymously, 60 calls an hour."
    )
    expires_at: datetime | None = Field(
        default=None,
        description="When GitHub says the token stops working. Null for a token with no end "
        "date and when no token is set.",
    )


type GitHubProblemReason = Literal["token_refused", "unreachable", "unexpected_answer"]


class GitHubProblem(WireModel):
    status: Literal["problem"] = "problem"
    reason: GitHubProblemReason
    message: str = Field(
        description="Plain words for an Operator. Never the token or GitHub's own error text."
    )


type GitHubCheckResult = Annotated[GitHubWorking | GitHubProblem, Field(discriminator="status")]


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


type CapabilityKind = Literal["read", "write", "notify", "none"]
type CapabilityState = Literal["ready", "planned", "unsupported"]
type ConnectionId = Literal["jira", "github", "teams"]
type ExampleKind = Literal["automate", "monitor", "learn"]


class CapabilitySpec(WireModel):
    id: str = Field(pattern=r"^[a-z]+(\.[a-z_]+)?$")
    plain: str = Field(description="The capability in an Operator's words.")
    kind: CapabilityKind
    system: str | None = Field(description="The system it reaches, in an Operator's words.")
    state: CapabilityState = Field(
        description="The base state. A missing key or a system that is not answering is worked "
        "out from the connection, not here."
    )
    cant: str | None = Field(
        description="The verb phrase a refusal uses after I can't, or None when it is ready."
    )
    why: str | None = Field(
        description="Why it can't be done, in plain words, or None when it is ready."
    )
    connection: ConnectionId | None
    needs_model: bool = Field(
        description="True when the agents do it with the AI model, so it needs one connected."
    )
    platform: bool = Field(
        description="True for what the platform does by itself, which Home leaves out of its lists."
    )
    focus: bool = Field(
        description="True for what software versioning uses: checking releases, asking for a yes, "
        "creating the upgrade ticket. Home's lists show only these."
    )
    tools: list[ToolId] = Field(description="The tools that do it. Empty unless it is ready.")


class ExampleSpec(WireModel):
    text: str
    kind: ExampleKind
    needs: list[str] = Field(description="The ids of the capabilities the example uses.")


class CapabilityList(WireModel):
    capabilities: list[CapabilitySpec]
    examples: list[ExampleSpec]


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


type RowKind = Literal["schedule", "look_for", "do", "where"]
type RowState = Literal["understood", "changed", "missing", "cant_do"]


class UnderstoodRow(WireModel):
    kind: RowKind
    text: str = Field(
        max_length=200,
        description="What the Planner read, in plain words. Empty when the part is missing, "
        "and can be empty when it can't be done.",
    )
    state: RowState
    note: str | None = Field(
        default=None,
        max_length=300,
        description="Why the part is changed, missing or can't be done. Usually None when it is "
        "understood.",
    )


class FindSoftwareRequest(WireModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = (
        Field(description="The software as a person wrote it, such as Kubernetes.")
    )
    tag_pattern: TagPattern


class SoftwareMatch(WireModel):
    repo: RepoName = Field(
        description="A GitHub project that exists, as owner/name, at the address GitHub gives it "
        "now. Checked just now."
    )
    what: str = Field(
        min_length=1,
        max_length=120,
        description="What the project is, in plain words, so the person can tell matches apart.",
    )
    why: str = Field(
        max_length=300,
        description="Where the guess came from, in plain words, for the person to read.",
    )
    releases: Literal["published", "none"] = Field(
        description="Whether the project has a stable release that the request's tag rule "
        "counts. With none, a watch would have nothing to compare."
    )
    newest: str | None = Field(
        description="The newest stable release tag that the tag rule counts. None when there is "
        "none."
    )


class FoundSoftware(WireModel):
    status: Literal["found"] = "found"
    matches: list[SoftwareMatch] = Field(
        min_length=1,
        max_length=5,
        description="Every project the name could mean. More than one means the person chooses. "
        "A match is a guess from a reviewed list, never a certainty.",
    )


class SoftwareNotKnown(WireModel):
    status: Literal["not_known"] = "not_known"
    message: str = Field(
        max_length=300,
        description="The list has no such name, or GitHub found none of its projects.",
    )


class SoftwareNotChecked(WireModel):
    status: Literal["not_checked"] = "not_checked"
    message: str = Field(
        max_length=300,
        description="What went wrong with GitHub, in plain words. No project is offered, because "
        "nothing unchecked is shown.",
    )


type FindSoftwareResult = Annotated[
    FoundSoftware | SoftwareNotKnown | SoftwareNotChecked, Field(discriminator="status")
]


type FactSection = Literal["watchlist", "workflows", "needs_you"]


NEWEST_VERSION_LIMIT: Final = 100


class WatchedFact(WireModel):
    name: str = Field(max_length=80)
    repo: str = Field(max_length=140)
    our_version: str | None = Field(
        max_length=40, description="The version the team runs. None means Not known."
    )
    newest_version: str | None = Field(
        max_length=NEWEST_VERSION_LIMIT,
        description="The newest release read from the source. None when unread.",
    )
    state: str = Field(max_length=40, description="The state in the words the Software page shows.")
    checked_at: datetime | None = Field(
        default=None, description="When the software was last checked. None when never."
    )
    open_ticket: str | None = Field(
        default=None, max_length=40, description="The upgrade ticket that is open, if any."
    )
    awaiting_approval: bool = Field(
        default=False, description="True when a ticket for it waits for an Approver's yes."
    )
    problem: str | None = Field(
        default=None, max_length=200, description="Why the last check could not read it."
    )
    our_version_source: Literal["given", "first_check", "ticket_done"] | None = Field(
        default=None, description="How the version the team runs was set. None when not known."
    )
    our_version_ticket: str | None = Field(
        default=None, max_length=40, description="The ticket that moved the version, if any."
    )


class WorkflowFact(WireModel):
    name: str = Field(max_length=80)
    state: Literal["on", "paused"]
    last_run: str | None = Field(
        max_length=40, description="The state of the newest run, in the words the Portal uses."
    )
    last_run_at: datetime | None


class NeedsYouFact(WireModel):
    approvals: int = Field(ge=0)
    confirmations: int = Field(ge=0)
    stopped: int = Field(ge=0)
    connections: int = Field(ge=0)
    addresses: int = Field(ge=0)
    replies: int = Field(ge=0)
    total: int = Field(ge=0, description="The count Home shows under Needs you.")


type WatchDay = Literal[
    "every_day",
    "weekdays",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class WatchlistScheduleFact(WireModel):
    day: WatchDay
    at: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", description="24-hour time, as 09:00.")


class PlannerFacts(WireModel):
    """What the platform holds for the signed-in person at the moment of the question. A section
    that is None was not sent, and the answer may not claim to have looked at it."""

    watchlist: list[WatchedFact] | None = Field(default=None, max_length=100)
    workflows: list[WorkflowFact] | None = Field(default=None, max_length=50)
    needs_you: NeedsYouFact | None = None
    watchlist_schedule: WatchlistScheduleFact | None = Field(
        default=None,
        description="When the Software watchlist checks all its software. None when it is off "
        "or was not read, so a time asked for one software is a cross.",
    )


class PreviousTurn(WireModel):
    """The turn before the one being answered, sent by the Portal with the next typed request."""

    request: str = Field(max_length=2000, description="What the person typed, or the chip's words.")
    software: str | None = Field(
        default=None, max_length=80, description="The software the Planner named in its answer."
    )
    answer: str | None = Field(
        default=None,
        max_length=600,
        description="The text of the Planner's answer, when it had one.",
    )
    kind: str | None = Field(
        default=None,
        max_length=40,
        description="The kind of answer the Planner gave, such as question or watchlist. Client "
        "input: it only decides whether a follow-up applies.",
    )


class AnswerRequest(WireModel):
    task: str = Field(min_length=1, max_length=2000)
    model: ModelAccess
    previous: PreviousTurn | None = Field(
        default=None,
        description="The turn before this one. Context for the question lane only: the Planner "
        "never builds request text from it.",
    )
    facts: PlannerFacts | None = Field(
        default=None,
        description="Read by the platform when the request arrives. Only a question about the "
        "person's own data uses it. Without it, such a question gets the fixed fallback.",
    )


type CantNeed = Literal["new_tool", "new_system"]


class CantRow(WireModel):
    kind: RowKind
    text: str = Field(max_length=200, description="The part the platform can't do, in plain words.")
    note: str = Field(max_length=300, description="Why it can't do it yet.")
    needs: CantNeed | None = Field(
        default=None,
        description="new_tool when the part is in a system the platform already reaches, such "
        "as Jira or GitHub, so a tool would have to be built and the team decides. new_system "
        "when it names a system or source the platform doesn't reach. None for a part the "
        "Planner didn't follow, which names nothing to build.",
    )
    system: str | None = Field(
        default=None,
        max_length=40,
        description="The system the part names, in plain words, such as Jira or email. None "
        "when it names none.",
    )


class SetupCardAnswer(WireModel):
    kind: Literal["setup_card"] = "setup_card"
    name: str = Field(
        min_length=1,
        max_length=60,
        description="The Planner's guess at a name. The Portal shows it as filled in by the "
        "Planner, with Rename.",
    )
    rows: list[UnderstoodRow] = Field(
        min_length=4,
        max_length=8,
        description="One schedule row, then at least one row for what to look for, what to do "
        "and where, in that order. None is cant_do. A time the task doesn't say is missing, "
        "never guessed.",
    )


class PartAnswer(WireModel):
    kind: Literal["part"] = "part"
    name: str = Field(min_length=1, max_length=60)
    rows: list[UnderstoodRow] = Field(
        min_length=4,
        max_length=8,
        description="The part the platform can do, as a card: the request with each part it "
        "can't do swapped for the nearest thing it can, or left for the person to choose.",
    )
    cant: list[CantRow] = Field(
        min_length=1, description="Each part it can't do. Every one needs a new tool."
    )


type Alternative = Annotated[SetupCardAnswer | WatchlistAnswer, Field(discriminator="kind")]


class CantAnswer(WireModel):
    kind: Literal["cant"] = "cant"
    cant: list[CantRow] = Field(min_length=1, description="Each part the platform can't do.")
    alternative: Alternative | None = Field(
        default=None,
        description="The nearest thing the Planner can set up, with every part checked. None "
        "when nothing comes close, so the only next step is Ask the team.",
    )


class WatchlistAnswer(WireModel):
    kind: Literal["watchlist"] = "watchlist"
    word: str = Field(
        min_length=1,
        max_length=80,
        description="The word that made the Planner think so, as the task wrote it.",
    )
    software: str | None = Field(
        default=None, max_length=80, description="The software the task names, as it wrote it."
    )
    also: (
        Annotated[SetupCardAnswer | PartAnswer | CantAnswer, Field(discriminator="kind")] | None
    ) = Field(
        default=None,
        description="The rest of a request that also asks for a workflow, such as a weekly "
        "ticket list, offered next. None when the request is only about the software.",
    )


CantAnswer.model_rebuild()


class WhichSoftwareAnswer(WireModel):
    kind: Literal["which_software"] = "which_software"
    word: str = Field(min_length=1, max_length=80)


class RefusedAnswer(WireModel):
    kind: Literal["refused"] = "refused"
    reason: Literal["skip_approval"] = "skip_approval"
    said: str = Field(
        max_length=200,
        description="The words that asked to skip a yes, as the request wrote them, so the "
        "refusal names the part. Empty only when the model said so without quoting them.",
    )
    rest: str = Field(
        max_length=2000,
        description="The request without the words that asked to skip a yes, so it can be set "
        "up with one. Empty when nothing is left.",
    )


class CheckWorkflowsAnswer(WireModel):
    kind: Literal["check_workflows"] = "check_workflows"
    workflow_words: str | None = Field(
        default=None,
        max_length=80,
        description="The words of the task that name one workflow, as it wrote them. The "
        "platform matches them to a workflow. None when the question is about all of them.",
    )


class WhyStoppedAnswer(WireModel):
    kind: Literal["why_stopped"] = "why_stopped"
    workflow_words: str | None = Field(default=None, max_length=80)


class NeedsMeAnswer(WireModel):
    kind: Literal["needs_me"] = "needs_me"


class AbilitiesAnswer(WireModel):
    kind: Literal["abilities"] = "abilities"


class QuestionAnswer(WireModel):
    kind: Literal["question"] = "question"
    text: str = Field(
        min_length=1,
        max_length=600,
        description="The model's own words, from the facts sent and nothing else (ADR 0042).",
    )
    looked_at: list[FactSection] = Field(
        max_length=3,
        description="The sections of the facts the answer used, kept only when they were sent.",
    )
    about_software: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list,
        max_length=3,
        description="The watched software the answer is about, named as the watchlist names "
        "them. Code keeps only names the facts hold and the text mentions (ADR 0042).",
    )


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
    | QuestionAnswer,
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
]


class RequestPart(WireModel):
    """One clause of the request and what the answer does with it (plan 4.1)."""

    text: str = Field(
        max_length=200,
        description="The request's own words: the whole clause, or, in a clause the Planner "
        "partly read, only the words it didn't read.",
    )
    mark: PartMark = Field(
        description="will_do for a part the answer does, cant for one it doesn't, and question "
        "for the one thing the answer asks."
    )
    reason: PartReason | None = Field(
        default=None,
        description="Why, for a cant: not_followed (no rule read it), cant_do (see note), "
        "ask_on_its_own (a question asked beside a request, or a request beside a question), "
        "one_day, one_time or one_frequency (a schedule with two, see choices), own_time (a "
        "time on a watch "
        "request), skip_approval (it asks to skip a yes), with_a_yes (it waits until the "
        "request is set up with a yes), needs_the_rest (it can't run without a part that "
        "can't be done), how_many_days (a question: the words name a span of days but no "
        "number). None for will_do.",
    )
    note: str | None = Field(
        default=None, max_length=300, description="For cant_do, why, in the registry's words."
    )
    choices: list[Annotated[str, Field(max_length=40)]] = Field(
        default_factory=list[str],
        description="For one_day and one_time, each day or time the request named, in its own "
        "words, for the person to choose one.",
    )


class Answered(WireModel):
    status: Literal["answered"] = "answered"
    answer: PlannerAnswer
    parts: list[RequestPart] = Field(
        default_factory=list[RequestPart],
        description="Every clause of the request, in order, with what happened to it. None is "
        "dropped. Thanks and please get no part.",
    )


type AnswerResult = Annotated[Answered | ModelProblem, Field(discriminator="status")]

answer_result_adapter: TypeAdapter[AnswerResult] = TypeAdapter(AnswerResult)


class CheckPartRequest(WireModel):
    kind: RowKind
    text: str = Field(min_length=1, max_length=200)


class PartFits(WireModel):
    state: Literal["fits"] = "fits"


class PartCantDo(WireModel):
    state: Literal["cant_do"] = "cant_do"
    note: str = Field(max_length=300, description="Why it can't do it, in plain words.")
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
    github_check_result: GitHubCheckResult
    tool_list: ToolList
    capability_list: CapabilityList
    card_draft_request: DraftRequest
    card_draft_result: DraftResult
    planner_choose_request: ChooseRequest
    planner_choose_result: ChooseResult
    software_find_request: FindSoftwareRequest
    software_find_result: FindSoftwareResult
    planner_answer_request: AnswerRequest
    planner_answer_result: AnswerResult
    planner_check_part_request: CheckPartRequest
    planner_check_part_result: CheckPartResult
