import json
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from platform_api.builder.templates import VERSION_PATTERN
from platform_api.orchestration import (
    AT_PATTERN,
    PACKAGE_VERSION_PATTERN,
    CardToolId,
    Day,
    Grade,
    InputKind,
    RowKind,
    RowState,
    ScheduleHold,
    Status,
    ToolId,
    ToolKind,
)
from platform_api.shared import ApprovalId, RunId, SoftwareId, UserId
from platform_api.wire import (
    MAVEN_COORDINATE_PATTERN,
    NPM_PACKAGE_PATTERN,
    FoundBy,
    PackageKind,
    RepoName,
    SourceKind,
    WireIn,
    WireModel,
)
from platform_api.wire import FailureReason as FailureReasonName
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
    "off",
]


class N8nExitView(WireModel):
    exit: str | None = Field(
        description="Which way out: true or false for an IF, the name of an Ask for a yes exit "
        "(No answer, Yes, No, Nothing to change), or null for a block with one way out."
    )
    to: str = Field(description="The block it leads to, by name.")


type N8nBadge = Literal["ours", "n8n"]


class N8nBlockView(WireModel):
    name: str = Field(description="The block's name, as n8n, the canvas and the run line show it.")
    kind: N8nBlockKind = Field(
        description="What the block does: schedule, start (Start from the Portal), manual and "
        "error start a run; read, agent, propose, ask (Ask for a yes), write (Make the approved "
        "changes), tell and report are our blocks; branch (IF), merge and end (No Op) are n8n's; "
        "other is one of n8n's own blocks that shapes the data, reads a system or posts a notice, "
        "as its tag says; off is a block the class file turns off, or does not know, for what it "
        "is or what it was asked to do."
    )
    badge: N8nBadge = Field(
        default="ours",
        description="ours for a block of our node pack, which the sketch badges Our block; n8n "
        "for one of n8n's own, badged n8n block (ADR 0045, section 3).",
    )
    tag: str | None = Field(
        default=None,
        description="What one of n8n's own blocks does, by its class: Reads Jira, Posts in Slack, "
        "Shapes the data. Null for our blocks and n8n's flow blocks, and for a block that is off.",
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
    owner_name: str | None = Field(
        description="The name of the schedule owner. Its scheduled runs start as them. Null for a "
        "schedule nobody saved in the Portal, such as one set in n8n's editor."
    )
    held: ScheduleHold | None = Field(
        default=None,
        description="Why the schedule starts no run: owner_removed when the owner has left the "
        "People list, owner_not_an_operator when they are no longer an Operator. An Operator "
        "takes it over by saving it again. Null while the owner can run it.",
    )
    held_words: str | None = Field(
        default=None,
        description="Why a held schedule starts no run, and how it runs again, in the words to "
        "show. Null while the owner can run it.",
    )


class RunStopView(WireModel):
    at: AwareDatetime = Field(
        description="When it last stopped: after a retry, the second stop. Needs you gives the "
        "same time."
    )
    what_happened: str = Field(
        description="Why it stopped, in the AI troubleshooter's one sentence, without the time."
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
    you_can_open: bool = Field(
        description="True when the run stopped and is in the Needs you of the person asking: an "
        "Operator whose work it is. False for any other run."
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
    stop: RunStopView | None = Field(
        description="When and why a stopped run stopped, the words every place that names the "
        "stop says. Null for any other run."
    )


class N8nHolderView(WireModel):
    id: UserId
    name: str
    since: datetime


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
    needs_you: Literal["approval", "stopped", "declined", "question", "fix"] | None = Field(
        default=None,
        description="Why this workflow is in the Needs you of the person asking, or null when it "
        "is not: a yes they may give, a run of theirs that stopped, a test run an Approver "
        "declined, a question to answer, or a workflow that can't run and needs a fix. It holds "
        "exactly when their Home has a row for the workflow.",
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
    grade: Grade | None = Field(
        default=None,
        description="The safety checker's grade of the version in use, for a workflow n8n "
        "carries. writes_refused: a write can run without a yes, so the platform refuses this "
        "version's writes and asks nobody, until the yes is put back or the change undone. "
        "needs_a_fix: it uses a block that is off, or cannot run as the platform expects, so "
        "each run stops at its first block. Null for a workflow on the shared n8n workflow.",
    )
    findings: list[str] = Field(
        default_factory=list[str],
        description="Why the version in use is not safe, in the safety checker's words, one per "
        "problem. Empty when it is safe.",
    )
    deleted_in_n8n_at: AwareDatetime | None = Field(
        default=None,
        description="When the platform found its workflow deleted in n8n. It runs no more, and "
        "its runs and versions are kept (ENGINE-PLAN D7). Null while n8n has it.",
    )
    moving_to_n8n: bool = Field(
        default=False,
        description="True while it still runs on the shared n8n workflow only because a run of "
        "it has not ended. It moves to an n8n workflow of its own once that run ends "
        "(ENGINE-PLAN 2.6).",
    )
    move_refused: str | None = Field(
        default=None,
        description="Why it is still on the shared n8n workflow and so starts no scheduled run, "
        "in plain words with what to do: a step the safety checker refused, or n8n not taking "
        "it yet. Null once it moved, and while it only waits for a run to end.",
    )
    start_refused: str | None = Field(
        default=None,
        description="Why neither Run now nor a test run can start it, in words to show: the "
        "version in use has no Start from the Portal block. Null when they can.",
    )
    made_in_n8n_by: UserId | None = Field(
        default=None,
        description="Who made it in n8n, for a workflow made in n8n and then set up from "
        "Workflows (ENGINE-PLAN E15). Change it in n8n: its runs are their work, so they never "
        "approve them. Null for a workflow the Planner laid out.",
    )
    held_in_n8n: N8nHolderView | None = Field(
        default=None,
        description="Who has it open in n8n now, for everyone to see. While someone does, the "
        "platform refuses every change that would publish over their work: a schedule change, "
        "Undo, roll back, Add the yes back and Resume. Pause and Delete still work.",
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
type Version = Annotated[
    str, Field(pattern=f"{VERSION_PATTERN}|{PACKAGE_VERSION_PATTERN}", max_length=40)
]
"""A GitHub software's version as VERSION_PATTERN, or a package's as PACKAGE_VERSION_PATTERN.
AddSoftware holds each to its own source."""


class PackageIn(WireIn):
    """A package on a registry the team installs from (ADR 0025)."""

    kind: PackageKind = Field(description="maven for Maven Central, npm for the npm registry.")
    ref: str = Field(
        description="groupId:artifactId for Maven Central, such as "
        "org.apache.logging.log4j:log4j-core, or the package name for npm, such as express or "
        "@angular/core."
    )

    @model_validator(mode="after")
    def _named_as_its_registry_names_it(self) -> PackageIn:
        pattern = MAVEN_COORDINATE_PATTERN if self.kind == "maven" else NPM_PACKAGE_PATTERN
        if not re.fullmatch(pattern, self.ref):
            raise ValueError(
                "ref must be groupId:artifactId"
                if self.kind == "maven"
                else "ref must be an npm package name, such as express or @angular/core"
            )
        return self


class AddSoftware(WireIn):
    name: SoftwareName
    repo: RepoName | None = Field(
        default=None,
        description="The GitHub repository whose releases are read, as owner/name. Give this "
        "or package, not both.",
    )
    package: PackageIn | None = Field(
        default=None,
        description="The package whose versions are read from its registry. Give this or "
        "repo, not both. Known vulnerabilities are looked up only for a package.",
    )
    our_version: Version | None = Field(
        default=None,
        description="The version the team runs now, such as 1.2.14, or for a package also "
        "4.1.115.Final or 33.3.1-jre. Leave it out when nobody "
        "knows it: the list then says Not known, and the check tells about releases newer than "
        "the newest one it first reads.",
    )

    @model_validator(mode="after")
    def _one_source(self) -> AddSoftware:
        if (self.repo is None) == (self.package is None):
            raise ValueError("give repo or package, not both and not neither")
        pattern = VERSION_PATTERN if self.package is None else PACKAGE_VERSION_PATTERN
        if self.our_version is not None and not re.fullmatch(pattern, self.our_version):
            raise ValueError(
                "our_version must be three numbers, such as 1.2.14"
                if self.package is None
                else "our_version must be three numbers, with at most .Final, .RELEASE, .GA, "
                "-jre or -android after them, such as 33.3.1-jre"
            )
        return self

    @property
    def source_kind(self) -> SourceKind:
        return "github" if self.package is None else self.package.kind

    @property
    def source_ref(self) -> str:
        if self.package is not None:
            return self.package.ref
        assert self.repo is not None
        return self.repo


class FindIn(WireIn):
    name: SoftwareName


class ProjectGuess(WireModel):
    kind: SourceKind = Field(
        default="github",
        description="Where it is published: github for a GitHub project, maven or npm for a "
        "package on that registry (ADR 0025). The add sends a package as package, not repo.",
    )
    repo: str = Field(
        description="The software at its source, checked just now: a GitHub project as "
        "owner/name at the address GitHub gives it now, a Maven package as groupId:artifactId, "
        "or an npm package name."
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
    found_by: FoundBy = Field(
        default="reviewed_list",
        description="reviewed_list when the name is on our reviewed list of known software. "
        "github_search when the list has no such name and GitHub's public repository search "
        "found this project. A search match is only ever a choice: never pick it for the "
        "person, even when it is the only match.",
    )
    stars: int | None = Field(
        default=None,
        ge=0,
        description="How many stars the repository has on GitHub, for a search match. Null for "
        "a match from the reviewed list.",
    )


class FoundProjects(WireModel):
    status: Literal["found"] = "found"
    matches: list[ProjectGuess] = Field(
        min_length=1,
        description="Every project the name could mean, each checked just now. Only one match "
        "from the reviewed list may be confirmed as it is. More than one, or any match found by "
        "searching GitHub (at most 3), means the person chooses. Each is a guess, never a "
        "certainty.",
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
    kind: SourceKind = Field(
        description="github for GitHub releases, maven for Maven Central, npm for the npm "
        "registry (ADR 0025)."
    )
    ref: str
    url: str = Field(description="The page a person opens to see the versions.")


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
    at: ClockTime = Field(
        description="Time of day in the team time zone, HH:MM on a 5-minute step."
    )


EXPECTED_VERSION = (
    "The version the person read before making this change. When another version is in use by "
    "now, nothing is saved or published and the answer is 409, so a teammate's later change is "
    "never overwritten."
)


class ScheduleSaveIn(ScheduleIn):
    expected_version: int = Field(description=EXPECTED_VERSION)


type Via = Literal["page", "chat"]

VIA_WORDS = (
    "Where the change was made: page, the workflow's page, or chat, the Planner's chat. The "
    "version keeps it."
)


class UseCaseScheduleIn(ScheduleSaveIn):
    via: Via = Field(default="page", description=VIA_WORDS)


class UndoIn(WireIn):
    via: Via = Field(default="page", description=VIA_WORDS)


class RepublishIn(WireIn):
    via: Via = Field(default="page", description=VIA_WORDS)
    in_use: int | None = Field(
        default=None,
        description="The version the person saw in use, as the Changed in n8n card names it. "
        "When another version is in use by now, nothing changes and the answer is 409, so a "
        "change made since is never thrown away.",
    )


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


type VersionMade = Literal[
    "published_in_n8n",
    "settings_changed_in_n8n",
    "rolled_back",
    "yes_put_back",
    "moved_to_n8n",
    "fixed",
]


class VersionView(WireModel):
    version: int
    at: AwareDatetime = Field(
        description="When it was published. For version 1, when the workflow was set up."
    )
    by: UserId | None = Field(
        description="Who changed it: the person who saved the schedule, rolled back or put the "
        "yes back in the Portal, or who published it in n8n. Null for version 1, for a version "
        "the Software watchlist published, and for a version published in n8n by someone the "
        "People list can't match."
    )
    via: Via | None = Field(
        description="Where in the Portal it was changed. Null for a version made in n8n, and "
        "when by is null."
    )
    change: VersionChange | None = Field(
        description="The change of when it runs. Null for version 1, for a version the Software "
        "watchlist published when its software changed, and for a version made otherwise."
    )
    undid: int | None = Field(
        description="The version this one undid, publishing the schedule from before it again."
    )
    running: bool = Field(description="True for the version running now, which is the newest.")
    made: VersionMade | None = Field(
        default=None,
        description="How a version that is not a change of when it runs came about: "
        "published_in_n8n by a person in n8n's editor; settings_changed_in_n8n, the same version "
        "in n8n with its settings saved there and nothing published, which n8n runs with the new "
        "settings at once; rolled_back to an earlier version; yes_put_back, which put Ask for "
        "a yes back before each write; moved_to_n8n, the version that moved it from the shared "
        "n8n workflow to its own; or fixed, a fix an Approver said yes to that passed its test "
        "run (ADR 0055). Null otherwise.",
    )
    grade: Grade | None = Field(
        default=None,
        description="The safety checker's grade of this version, for a workflow n8n carries. "
        "Null for a workflow on the shared n8n workflow.",
    )
    changes: list[str] = Field(
        default_factory=list[str],
        description="For a version published in n8n, or whose settings changed there, what "
        "changed from the version before, in plain words, as the Changed in n8n card lists "
        "them. Empty otherwise.",
    )
    rolled_back_to: int | None = Field(
        default=None, description="The version a roll back put back in use. Null otherwise."
    )
    publisher_unknown: bool = Field(
        default=False,
        description="True for a version published in n8n by someone the People list can't "
        "match. Its runs stop at their first block until an Operator matches the person.",
    )


class SweepOut(WireModel):
    found: int = Field(description="How many versions published in n8n this look found and kept.")


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
    held_words: str | None = Field(
        default=None,
        description="Why a held schedule starts no run, and how it runs again, in the words to "
        "show. Null while the owner can run it.",
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
    moving_to_n8n: bool = Field(
        default=False,
        description="The watchlist still runs on the shared run workflow because a check has "
        "not ended. It moves to its own n8n workflow the next time it is asked once that check "
        "ends: at the next Check now, or when the platform next starts.",
    )


class WatchlistOut(WireModel):
    watchlist: WatchlistView | None


class ToolView(WireModel):
    id: ToolId
    kind: ToolKind
    name: str
    description: str
    system: str = Field(description='What it reaches, in words, such as "Maven Central and npm".')
    in_cards: bool = Field(
        description="Whether an agent card can use it. False for a tool only the Software "
        "watchlist check runs."
    )
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
    tool: CardToolId | None


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
    tools: list[CardToolId] = Field(description="The tools the blocks use, each once, in order.")


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
    project: str | None = Field(
        default=None,
        description="The one Jira project the task's words name, read by code, which the "
        "Portal fills the agent's Jira project input with. Null when the words name none, or "
        "the agent uses no Jira tool.",
    )


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
        description="When it runs on its own, in the team time zone. The person who sets it up "
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


FixReason = Literal["needs_a_fix", "writes_refused"]


def fix_of(view: UseCaseView, operator: bool) -> FixReason | None:
    """Why a workflow that is on can't run, for a person who has a button for it. A version that
    needs a fix is for everyone, because Explain opens for both roles. Refused writes are for an
    Operator, who can add the yes back. A workflow that could not move to n8n has no button, so
    it is not here. One rule for the pill and for Home's Needs you row."""
    if view.state != "on":
        return None
    if view.grade == "needs_a_fix":
        return view.grade
    if view.grade == "writes_refused" and operator:
        return view.grade
    return None
