"""A recorded check of the software watchlist, for the Portal's demo.

The watchlist holds six software. Before the check, the page shows the results of Monday's
scheduled check. On Friday morning Alice checks again by hand. The check reads all six: three
are behind, one cannot be read and one gets its starting point. Bob approves the three upgrade
tickets with one decision, and they are written as MOCK-143 to MOCK-145. The agents' words
follow the agent runtime's watchlist checker.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from platform_api.builder.models import (
    ScheduleView,
    SourceView,
    VersionSourceView,
    WatchedSoftwareView,
    WatchlistView,
)
from platform_api.builder.watchlist import attention_first
from platform_api.contracts.stories import (
    AGENT_CHECKER,
    AGENT_PLANNER,
    BOB,
    CHANNEL,
    CHECKER,
    PLANNER,
    PLATFORM,
    TO_CHECKER,
    TO_ROOM,
    USER_ALICE,
    USER_BOB,
    WORKFLOW,
    Story,
    Timeline,
    approval_ref,
    open_step,
)
from platform_api.monitoring.agent_events import (
    AgentJoinedData,
    AgentMessageData,
    AgentStepFinishedData,
    AgentStepStartedData,
)
from platform_api.monitoring.events import (
    AgentJoined,
    AgentMessage,
    AgentStepFinished,
    AgentStepStarted,
    ApprovalAnnounced,
    ApprovalAnnouncedData,
    ApprovalDecided,
    ApprovalDecidedData,
    ApprovalRequested,
    ApprovalRequestedData,
    LegDispatched,
    LegDispatchedData,
    RunCreated,
    RunCreatedData,
    RunSucceeded,
    RunSucceededData,
    StepFinished,
    StepFinishedData,
    StepStarted,
    StepStartedData,
    WriteActionDone,
    WriteActionDoneData,
    WriteActionProposed,
    WriteActionProposedData,
)
from platform_api.orchestration.http import (
    AwaitingApprovalView,
    ProposalView,
    RunView,
    WriteActionView,
)
from platform_api.orchestration.watch import newer
from platform_api.orchestration.write_actions import WriteAction, describe, digest
from platform_api.shared import RunId, SoftwareId, UserId
from platform_api.wire import WireModel

ALICE = UserId("alice")
CAROL = UserId("carol")

CHECK = Story(
    "watchlist", RunId("run_01JBC"), datetime(2026, 11, 20, 2, 14, tzinfo=UTC), "51", "52"
)
USE_CASE_ID = "uc_01JBW"
USE_CASE_NAME = "Software watchlist"
USE_CASE_VERSION = 6
PROJECT = "MOCK"

SINGAPORE = timezone(timedelta(hours=8))
ADDED_AT = datetime(2026, 11, 2, 10, 0, tzinfo=SINGAPORE)
FIRST_CHECK_AT = datetime(2026, 11, 9, 9, 0, 12, tzinfo=SINGAPORE)
LAST_WEEK = datetime(2026, 11, 16, 9, 0, 12, tzinfo=SINGAPORE)
SCHEDULE = ScheduleView(
    day="monday",
    at="09:00",
    time_zone="Asia/Singapore",
    owner=ALICE,
    owner_name="Alice",
    saved_at=ADDED_AT,
    next_at=datetime(2026, 11, 23, 9, 0, tzinfo=SINGAPORE),
)


@dataclass(frozen=True)
class Watched:
    """One row of the watchlist as it stood before the check, and what the check found."""

    number: int
    name: str
    ref: str
    our_version: str | None
    our_version_source: VersionSourceView | None
    seen: str | None
    problem: str | None
    state: str
    newest: str | None
    new_versions: tuple[str, ...]
    added_by: UserId = ALICE
    added_at: datetime = ADDED_AT

    @property
    def id(self) -> SoftwareId:
        return SoftwareId(f"sw_01JBY{self.number:020d}")


def given() -> VersionSourceView:
    return VersionSourceView(kind="given", at=ADDED_AT, ticket=None)


WATCHED = (
    Watched(
        1,
        "n8n",
        "n8n-io/n8n",
        "2.42.6",
        VersionSourceView(
            kind="ticket_done",
            at=datetime(2026, 11, 13, 14, 30, tzinfo=SINGAPORE),
            ticket="MOCK-140",
        ),
        "2.42.6",
        None,
        "up_to_date",
        "2.42.6",
        (),
    ),
    Watched(
        2,
        "LangGraph",
        "langchain-ai/langgraph",
        "1.2.14",
        given(),
        "1.2.16",
        None,
        "behind",
        "1.2.16",
        ("1.2.16", "1.2.15"),
    ),
    Watched(
        3,
        "Redis",
        "redis/redis",
        "8.2.0",
        VersionSourceView(kind="first_check", at=FIRST_CHECK_AT, ticket=None),
        "8.2.0",
        None,
        "behind",
        "8.2.1",
        ("8.2.1",),
    ),
    Watched(
        4,
        "PostgreSQL",
        "postgres/postgres",
        "17.2.0",
        given(),
        "17.2.0",
        None,
        "behind",
        "17.3.0",
        ("17.3.0",),
    ),
    Watched(
        5,
        "FastAPI",
        "fastapi/fast-api",
        "0.115.0",
        given(),
        None,
        "GitHub answered 404 Not Found.",
        "cant_check",
        None,
        (),
    ),
    Watched(
        6,
        "Terraform",
        "hashicorp/terraform",
        None,
        None,
        None,
        None,
        "starting_point",
        "1.9.8",
        (),
        added_by=CAROL,
        added_at=datetime(2026, 11, 19, 11, 20, tzinfo=SINGAPORE),
    ),
)
BEHIND = tuple(w for w in WATCHED if w.state == "behind")
TICKET_KEYS = tuple(f"MOCK-{143 + index}" for index in range(len(BEHIND)))


def _status_before(w: Watched) -> str:
    if w.problem is not None:
        return "cant_check"
    if w.seen is None:
        return "not_checked"
    behind = w.our_version is not None and newer(w.seen, w.our_version)
    return "behind" if behind else "up_to_date"


def _row_before(w: Watched) -> WatchedSoftwareView:
    return WatchedSoftwareView.model_validate(
        {
            "id": w.id,
            "name": w.name,
            "source": SourceView(
                kind="github", ref=w.ref, url=f"https://github.com/{w.ref}/releases"
            ),
            "our_version": w.our_version,
            "our_version_source": w.our_version_source,
            "newest_version": w.seen,
            "checked_at": None if w.seen is None and w.problem is None else LAST_WEEK,
            "status": _status_before(w),
            "problem": w.problem,
            "open_ticket": None,
            "approval_id": None,
            "added_by": w.added_by,
            "added_at": w.added_at,
        }
    )


BEFORE_CHECK = WatchlistView(
    use_case_id=USE_CASE_ID,
    version=USE_CASE_VERSION,
    ticket_project=PROJECT,
    software=attention_first([_row_before(w) for w in WATCHED]),
    last_check=None,
    schedule=SCHEDULE,
)


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _detail(w: Watched) -> str:
    match w.state:
        case "up_to_date":
            return f"Nothing is newer than {w.our_version}."
        case "behind":
            return f"{_plural(len(w.new_versions), 'release')} newer than {w.our_version}."
        case "starting_point":
            return f"No version was given, so {w.newest} is the starting point."
        case _:
            return w.problem or ""


def _ticket(w: Watched) -> WriteAction:
    bullets = "\n".join(f"- {tag}" for tag in w.new_versions)
    return WriteAction(
        connector="jira",
        operation="create_ticket",
        target={"project": PROJECT},
        fields={
            "title": f"Upgrade {w.name} from {w.our_version} to {w.newest}",
            "body": f"{w.name} has {_plural(len(w.new_versions), 'new release')} on GitHub "
            f"({w.ref}) newer than our version {w.our_version}:\n{bullets}\n\n"
            "Proposed by the AI workflow builder.",
        },
    )


ACTIONS = [_ticket(w) for w in BEHIND]
DIGEST = digest(ACTIONS)
SUMMARY = (
    f"{len(BEHIND)} of {len(WATCHED)} watched software have new releases: "
    + _names([f"{w.name} {w.newest}" for w in BEHIND])
    + ". "
    + _names([w.name for w in WATCHED if w.state == "cant_check"])
    + " could not be checked."
)


def _read_sources(tl: Timeline, base: float) -> float:
    at = base
    for w in WATCHED:
        tl.add(
            AgentStepStarted,
            at,
            AGENT_CHECKER,
            f"Version checker is reading the releases of {w.name}.",
            AgentStepStartedData(step="read_source"),
        )
        unreadable = w.state == "cant_check"
        tl.add(
            AgentStepFinished,
            at + 0.4,
            AGENT_CHECKER,
            f"Version checker could not read {w.name}."
            if unreadable
            else f"Version checker read {w.name}. {_detail(w)}",
            AgentStepFinishedData(
                step="read_source",
                result={"software_id": w.id, "state": w.state, "newest": w.newest},
            ),
        )
        at += 0.5
        if unreadable:
            tl.add(
                AgentMessage,
                at,
                AGENT_CHECKER,
                f"Version checker could not check {w.name} and carried on.",
                AgentMessageData(
                    speaker=CHECKER,
                    addressee=TO_ROOM,
                    text=f"I could not read {w.name}'s releases: {w.problem} "
                    "I will carry on with the rest.",
                ),
            )
            at += 0.1
    return at


def check_events() -> Timeline:
    tl = Timeline(CHECK)
    tl.add(
        RunCreated,
        0.0,
        USER_ALICE,
        f"Alice started a run of {USE_CASE_NAME}.",
        RunCreatedData(
            use_case_id=USE_CASE_ID, use_case_version=USE_CASE_VERSION, started_by=ALICE
        ),
    )
    tl.add(
        LegDispatched,
        0.18,
        PLATFORM,
        "The work leg was queued for the workflow engine (attempt 1).",
        LegDispatchedData(leg="work", attempt=1),
    )
    tl.add(
        StepStarted,
        2.1,
        WORKFLOW,
        f"Workflow step run_agents started (n8n execution {CHECK.work_execution}).",
        StepStartedData(step="run_agents", n8n_execution_id=CHECK.work_execution, try_number=1),
    )
    count = len(WATCHED)
    tl.add(
        AgentJoined,
        2.39,
        AGENT_PLANNER,
        f"Planner brought in Version checker to read the sources of {count} watched software.",
        AgentJoinedData(
            agent=CHECKER, reason="The task asks about releases of several watched software."
        ),
    )
    tl.add(
        AgentMessage,
        2.51,
        AGENT_PLANNER,
        f"Planner asked Version checker to check {count} watched software for new releases.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CHECKER,
            text=f"Please check these for new releases: {_names([w.name for w in WATCHED])}.",
        ),
    )
    at = _read_sources(tl, 2.7)
    tickets = len(BEHIND)
    tl.add(
        AgentMessage,
        at + 0.2,
        AGENT_CHECKER,
        f"Version checker reported {tickets} of {count} watched software behind and suggested "
        f"{tickets} tickets.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text=f"{tickets} of {count} watched software have new releases: "
            f"{_names([w.name for w in BEHIND])}. I suggest {tickets} tickets, one for each.",
        ),
    )
    tl.add(
        AgentMessage,
        at + 0.4,
        AGENT_PLANNER,
        f"Planner agreed and will propose {tickets} tickets for approval.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CHECKER,
            text=f"Agreed. I'll draft {tickets} tickets for an Approver to check together.",
        ),
    )
    lines = [describe(action) for action in ACTIONS]
    tl.add(
        WriteActionProposed,
        at + 0.9,
        AGENT_PLANNER,
        f"The agents proposed {tickets} write actions: "
        + "; ".join(line.line for line in lines)
        + ".",
        WriteActionProposedData(proposal_id=CHECK.proposal_id, digest=DIGEST, actions=lines),
    )
    tl.add(
        StepFinished,
        at + 0.96,
        WORKFLOW,
        f"Workflow step run_agents finished: {SUMMARY}",
        StepFinishedData(
            step="run_agents",
            n8n_execution_id=CHECK.work_execution,
            try_number=1,
            outcome="proposed",
            detail=SUMMARY,
        ),
    )
    tl.add(
        StepStarted,
        at + 3.2,
        WORKFLOW,
        f"Workflow step ask_approval started (n8n execution {CHECK.work_execution}).",
        StepStartedData(step="ask_approval", n8n_execution_id=CHECK.work_execution, try_number=1),
    )
    tl.add(
        ApprovalRequested,
        at + 3.23,
        PLATFORM,
        "Approval requested. Waiting for the Team approver.",
        ApprovalRequestedData(
            approval_id=CHECK.approval_id, steps=[open_step()], link=CHECK.approval_link
        ),
    )
    tl.add(
        StepFinished,
        at + 3.25,
        WORKFLOW,
        "Workflow step ask_approval finished. The work leg ends here.",
        StepFinishedData(
            step="ask_approval",
            n8n_execution_id=CHECK.work_execution,
            try_number=1,
            outcome="approval_opened",
            detail=f"Approval {CHECK.approval_id} opened",
        ),
    )
    tl.add(
        ApprovalAnnounced,
        at + 5.6,
        PLATFORM,
        f"The approval request was posted to the Teams channel {CHANNEL}.",
        ApprovalAnnouncedData(
            approval_id=CHECK.approval_id, channel=CHANNEL, link=CHECK.approval_link
        ),
    )
    _act_leg(tl, at + 1260.0)
    return tl


def _act_leg(tl: Timeline, decided_at: float) -> None:
    decided = tl.add(
        ApprovalDecided,
        decided_at,
        USER_BOB,
        "Bob approved the request (Team approver).",
        ApprovalDecidedData(approval_id=CHECK.approval_id, step=0, verdict="approve", by=BOB),
    )
    tl.add(
        LegDispatched,
        decided_at + 0.16,
        PLATFORM,
        "The act leg was queued for the workflow engine (attempt 1).",
        LegDispatchedData(leg="act", attempt=1),
    )
    tl.add(
        StepStarted,
        decided_at + 2.45,
        WORKFLOW,
        f"Workflow step write_action started (n8n execution {CHECK.act_execution}).",
        StepStartedData(step="write_action", n8n_execution_id=CHECK.act_execution, try_number=1),
    )
    for index, key in enumerate(TICKET_KEYS):
        tl.add(
            WriteActionDone,
            decided_at + 2.9 + 0.4 * index,
            PLATFORM,
            f"Jira ticket {key} was created, approved by Bob.",
            WriteActionDoneData(
                connector="jira",
                operation="create_ticket",
                external_reference=key,
                approved_by=[decided.data.by],
            ),
        )
    finished_at = decided_at + 2.9 + 0.4 * len(TICKET_KEYS)
    tl.add(
        StepFinished,
        finished_at,
        WORKFLOW,
        f"Workflow step write_action finished: created {', '.join(TICKET_KEYS)}.",
        StepFinishedData(
            step="write_action",
            n8n_execution_id=CHECK.act_execution,
            try_number=1,
            outcome="written",
            detail="Created " + ", ".join(TICKET_KEYS),
        ),
    )
    tl.add(
        RunSucceeded,
        finished_at + 0.01,
        PLATFORM,
        f"The run succeeded. {len(TICKET_KEYS)} write actions were done.",
        RunSucceededData(outcome="written"),
    )


def awaiting_approval_view(tl: Timeline) -> RunView:
    announced = next(e for e in tl.events if e.kind == "approval_announced")
    return AwaitingApprovalView(
        run_id=CHECK.run_id,
        use_case_id=USE_CASE_ID,
        use_case_name=USE_CASE_NAME,
        use_case_version=USE_CASE_VERSION,
        started_by=ALICE,
        trigger="person",
        started_at=CHECK.t0,
        updated_at=announced.ts,
        last_seq=announced.seq,
        events_url=CHECK.events_url,
        proposal=ProposalView(
            proposal_id=CHECK.proposal_id,
            digest=DIGEST,
            actions=[
                WriteActionView(
                    connector=action.connector,
                    operation=action.operation,
                    target=dict(action.target),
                    fields=dict(action.fields),
                )
                for action in ACTIONS
            ],
        ),
        approval=approval_ref(CHECK, [open_step()]),
    )


def watchlist_run_fixtures() -> dict[str, WireModel | list[WireModel]]:
    tl = check_events()
    return {
        "runs/watchlist.json": list(tl.events),
        "views/watchlist.awaiting_approval.json": awaiting_approval_view(tl),
        "watchlist/before-check.json": BEFORE_CHECK,
    }
