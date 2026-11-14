import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, StringConstraints, field_validator

from platform_api.builder.templates import VERSION_PATTERN
from platform_api.orchestration import (
    AT_PATTERN,
    Day,
    InputKind,
    RowKind,
    RowState,
    ScheduleHold,
    Status,
    ToolId,
    ToolKind,
)
from platform_api.shared import ApprovalId, RunId, SoftwareId, UserId
from platform_api.wire import FailureReason as FailureReasonName
from platform_api.wire import RepoName, WireIn, WireModel
from platform_api.wire import RunOutcome as RunOutcomeName
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


class CreateUseCase(WireIn):
    template: str
    name: str
    instruction: str
    params: dict[str, str]


type N8nBlockKind = Literal[
    "schedule",
    "start",
    "manual",
    "error",
    "read",
    "agent",
    "propose",
    "ask",
    "write",
    "tell",
    "report",
    "branch",
    "merge",
    "end",
    "other",
]


class N8nExitView(WireModel):
    exit: str | None = Field(
        description="Which way out: true or false for an IF, the name of an Ask for a yes exit "
        "(No answer, Yes, No, Nothing to change), or null for a block with one way out."
    )
    to: str = Field(description="The block it leads to, by name.")


class N8nBlockView(WireModel):
    name: str = Field(description="The block's name, as n8n, the canvas and the run line show it.")
    kind: N8nBlockKind = Field(
        description="What the block does: schedule, start (Start from the Portal), manual and "
        "error start a run; read, agent, propose, ask (Ask for a yes), write (Make the approved "
        "changes), tell and report are our blocks; branch (IF), merge and end (No Op) are n8n's; "
        "other is a block that is not on the allow list."
    )
    next: list[N8nExitView] = Field(description="Where each of its exits leads.")


type BuildLineKind = Literal["status", "check", "note"]


class BuildLineView(WireModel):
    at: AwareDatetime = Field(
        description="When it happened, for replaying the lines with their real gaps."
    )
    kind: BuildLineKind = Field(
        description="status: what the builder was doing. check: a check that passed. note: what "
        "the safety checker changed."
    )
    text: str


class UseCaseCreated(WireModel):
    use_case_id: str
    version: int
    n8n_workflow_id: str | None = Field(
        default=None,
        description="The workflow of its own that holds it in n8n, saved as a draft. Null when "
        "this platform does not lay workflows out in n8n.",
    )
    grade: Literal["safe", "writes_refused", "needs_a_fix"] | None = Field(
        default=None,
        description="The safety checker's grade of the draft. Only a safe draft is saved, so it "
        "is safe whenever there is a draft.",
    )
    build_log: list[BuildLineView] = Field(
        default_factory=list[BuildLineView],
        description="What happened while it was laid out in n8n, in order, in the set-up card's "
        "words. Empty with no draft in n8n.",
    )
    blocks: list[N8nBlockView] = Field(
        default_factory=list[N8nBlockView],
        description="The draft's blocks in the order a run meets them. Empty with no draft in n8n.",
    )


class UseCaseAgentView(WireModel):
    card_id: str
    card_version: int
    name: str
    values: dict[str, str]


type UseCaseState = Literal["draft", "on", "paused"]

type ClockTime = Annotated[str, Field(pattern=AT_PATTERN, examples=["09:00"])]


class UseCaseSchedule(WireModel):
    day: Day
    at: ClockTime
    time_zone: str
    owner_name: str = Field(
        description="The name of the schedule owner. Its scheduled runs start as them."
    )
    held: ScheduleHold | None = Field(
        default=None,
        description="Why the schedule starts no run: owner_removed when the owner has left the "
        "People list, owner_not_an_operator when they are no longer an Operator. An Operator "
        "takes it over by saving it again. Null while the owner can run it.",
    )


class LastRunView(WireModel):
    run_id: RunId
    state: RunStateName
    at: AwareDatetime = Field(description="When the run started.")
    test: bool = Field(
        description="True when a person started it with Do a test run. False for Run now, a "
        "check of the watchlist and a run its schedule started."
    )
    declined_by: UserId | None = Field(
        description="Who declined it. Null unless the run was declined."
    )
    decline_reason: str | None = Field(
        description="Why it was declined, when the Approver gave a reason. Null otherwise."
    )
    approved_by: list[UserId] = Field(
        description="Who said yes to its request, in step order. On a declined run, those who "
        "said yes before it was declined. Empty when nobody did."
    )
    proposed: int = Field(
        description="How many writes the run asked a yes for. Counted only while the run waits "
        "for a yes or after it was declined. 0 for a run that finished or stopped."
    )
    written: int = Field(description="How many writes the run made. 0 if none.")
    tickets: bool = Field(
        description="True when each of those writes is a ticket, so the Portal can say tickets "
        "rather than changes."
    )
    you_can_decide: bool = Field(
        description="True when the person asking may decide the yes this run waits for. False "
        "for any other run, and in an answer that is not for a person."
    )
    retryable: bool = Field(description="True when the run stopped and a retry may start it again.")
    reason: FailureReasonName | None = Field(
        description="Why a stopped run stopped. Null for any other run."
    )
    outcome: RunOutcomeName | None = Field(
        default=None,
        description="How a finished run ended: written, nothing_to_write, or test_passed for a "
        "test run that stopped before the yes and wrote nothing. Null until it succeeded.",
    )


class UseCaseView(WireModel):
    use_case_id: str
    version: int
    template: str
    name: str
    instruction: str
    params: dict[str, str]
    owner: UserId
    created_at: datetime
    state: UseCaseState = Field(
        description="on, paused until an Operator resumes it, or draft until an Operator turns "
        "it on (ADR 0044). A paused workflow starts no run, on its schedule or by hand. A draft "
        "never runs on its schedule, and by hand only a test run, which stops before the yes and "
        "writes nothing. A deleted workflow is not shown."
    )
    next_run_at: datetime | None = Field(
        description="When the workflow next runs on its own. Null while it is a draft, while it "
        "is paused, while its schedule is held because the owner can no longer run it, and for a "
        "workflow with no schedule."
    )
    schedule: UseCaseSchedule | None = Field(
        description="When it runs on its own, and who owns the schedule. Kept while it is a "
        "draft, paused or held. Null for a workflow with no schedule."
    )
    plan: list[BlockView] = Field(
        description="The blocks a run of this use case draws, in order. A template use case "
        "has its template's blocks. An agent use case has one agent block for each agent, "
        "then the approval gate and one write action for each kind of write."
    )
    agents: list[UseCaseAgentView] = Field(
        description="The agents of an agent use case, with the values they run with. "
        "Empty for a template use case."
    )
    last_run: LastRunView | None = Field(
        description="The newest run of this workflow, whatever its state. Null when it has "
        "never run."
    )
    left_out: list[str] = Field(
        description="The parts of the request it was set up without, in the person's own words "
        "(plan 4.6). Text for people to read: nothing runs from it."
    )
    blocks: list[N8nBlockView] = Field(
        default_factory=list[N8nBlockView],
        description="The blocks of this version's own workflow in n8n, in the order a run meets "
        "them, read from the workflow the platform keeps for the version. Empty for a workflow "
        "that runs on the shared n8n workflow.",
    )


class UseCaseList(WireModel):
    use_cases: list[UseCaseView] = Field(description="Every workflow that is not deleted.")


class UseCaseDeleted(WireModel):
    use_case_id: str
    deleted_at: datetime
    restore_until: datetime = Field(
        description="Until then, POST /api/v1/use-cases/{use_case_id}/restore puts the workflow "
        "back as it was. Its past runs stay readable either way."
    )


class StartRunIn(WireIn):
    test: bool = Field(
        default=False,
        description="True for Do a test run, which tries a workflow once. Run now and a check "
        "of the watchlist send nothing.",
    )


class SuggestIn(WireIn):
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
type Version = Annotated[str, Field(pattern=VERSION_PATTERN)]


class AddSoftware(WireIn):
    name: SoftwareName
    repo: RepoName
    our_version: Version | None = Field(
        default=None,
        description="The version the team runs now, such as 1.2.14. Leave it out when nobody "
        "knows it: the list then says Not known, and the check tells about releases newer than "
        "the newest one it first reads.",
    )


class FindIn(WireIn):
    name: SoftwareName


class ProjectGuess(WireModel):
    repo: RepoName = Field(
        description="A GitHub project that exists, as owner/name, at the address GitHub gives it "
        "now. Checked just now."
    )
    what: str = Field(description="What the project is, so the person can tell matches apart.")
    why: str = Field(description="Where the guess came from, in plain words.")
    releases: Literal["published", "none"] = Field(
        description="none when the project has no release the watchlist counts, so a watch "
        "would have nothing to compare."
    )
    newest: str | None = Field(description="The newest release the watchlist counts, if any.")
    already_listed: str | None = Field(
        description="The name this project already has on the watchlist, or null."
    )


class FoundProjects(WireModel):
    status: Literal["found"] = "found"
    matches: list[ProjectGuess] = Field(
        min_length=1,
        description="Every project the name could mean. More than one means the person "
        "chooses. Each is a guess from a reviewed list, never a certainty.",
    )


class NoProjectKnown(WireModel):
    status: Literal["not_known"] = "not_known"
    message: str


class NoProjectChecked(WireModel):
    status: Literal["not_checked"] = "not_checked"
    message: str = Field(
        description="What went wrong, in plain words. No project is offered, because nothing "
        "unchecked is shown."
    )


type FindOut = Annotated[
    FoundProjects | NoProjectKnown | NoProjectChecked, Field(discriminator="status")
]


class SourceView(WireModel):
    kind: Literal["github"]
    ref: str
    url: str


type VersionSourceKind = Literal["given", "first_check", "ticket_done"]


class VersionSourceView(WireModel):
    kind: VersionSourceKind
    at: datetime
    ticket: str | None


class AddressChangeView(WireModel):
    kind: Literal["use", "undo"] = Field(
        description="use: the saved repository was switched to the one GitHub reported. undo: it "
        "was put back."
    )
    from_repo: RepoName
    to_repo: RepoName
    by: UserId
    at: datetime


class WatchedSoftwareView(WireModel):
    id: SoftwareId
    name: str
    source: SourceView
    our_version: str | None = Field(
        description="The version the team runs, when somebody said so or a ticket marked Done "
        "moved it. Null means Not known. It is never filled from the newest release."
    )
    our_version_source: VersionSourceView | None
    compared_from: str | None = Field(
        description="With no version known, the newest release the first check read. Later "
        "checks tell about releases newer than this. It is not the version the team runs."
    )
    newest_version: str | None = Field(
        description="The newest release read from the source. A check that cannot read the "
        "source keeps the version an earlier check read."
    )
    newest_read_at: datetime | None = Field(
        description="When newest_version was read. Earlier than checked_at when the latest "
        "check could not read the source."
    )
    checked_at: datetime | None
    status: Status
    problem: str | None
    open_ticket: str | None
    approval_id: ApprovalId | None
    moved_to: RepoName | None = Field(
        default=None,
        description="The repository GitHub answered for the saved one at the latest check, when "
        "it is a different one: GitHub renamed the repository and redirects the old name. Null "
        "when the names agree, or when no check has read it. The Operator may switch the saved "
        "repository to it with POST /watchlist/software/{software_id}/address.",
    )
    not_found: bool = Field(
        default=False,
        description="True when the latest check was told by GitHub that the saved repository "
        "does not exist. GitHub does not say where it went, so nothing is offered: remove the "
        "software and add it again at its new address.",
    )
    address_changes: list[AddressChangeView] = Field(
        description="Each time the saved repository was switched or put back, the newest first, "
        "with who did it. At most 10.",
    )
    added_by: UserId
    added_at: datetime


class AddressIn(WireIn):
    repo: RepoName = Field(
        description="The owner/name the person confirmed. For use, it must be the one GitHub "
        "reported for the software. For undo, it must be an address the software had before."
    )


class LastCheckView(WireModel):
    run_id: RunId
    state: RunStateName
    started_at: datetime


class ScheduleIn(WireIn):
    day: Day
    at: ClockTime = Field(description="Time of day in Singapore, HH:MM on a 5-minute step.")


type Via = Literal["page", "chat"]

VIA_WORDS = (
    "Where the change was made: page, the workflow's page, or chat, the Planner's chat. The "
    "version keeps it."
)


class UseCaseScheduleIn(ScheduleIn):
    via: Via = Field(default="page", description=VIA_WORDS)


class UndoIn(WireIn):
    via: Via = Field(default="page", description=VIA_WORDS)


class VersionSchedule(WireModel):
    day: Day
    at: ClockTime
    time_zone: str


class ScheduleChangeView(WireModel):
    before: VersionSchedule | None = Field(description="Null when it had no schedule.")
    after: VersionSchedule | None = Field(
        description="Null when an Undo took the schedule away again."
    )


class VersionChange(WireModel):
    schedule: ScheduleChangeView


class VersionView(WireModel):
    version: int
    at: AwareDatetime = Field(
        description="When it was published. For version 1, when the workflow was set up."
    )
    by: UserId | None = Field(description="Who changed it. Null when change is null.")
    via: Via | None = Field(description="Where it was changed. Null when change is null.")
    change: VersionChange | None = Field(
        description="What changed. Null for version 1, and for a version the Software "
        "watchlist published when its software changed."
    )
    undid: int | None = Field(
        description="The version this one undid, publishing the schedule from before it again."
    )
    running: bool = Field(description="True for the version running now, which is the newest.")


class VersionList(WireModel):
    versions: list[VersionView] = Field(
        description="Newest first. Empty for a draft, which has published no version yet."
    )


class ScheduleView(WireModel):
    day: Day
    at: ClockTime
    time_zone: str
    owner: UserId = Field(description="The schedule owner. Only another Approver can approve.")
    owner_name: str
    saved_at: datetime
    next_at: datetime | None = Field(
        description="The next time a check starts. Null while the watchlist is paused, and "
        "while the schedule is held."
    )
    held: ScheduleHold | None = Field(
        default=None,
        description="Why the schedule starts no check: owner_removed when the owner has left the "
        "People list, owner_not_an_operator when they are no longer an Operator. An Operator "
        "takes it over by saving it again. Null while the owner can run it.",
    )


class WatchlistView(WireModel):
    use_case_id: str
    version: int
    ticket_project: str
    state: Literal["on", "paused"] = Field(
        description="on, or paused until an Operator resumes it, as on its use case view. A "
        "paused watchlist starts no check, on its schedule or by hand."
    )
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


class CardInput(WireIn):
    name: str
    kind: str = Field(description="github_repo, jira_project or text.")
    what: str = ""
    example: str = ""


class CardBlock(WireIn):
    say: str
    tool: str | None = Field(default=None, description="A tool id from GET /tools, or null.")


class CardApprovalView(WireIn):
    tool: str
    approvers: int


class CardDefinition(WireIn):
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


class PlanIn(WireIn):
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


class AgentChoice(WireIn):
    card_id: str
    values: dict[str, str]


class CreateAgentUseCase(WireIn):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    agents: Annotated[list[AgentChoice], Field(min_length=1, max_length=3)]
    schedule: ScheduleIn | None = Field(
        default=None,
        description="When it runs on its own, in Singapore time. The person who sets it up "
        "owns the schedule, so its scheduled runs are their work. Leave it out to run it only "
        "by hand.",
    )
    left_out: Annotated[
        list[
            Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        ],
        Field(max_length=10),
    ] = Field(
        default_factory=list,
        description="The parts of the request the Planner marked with a cross, in the person's "
        "own words, so the workflow keeps what it was set up without (plan 4.6). Nothing runs "
        "from them.",
    )
    on: bool = Field(
        default=True,
        description="False sets it up as a draft (ADR 0044): it never runs on its schedule, a "
        "test run of it stops before the yes and writes nothing, and turning it on publishes "
        "version 1.",
    )


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


class StarterView(WireModel):
    name: str
    what: str
    task: str | None = Field(
        description="The task this starter stands for. Null when the starter opens a page."
    )
    opens: Literal["software_watchlist"] | None = Field(
        description="The page this starter opens instead of a task."
    )


DRAFT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
DRAFT_STEPS = 4
DRAFT_LIMIT_BYTES = 32 * 1024


class DraftTimes(WireIn):
    created_at: AwareDatetime
    saved_at: AwareDatetime


class DraftIn(WireIn):
    step: Annotated[int, Field(ge=1, le=DRAFT_STEPS)] | None = Field(
        default=None,
        description="The step of the old four-step screen the draft was saved at, from 1 to 4. "
        "A draft saved from a Planner card has no step.",
    )
    content: dict[str, JsonValue] = Field(
        description="The set-up card's form as the Portal keeps it, at most 32 KB as JSON. "
        "The platform stores it as it is. It reads only a top-level `name`, which Home shows."
    )
    put_back: DraftTimes | None = Field(
        default=None,
        description="Set when Undo puts back a draft that was just discarded: the times it had. "
        "They are used only if no draft with this id exists, and never later than now, so "
        "`Last saved` stays true. An ordinary save leaves it out.",
    )

    @field_validator("content")
    @classmethod
    def _fits(cls, content: dict[str, JsonValue]) -> dict[str, JsonValue]:
        size = len(json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode())
        if size > DRAFT_LIMIT_BYTES:
            raise ValueError("The draft is too big to save. Keep it under 32 KB.")
        return content


class DraftView(WireModel):
    draft_id: str
    step: int | None
    content: dict[str, JsonValue]
    created_at: datetime
    saved_at: datetime


class DraftList(WireModel):
    drafts: list[DraftView] = Field(
        description="The signed-in person's own drafts, the last saved first."
    )
