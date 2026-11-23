from datetime import date, datetime
from typing import Annotated, Any, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)


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


MAVEN_COORDINATE_PATTERN = (
    r"^[A-Za-z0-9_-]{1,60}(?:\.[A-Za-z0-9_-]{1,60}){0,10}:[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$"
)
"""groupId:artifactId. The group's dots become folders in the registry's address, so no part
may be empty, and the artifact never starts with a dot."""
NPM_PACKAGE_PATTERN = r"^(?:@[a-z0-9~-][a-z0-9._~-]{0,100}/)?[a-z0-9~-][a-z0-9._~-]{0,113}$"
"""An npm package name, with or without its @scope, as npm allows it today."""


class MavenSource(WireModel):
    kind: Literal["maven"] = "maven"
    ref: str = Field(
        pattern=MAVEN_COORDINATE_PATTERN,
        description="The package on Maven Central as groupId:artifactId, such as "
        "org.apache.logging.log4j:log4j-core.",
    )


class NpmSource(WireModel):
    kind: Literal["npm"] = "npm"
    ref: str = Field(
        pattern=NPM_PACKAGE_PATTERN,
        description="The package on the npm registry, such as express or @angular/core.",
    )


type SoftwareSource = Annotated[GithubSource | MavenSource | NpmSource, Field(discriminator="kind")]
type SourceKind = Literal["github", "maven", "npm"]
SOURCE_NAMES: dict[str, str] = {"github": "GitHub", "maven": "Maven Central", "npm": "npm"}
"""How each source is named to people, in messages and tickets (ADR 0025)."""


class SoftwareToCheck(WireModel):
    id: str = Field(pattern=SOFTWARE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    source: SoftwareSource
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
    tool: CardToolId | None = Field(
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

type Severity = Literal["critical", "high", "medium", "low", "unknown"]
type VulnerabilitySource = Literal["OSV", "NVD"]
type VulnerabilityCheck = Literal["not_checked", "checked", "could_not_check"]

URGENT_SCORE = 9.0
"""A known vulnerability scored this high or more makes the upgrade ticket urgent (ADR 0025)."""


class Vulnerability(WireModel):
    """One known vulnerability in the version the team runs, merged across sources by CVE."""

    id: str = Field(
        min_length=1,
        max_length=60,
        description="The CVE number when there is one, such as CVE-2021-44228, otherwise the "
        "advisory's own id, such as GHSA-jfh8-c2jp-5v3q.",
    )
    severity: Severity = Field(
        description="From NVD's CVSS score when NVD answered, otherwise from the advisory. "
        "unknown when neither said."
    )
    score: float | None = Field(
        default=None, ge=0, le=10, description="NVD's CVSS base score. None when NVD was not read."
    )
    summary: str = Field(default="", max_length=200, description="One line about the flaw.")
    fixed_in: str | None = Field(
        default=None, description="The lowest version the advisory says fixes it, when it says."
    )
    reported_by: list[VulnerabilitySource] = Field(
        min_length=1, description="Which sources reported it, so an Approver can check them."
    )
    url: str = Field(description="The record an Approver can open: NVD for a CVE, else OSV.")

    @property
    def urgent(self) -> bool:
        return self.severity == "critical" or (self.score or 0) >= URGENT_SCORE


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
    vulnerability_check: VulnerabilityCheck = Field(
        default="not_checked",
        description="Whether known vulnerabilities in our version were looked up. not_checked "
        "for a GitHub source, which names no package, and when our version is not known. "
        "could_not_check when OSV did not answer, so an empty list never reads as safe.",
    )
    vulnerabilities: list[Vulnerability] = Field(
        default_factory=list[Vulnerability],
        description="Known vulnerabilities in our version, worst first. Empty unless checked.",
    )
    vulnerabilities_complete: bool = Field(
        default=True,
        description="False when OSV listed more than one check reads, so vulnerabilities holds "
        "only the first of them and there are more. True when the list is all OSV has, or when "
        "nothing was checked.",
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
    id: CardToolId
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
type ConnectionId = Literal["jira", "github", "teams", "confluence"]
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
    short: str | None = Field(
        default=None,
        description="The capability in a few words, as the chat's capabilities card names it: one "
        "of its lines when it is ready, a name in its Not yet note when it isn't. None for one the "
        "card leaves out.",
    )
    instead: str | None = Field(
        default=None,
        description="For one that isn't ready, what the person has instead, in one sentence, as a "
        "can't card says it under its head. None when it is ready, or when nothing comes close.",
    )


class ExampleSpec(WireModel):
    text: str
    kind: ExampleKind
    needs: list[str] = Field(description="The ids of the capabilities the example uses.")


class KeyShapes(WireModel):
    """The shapes of keys the masker knows, as regular expressions. platform-api refuses each
    of them in a person's words, answers and what comes back from n8n (ADR 0051)."""

    shapes: list[str]


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
    tools: list[CardToolId] = Field(default_factory=list[CardToolId])


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
type WatchPart = Literal["schedule", "ticket"]


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
    kind: SourceKind = Field(
        default="github",
        description="Where the software is published: github for a GitHub project, maven or npm "
        "for a package on that registry (ADR 0025).",
    )
    repo: str = Field(
        max_length=214,
        description="The software at its source, checked just now: a GitHub project as "
        "owner/name at the address GitHub gives it now, a Maven package as groupId:artifactId, "
        "or an npm package name.",
    )

    @model_validator(mode="after")
    def _fits_its_kind(self) -> SoftwareMatch:
        """The name must be one its source could hold, as the watchlist would save it."""
        match self.kind:
            case "github":
                GithubSource(ref=self.repo)
            case "maven":
                MavenSource(ref=self.repo)
            case "npm":
                NpmSource(ref=self.repo)
        return self

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


class ReadReleasesRequest(WireModel):
    repo: RepoName = Field(description="The public GitHub repository, as owner/name.")
    tag_pattern: TagPattern


class ReleaseRead(WireModel):
    tag: str
    name: str | None
    published_at: str | None


class ReleasesRead(WireModel):
    status: Literal["read"] = "read"
    releases: list[ReleaseRead] = Field(
        max_length=30,
        description="The repository's stable releases that the tag rule counts, newest first, "
        "as GitHub lists them. Empty when it has none.",
    )


class ReleasesNotRead(WireModel):
    status: Literal["not_read"] = "not_read"
    message: str = Field(max_length=300, description="What went wrong with GitHub, in plain words.")
    retryable: bool = Field(description="True when trying again later may work.")


type ReadReleasesResult = Annotated[ReleasesRead | ReleasesNotRead, Field(discriminator="status")]


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


WORKFLOW_FACTS: Final = 50
OTHER_WORKFLOWS: Final = 250
"""At the 80-character limit, 250 names are about 21 KB of the question's facts, less than a full
watchlist section. Past it the facts count the names left out, and the Planner says it read only
some."""

type WorkflowName = Annotated[str, StringConstraints(max_length=80)]


class WorkflowFact(WireModel):
    name: WorkflowName
    state: Literal["draft", "on", "paused"]
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
    declined: int = Field(ge=0, description="The person's own test runs an Approver declined.")
    questions: int = Field(
        ge=0, description="Questions Approvers asked the person on requests waiting for a yes."
    )
    total: int = Field(
        ge=0, description="The count Home shows under Needs you, the sum of the counts above."
    )


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


CLOCK_PATTERN: Final = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
SOFTWARE_LIMIT: Final = 80
"""The longest software name one turn hands the next (`previous.software`)."""


class WatchlistScheduleFact(WireModel):
    day: WatchDay
    at: str = Field(pattern=CLOCK_PATTERN, description="24-hour time, as 09:00.")


class PlannerFacts(WireModel):
    """What the platform holds for the signed-in person at the moment of the question. A section
    that is None was not sent, and the answer may not claim to have looked at it."""

    watchlist: list[WatchedFact] | None = Field(default=None, max_length=100)
    workflows: list[WorkflowFact] | None = Field(default=None, max_length=WORKFLOW_FACTS)
    other_workflows: list[WorkflowName] | None = Field(
        default=None,
        max_length=OTHER_WORKFLOWS,
        description="The names of the person's other workflows, sent when they have more than "
        "the workflows above. Their state and last run were not read.",
    )
    left_out_workflows: int | None = Field(
        default=None,
        gt=0,
        description="How many more workflows the person has whose names were not sent at all, "
        "to keep the facts short. None when every name was sent.",
    )
    needs_you: NeedsYouFact | None = None
    watchlist_schedule: WatchlistScheduleFact | None = Field(
        default=None,
        description="When the Software watchlist checks all its software. None when it is off "
        "or was not read, so a time asked for one software is a cross.",
    )
    watchlist_project: str | None = Field(
        default=None,
        max_length=40,
        description="The Jira project the Software watchlist raises its upgrade tickets in. None "
        "when it was not read, so a ticket asked for in any named project is not its own.",
    )

    def workflow_names(self) -> list[str]:
        """Every workflow's name the platform sent, those with a last run and the others."""
        return [w.name for w in self.workflows or []] + list(self.other_workflows or [])

    def workflows_in_all(self) -> int:
        """How many workflows the person has, named in the facts or not."""
        return len(self.workflow_names()) + (self.left_out_workflows or 0)


class PreviousTurn(WireModel):
    """The turn before the one being answered, sent by the Portal with the next typed request."""

    request: str = Field(max_length=2000, description="What the person typed, or the chip's words.")
    software: str | None = Field(
        default=None,
        max_length=SOFTWARE_LIMIT,
        description="The one software the Planner named in its answer, or for a free reply the "
        "one its request named, which must be in the request's words. Client input: a message "
        "that only asks to watch it, such as keep track of it, gets the offer to watch this "
        "software, which the person must tap.",
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


class TurnTrace(WireModel):
    """Where the turn is traced (ADR 0050). The platform makes it. The runtime traces only when
    its own tracing is on."""

    id: str = Field(
        pattern=r"^[0-9a-f]{32}$",
        description="The turn's trace id, 32 lowercase hex digits. The platform makes a new one "
        "for each typed message.",
    )
    chat: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f-]{1,36}$",
        description="The Portal's chat, which groups its turns into one session.",
    )
    person: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="A pseudonym for the person: an HMAC-SHA256 of their platform id. Never "
        "their email or name.",
    )


class AnswerRequest(WireModel):
    task: str = Field(min_length=1, max_length=2000)
    model: ModelAccess
    trace: TurnTrace | None = Field(
        default=None, description="Where the turn is traced. None leaves it untraced."
    )
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
    changes_workflows: bool = Field(
        default=True,
        description="False when the person asking can't change workflows, as an Approver who "
        "isn't an Operator: a change beside a question is crossed, and the question still gets "
        "its answer (plan 3.2).",
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
    instead: str | None = Field(
        default=None,
        max_length=200,
        description="What the person has instead, in one sentence, from the registry entry the "
        "part asks for. With it, the note is that entry's one-line can't. None when no entry with "
        "those words fits the part.",
    )
    unsupported: bool = Field(
        default=False,
        description="True when the platform won't do the part at all, so there is nothing to ask "
        "the team for.",
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
    also: (
        Annotated[SetupCardAnswer | PartAnswer | CantAnswer, Field(discriminator="kind")] | None
    ) = Field(
        default=None,
        description="The rest of a request that also asks for another workflow, as a ticket "
        "list beside one software's release check, offered after this card. None when the "
        "card holds the whole request.",
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
    covers: list[WatchPart] = Field(
        default_factory=list[WatchPart],
        description="The parts of the request past the software that the Software watchlist "
        "does itself: schedule when it names the day or time the watchlist already runs on, "
        "ticket when it asks for the upgrade ticket the watchlist raises after a yes. Empty "
        "beside `also`, whose card holds the rest of the request.",
    )


CantAnswer.model_rebuild()
SetupCardAnswer.model_rebuild()


class WhichSoftwareAnswer(WireModel):
    kind: Literal["which_software"] = "which_software"
    word: str = Field(min_length=1, max_length=80)


class RefusedAnswer(WireModel):
    kind: Literal["refused"] = "refused"
    reason: Literal["skip_approval"] = "skip_approval"
    said: str = Field(
        max_length=200,
        description="The words that asked to skip a yes, as the request wrote them, so the "
        "refusal names the part.",
    )
    rest: str = Field(
        max_length=2000,
        description="The request without the words that asked to skip a yes, so it can be set "
        "up with one. Empty when nothing is left, or when the rest is nothing the platform can "
        "set up: then the parts say why.",
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
    how_to_start: bool = Field(
        default=False,
        description='True when the request asks how to start using the app, as "help" or '
        '"list the steps". The Portal then leads with the steps, not the list of what it can do.',
    )


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


type ReplyForm = Literal["answer", "clarify", "cant"]

REPLY_TEXT_LIMIT: Final = 600
CHOICE_LIMIT: Final = 40


class ReplyEnvelope(BaseModel):
    """What the model fills for a free reply (ADR 0047). It is loose on purpose: the guard's checks,
    not the parser, decide whether it can be shown, so a broken rule counts as a reject."""

    model_config = ConfigDict(extra="ignore")

    form: ReplyForm = Field(
        description="answer: answer it from the guide, the capabilities or the facts. clarify: "
        "a request too vague to act on, settled by one short question. cant: it asks for "
        "something the platform can't do."
    )
    text: str = Field(
        description="Plain words, at most 600 characters. No Markdown, list, link or HTML. A "
        "clarify ends with a question mark."
    )
    choices: list[str] = Field(
        default_factory=list[str],
        description="For clarify only: 2 to 4 replies the person can tap, each 2 to 5 words and "
        "never more than 40 characters, in their own voice.",
    )
    offer: str | None = Field(
        default=None,
        description="For cant only: the id of the one Ready capability that comes closest, or "
        "null when none does.",
    )
    looked_at: list[str] = Field(
        default_factory=list[str],
        description="The sections of the facts you used: watchlist, workflows, needs_you.",
    )


class ReplyOffer(WireModel):
    """The button on a free reply's can't. It sends the registry's example request for the
    closest Ready capability as the person's next message, so the Planner reads it again and any
    write it sets up still waits for a yes (ADR 0047)."""

    capability: str = Field(description="The id of a Ready capability in the registry.")
    request: str = Field(
        min_length=1, max_length=2000, description="The registry's example request it sends."
    )


type AboutSection = Literal["watchlist", "workflows"]
ABOUT_LIMIT: Final = 5


class ReplyAbout(WireModel):
    """One watched software or workflow a free reply speaks of. Code keeps it only when the facts
    hold the name, spelled as they spell it, and the Portal draws its state line from its own data,
    so the reply never has to state a version, a state or a run (ADR 0049)."""

    section: AboutSection
    name: str = Field(min_length=1, max_length=80)


class FreeReplyAnswer(WireModel):
    """The model's own reply to a message no other answer fits, shown only after code checked it
    (ADR 0047). It writes nothing: a choice or an offer is sent as the person's next message."""

    kind: Literal["reply"] = "reply"
    form: ReplyForm = Field(
        description="answer: a direct answer. clarify: one short question, with choices to tap. "
        "cant: an honest can't, with the closest thing the platform can do as a button."
    )
    text: str = Field(min_length=1, max_length=REPLY_TEXT_LIMIT, description="Plain words only.")
    choices: list[Annotated[str, Field(min_length=1, max_length=CHOICE_LIMIT)]] = Field(
        default_factory=list[str],
        max_length=4,
        description="For clarify only, 2 to 4 replies to tap. Each is sent as the next message.",
    )
    offer: ReplyOffer | None = Field(
        default=None,
        description="For cant only. None on a can't means the button is Ask the team.",
    )
    looked_at: list[FactSection] = Field(
        default_factory=list[FactSection],
        max_length=3,
        description="The sections of the facts the reply used, kept only when they were sent.",
    )
    about: list[ReplyAbout] = Field(
        default_factory=list[ReplyAbout],
        max_length=ABOUT_LIMIT,
        description="The watched software and workflows the reply names, each kept only when the "
        "facts hold it. The Portal draws each one's state line. Left out when empty, so a reply "
        "that names none reads as it did before ADR 0049.",
        exclude_if=lambda about: not about,
    )
    software: str | None = Field(
        default=None,
        max_length=SOFTWARE_LIMIT,
        description="The one software the message named, as it wrote it: code finds the "
        "reading's software in the message's words, never in the reply. The Portal sends it back "
        "as previous.software, so a next message such as keep track of it means it. Left out "
        "when none.",
        exclude_if=lambda software: software is None,
    )

    @model_validator(mode="after")
    def _form_fits(self) -> FreeReplyAnswer:
        if (self.form == "clarify") != (len(self.choices) >= 2) or (
            self.form != "clarify" and self.choices
        ):
            raise ValueError("Only a clarifying question has choices, 2 to 4 of them")
        if self.offer is not None and self.form != "cant":
            raise ValueError("Only a can't offers something instead")
        return self


class DidntFollowAnswer(WireModel):
    """The fixed fallback for a free reply that failed or that the guard rejected: one line on
    what the Planner can do for this person, and Say it another way. Never a bare cross."""

    kind: Literal["didnt_follow"] = "didnt_follow"


class _OnOrOff(WireModel):
    workflow_words: str | None = Field(
        default=None,
        max_length=80,
        description="The words of the request that name the workflow, as it wrote them. The "
        'platform matches them to one of the person\'s workflows by whole words. None for "it", '
        "so the person picks one.",
    )
    software: str | None = Field(
        default=None,
        max_length=80,
        description='The software those words name, as "the React check" names React. None when '
        "they name none.",
    )


class PauseAnswer(_OnOrOff):
    """A request to pause one of the person's workflows, and nothing else."""

    kind: Literal["pause"] = "pause"


class ResumeAnswer(_OnOrOff):
    """A request to turn a paused workflow back on, and nothing else."""

    kind: Literal["resume"] = "resume"


type EditCant = Literal["only_schedule", "how_often"]


class ScheduleChange(WireModel):
    """When a request asks a workflow it names to run, in the schedule's own terms. A part it
    doesn't name is None, so the saved one stays."""

    day: WatchDay | None = Field(default=None, description="The day it asks for, if it names one.")
    weekly: bool = Field(
        default=False,
        description="True for once a week with no day named. The saved day stays when it is one "
        "day of the week, and the person picks one when it isn't.",
    )
    at: str | None = Field(
        default=None, pattern=CLOCK_PATTERN, description="The time it asks for, 24-hour, as 09:00."
    )
    hour: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description='An hour it names with no am or pm, as "at 9", which could be morning or '
        "evening, so the person picks one. Never guessed.",
    )
    time_unclear: bool = Field(
        default=False,
        description='A time it names that the schedule can\'t read, as "in the afternoon" or "an '
        'hour later": the person picks one. Never guessed.',
    )

    @model_validator(mode="after")
    def _one_of_each(self) -> ScheduleChange:
        if self.day is not None and self.weekly:
            raise ValueError("A day named is not weekly with no day")
        if sum((self.at is not None, self.hour is not None, self.time_unclear)) > 1:
            raise ValueError("A time is named once")
        return self


class EditAnswer(WireModel):
    kind: Literal["edit"] = "edit"
    workflow_words: str | None = Field(
        default=None,
        max_length=80,
        description="The words of the request that name the workflow to change, as it wrote "
        "them. The platform matches them to one of the person's workflows by whole words. None "
        'when the request names none, as "make it daily".',
    )
    software: str | None = Field(
        default=None,
        max_length=80,
        description='The software those words name, as "the React check" names React, so the '
        "platform can tell the Software watchlist's check of it. None when they name none.",
    )
    schedule: ScheduleChange | None = Field(
        default=None,
        description="When it should run. None when the request asks for no change to when it "
        "runs, or for one the schedule can't hold.",
    )
    cant: EditCant | None = Field(
        default=None,
        description="only_schedule: it asks for a change other than when the workflow runs, "
        "such as renaming it, or pausing it beside another change, which the chat can't make "
        "yet. A pause or a resume alone is its own answer. how_often: it asks for "
        "a frequency the schedule can't hold, such as monthly. None when the change can be made.",
    )
    holds_save: bool = Field(
        default=False,
        description="True when the new schedule names two days, two times or two frequencies. "
        "Nothing can be saved until the person asks again without the part with a cross.",
    )
    leaves_out_days: bool = Field(
        default=False,
        description="With how_often: True when the request leaves out a day, or words that look "
        "like a day or time off, as 'skip Fridays', 'except PH' or 'except when I'm on leave', "
        "which no schedule can hold. The Portal then says it can't leave days out, whatever words "
        "the cross holds. False for a frequency it can't hold, as monthly.",
    )

    @model_validator(mode="after")
    def _a_cant_proposes_nothing(self) -> EditAnswer:
        if self.cant is not None and (self.schedule is not None or self.holds_save):
            raise ValueError("An edit the chat can't make proposes no schedule")
        if self.leaves_out_days and self.cant != "how_often":
            raise ValueError("Only a schedule it can't hold leaves out days")
        return self


SOFTWARE_NAME_LIMIT: Final = 80


class RemoveSoftwareAnswer(WireModel):
    """A request to take one software off the Software watchlist. The platform shows each name in
    watched_as with the Software page's own Remove, with its Undo. It is a setting of the
    platform: nothing outside it is written, so no Approver is asked."""

    kind: Literal["remove_software"] = "remove_software"
    software: str = Field(
        min_length=1,
        max_length=SOFTWARE_NAME_LIMIT,
        description="The software's name as the request wrote it.",
    )
    watched_as: list[Annotated[str, Field(max_length=SOFTWARE_NAME_LIMIT)]] = Field(
        default_factory=list[str],
        max_length=100,
        description="Each name in the facts' watchlist that is this software, with case, spaces, "
        "dots and hyphens aside, so node js is Node.js. Empty when the watchlist holds none.",
    )


class ExplainAnswer(WireModel):
    """A request to explain a workflow the person has (ADR 0051). The platform matches the words
    to one of the person's workflows and shows its report. It changes nothing, so both roles may
    ask."""

    kind: Literal["explain"] = "explain"
    workflow_words: str | None = Field(
        default=None,
        max_length=80,
        description="The workflow's name as stored when the request says all of it, which "
        'always fits, else the request\'s own words for part of it, as "the weekly summary". '
        'None for "explain it", so the Portal explains the workflow in focus.',
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
        "number), only_schedule (a change to a workflow other than when it runs, which the "
        "chat can't make yet), how_often (a frequency the schedule can't hold, such as "
        "monthly), which_software (a watch of more than one thing, as 'track them', that names "
        "no software). None for will_do.",
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


type ExplainKind = Literal["runs", "reads", "writes", "posts", "changes"]

EXPLAIN_WORDING_LIMIT: Final = 1200
EXPLAIN_TEXT_LIMIT: Final = 700


class ExplainFact(WireModel):
    """One fact of a workflow's In short (ADR 0051): when it runs, a place it reads, a write or a
    post code's wording says after "It", or the closing "It changes nothing"."""

    kind: ExplainKind
    together: list[Annotated[str, Field(min_length=1, max_length=EXPLAIN_WORDING_LIMIT)]] = Field(
        min_length=1,
        max_length=12,
        description="The words and quoted values code's wording keeps in one sentence for this "
        'fact, as ["day", "8:00"] or ["GitHub", "fastapi/fastapi"]. A quoted value is given '
        "without its quotes.",
    )
    negated: bool = Field(description="True when code's words for this fact hold a negation.")


class ExplainWordingRequest(WireModel):
    """Code's In short for one workflow, to be reworded so it reads naturally. The model may only
    smooth the wording: anything in doubt keeps code's."""

    model: ModelAccess
    wording: str = Field(
        max_length=EXPLAIN_WORDING_LIMIT,
        description="Code's In short as one string, each quoted value in curly quotes.",
    )
    facts: list[ExplainFact] = Field(max_length=40)


class ExplainReworded(WireModel):
    kind: Literal["reworded"] = "reworded"
    text: str = Field(
        max_length=EXPLAIN_TEXT_LIMIT,
        description="The In short as the model reworded it, as the person sees it. It passed every "
        "check and the verifier.",
    )


class ExplainKept(WireModel):
    kind: Literal["kept"] = "kept"
    why: str = Field(
        description="Why code's wording stays: the id of the check that failed, the verifier's "
        "flag, or call when the model's call failed.",
    )


type ExplainWordingResult = ExplainReworded | ExplainKept | ModelProblem

explain_wording_result_adapter: TypeAdapter[ExplainWordingResult] = TypeAdapter(
    ExplainWordingResult
)


# The workflow drafter (ADR 0051): a person's words in, a plan of n8n blocks out.

PLAN_NAME_LIMIT: Final = 80
BLOCK_NAME_LIMIT: Final = 60
SETTING_ID_PATTERN: Final = r"^[a-z][a-z0-9_]{0,39}$"

type SettingKind = Literal[
    "run_time", "jira_project", "channel", "address", "repository", "confluence_page", "text"
]
"""What a setting holds. A run time, a Jira project, and a channel or an address a notice posts
to are never guessed (ADR 0051, section 5)."""
type SettingMark = Literal["filled", "guessed", "needed"]


class WriteKeyFact(WireModel):
    """A write key an Operator added in Settings: its name and the system it writes to. Never its
    secret."""

    name: str = Field(min_length=1, max_length=80)
    system: str = Field(min_length=1, max_length=40)


class DrafterFacts(WireModel):
    """The team's facts the drafter may use. No Approver's name and no secret."""

    jira_projects: list[Annotated[str, Field(max_length=20)]] = Field(
        default_factory=list[str], max_length=100, description="The allowed Jira projects."
    )
    confluence_pages: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list[str], max_length=100, description="The allowed Confluence pages."
    )
    repositories: list[RepoName] = Field(
        default_factory=list[str], max_length=100, description="The allowed repositories."
    )
    channels: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list[str],
        max_length=200,
        description="The Slack channels the platform's key can see, when the platform has read "
        "them. A channel the person names counts as filled only when it is here.",
    )
    agent_cards: list[LibraryCard] = Field(default_factory=list[LibraryCard], max_length=50)
    write_keys: list[WriteKeyFact] = Field(default_factory=list[WriteKeyFact], max_length=50)


class PlanBlock(WireModel):
    name: str = Field(min_length=1, max_length=BLOCK_NAME_LIMIT)
    type: str = Field(min_length=1, max_length=120)
    version: float
    parameters: dict[str, Any] = Field(
        description="As n8n holds them. A setting stands in a value as its placeholder, "
        "<<setting id>>, never as a guessed value."
    )


class PlanWire(WireModel):
    from_block: str
    exit: str = Field(description='The exit\'s name, as "main", "true" or "Yes".')
    to_block: str
    exit_index: int = Field(ge=0, description="The exit's place in n8n's outputs of from_block.")
    input_index: int = Field(ge=0, description="The input of to_block it joins.")


class SettingPlace(WireModel):
    block: str
    parameter: str = Field(description='The parameter\'s path in the block, as "channelId".')


class PlanSetting(WireModel):
    id: str = Field(pattern=SETTING_ID_PATTERN)
    kind: SettingKind
    label: str = Field(min_length=1, max_length=80)
    fills: list[SettingPlace] = Field(min_length=1)
    value: str | None = Field(
        description="A run time is code's reading, as monday 09:00, or the person's own words "
        "for one code can't read. None while it is needed, except a run time still needed for "
        "want of a time, which keeps the day the words name, as monday."
    )
    mark: SettingMark = Field(
        description="filled: code found it in the person's words, and for a kind that is never "
        "guessed, in the team's facts too. guessed: the drafter picked it. needed: nobody has "
        "given it."
    )


class WorkflowPlan(WireModel):
    """A drafted workflow as the drafter planned it and code checked it against the catalogue.
    The builder lays it out as an n8n workflow and adds what every layout adds."""

    name: str = Field(min_length=1, max_length=PLAN_NAME_LIMIT)
    blocks: list[PlanBlock] = Field(min_length=1)
    wires: list[PlanWire]
    settings: list[PlanSetting]


class WorkflowDraftRequest(WireModel):
    words: str = Field(
        min_length=1,
        max_length=2000,
        description="The person's words, unchanged. For an edit, the words that ask for it.",
    )
    facts: DrafterFacts
    current: WorkflowPlan | None = Field(
        default=None,
        description="For an edit, the plan as it stands, with each setting's value. The drafter "
        "returns a whole new plan, and a setting with the same id and kind keeps its value unless "
        "the words change it.",
    )
    model: ModelAccess


type ProblemCode = Literal[
    "unreadable",
    "name",
    "too_big",
    "no_block",
    "no_version",
    "no_resource",
    "no_operation",
    "no_parameter",
    "bad_value",
    "missing_value",
    "held",
    "hidden",
    "left_out",
    "community",
    "platform_adds",
    "cant_run",
    "native_write",
    "address_unread",
    "guessed",
    "wire",
    "setting",
]
INVENTED_CODES: Final[frozenset[ProblemCode]] = frozenset(
    {"no_block", "no_version", "no_resource", "no_operation", "no_parameter"}
)
"""A plan sent back for one of these named something the pinned n8n image doesn't have."""


class PlanProblem(WireModel):
    code: ProblemCode
    block: str | None = None
    text: str = Field(description="What is wrong, in words the drafter can act on.")


class SentBack(WireModel):
    """One plan the catalogue check sent back to the drafter, and why."""

    problems: list[PlanProblem] = Field(min_length=1)


COULDNT_DRAFT: Final = "I couldn't draft that."
KEY_PASTED: Final = "Don't paste keys here. An Operator adds keys in Settings."


class WorkflowDrafted(WireModel):
    status: Literal["drafted"] = "drafted"
    plan: WorkflowPlan
    catalogue: str = Field(description="The n8n image, with its digest, the plan was checked by.")
    sent_back: list[SentBack] = Field(description="The plans the check sent back first.")
    turns: int = Field(ge=1, description="The model's turns.")


type NotDraftedWhy = Literal["gave_up", "no_tool_call", "too_long", "failed"]


class WorkflowNotDrafted(WireModel):
    """Nothing is shown as working: the person sees "I couldn't draft that", with Ask the team."""

    status: Literal["not_drafted"] = "not_drafted"
    why: NotDraftedWhy = Field(
        description="gave_up: no plan passed the check after it went back three times. "
        "no_tool_call: the model answered without a tool. too_long: it ran out of turns or time. "
        "failed: the platform's own code failed while it answered a tool, so it stopped."
    )
    message: str = COULDNT_DRAFT
    catalogue: str
    sent_back: list[SentBack]
    turns: int = Field(ge=0)


class KeyPasted(WireModel):
    """Something the drafter would read holds the shape of a key: the words, the team's facts or
    the current plan. So no model read any of it (ADR 0051, section 5)."""

    status: Literal["key_pasted"] = "key_pasted"
    message: str = KEY_PASTED


type WorkflowDraftResult = Annotated[
    WorkflowDrafted | WorkflowNotDrafted | KeyPasted | ModelProblem,
    Field(discriminator="status"),
]

workflow_draft_result_adapter: TypeAdapter[WorkflowDraftResult] = TypeAdapter(WorkflowDraftResult)


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
    releases_read_request: ReadReleasesRequest
    releases_read_result: ReadReleasesResult
    planner_answer_request: AnswerRequest
    planner_answer_result: AnswerResult
    planner_check_part_request: CheckPartRequest
    planner_check_part_result: CheckPartResult
    workflow_explain_request: ExplainWordingRequest
    workflow_explain_result: ExplainWordingResult
    workflow_draft_request: WorkflowDraftRequest
    workflow_draft_result: WorkflowDraftResult
