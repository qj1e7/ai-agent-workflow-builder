from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from platform_api.auth import DEV_USERS
from platform_api.builder.http import (
    BlockView,
    ParamSpec,
    SuggestOut,
    TemplateList,
    TemplateView,
    UseCaseView,
)
from platform_api.monitoring.agent_events import (
    AgentAddressee,
    AgentFailedData,
    AgentJoinedData,
    AgentMessageData,
    AgentRef,
    AgentStepFinishedData,
    AgentStepStartedData,
    RoomAddressee,
)
from platform_api.monitoring.events import (
    ActionLine,
    ActivityEvent,
    Actor,
    AgentFailed,
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
    RunFailed,
    RunFailedData,
    RunRejected,
    RunRejectedData,
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
    activity_event_adapter,
)
from platform_api.monitoring.http import TroubleshootingOut
from platform_api.monitoring.troubleshooter import explain
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.http import (
    ApprovalRef,
    ApprovalView,
    AwaitingApprovalView,
    DecisionOut,
    DecisionView,
    FailedView,
    MockJiraTicket,
    MockJiraTickets,
    ProposalView,
    RefusalOut,
    RejectedView,
    RunView,
    StepResponseOut,
    SucceededView,
    TeamsStubMessage,
    TeamsStubMessages,
    WorkflowFailureIn,
    WorkingView,
    WriteActionView,
    WriteDoneView,
)
from platform_api.orchestration.write_actions import WriteAction, digest
from platform_api.shared import ApprovalId, ProposalId, RunId, UserId
from platform_api.wire import ApprovalStepView, WireModel

ALICE = UserId("alice")
BOB = UserId("bob")

USER_ALICE = Actor(kind="user", id="alice", display="Alice")
USER_BOB = Actor(kind="user", id="bob", display="Bob")
PLATFORM = Actor(kind="platform", id="platform", display="Platform")
WORKFLOW = Actor(kind="workflow", id="n8n", display="Workflow engine")
ROOM_LEAD = AgentRef(id="room_lead", display="Room lead")
CHECKER = AgentRef(id="release_checker", display="Release checker")
AGENT_ROOM_LEAD = Actor(kind="agent", id=ROOM_LEAD.id, display=ROOM_LEAD.display)
AGENT_CHECKER = Actor(kind="agent", id=CHECKER.id, display=CHECKER.display)
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
TO_ROOM = RoomAddressee()

USE_CASE_ID = "uc_01JB7"
USE_CASE_NAME = "LangGraph releases"
REPO = "langchain-ai/langgraph"
TAG_PATTERN = r"^\d+\.\d+\.\d+$"
LAST_KNOWN_TAG = "1.2.14"
NEW_TAGS = ["1.2.16", "1.2.15"]
TICKET_TITLE = "New LangGraph releases: 1.2.16, 1.2.15"
TICKET_BODY = (
    "Releases newer than 1.2.14 on langchain-ai/langgraph:\n- 1.2.16\n- 1.2.15\n\n"
    "Proposed by the AI workflow builder."
)
INSTRUCTION = "Check langchain-ai/langgraph for new releases and open a ticket for the team."
CHANNEL = "CODESparks Ops"
TICKET_KEY = "MOCK-142"

JIRA_ACTION = WriteAction(
    connector="jira",
    operation="create_ticket",
    target={"project": "MOCK"},
    fields={"title": TICKET_TITLE, "body": TICKET_BODY},
)
DIGEST = digest([JIRA_ACTION])
ACTION_VIEW = WriteActionView(
    connector=JIRA_ACTION.connector,
    operation=JIRA_ACTION.operation,
    target=dict(JIRA_ACTION.target),
    fields=dict(JIRA_ACTION.fields),
)
ACTION_LINE = ActionLine(
    connector="jira", operation="create_ticket", line=f"Create Jira ticket in MOCK: {TICKET_TITLE}"
)


@dataclass(frozen=True)
class Story:
    name: str
    run_id: RunId
    t0: datetime
    work_execution: str
    act_execution: str = ""

    @property
    def task_id(self) -> str:
        return f"{self.run_id}/work/1/1"

    @property
    def approval_id(self) -> ApprovalId:
        return ApprovalId("apr_" + self.run_id.removeprefix("run_"))

    @property
    def proposal_id(self) -> ProposalId:
        return ProposalId("prp_" + self.run_id.removeprefix("run_"))

    @property
    def approval_link(self) -> str:
        return f"/approvals/{self.approval_id}"

    @property
    def events_url(self) -> str:
        return f"/api/v1/runs/{self.run_id}/events"


SUCCESS = Story("success", RunId("run_01JB8"), datetime(2026, 11, 3, 2, 14, tzinfo=UTC), "41", "42")
FAILURE = Story("failure", RunId("run_01JB9"), datetime(2026, 11, 4, 2, 14, tzinfo=UTC), "43")
REJECTED = Story("rejected", RunId("run_01JBA"), datetime(2026, 11, 5, 2, 14, tzinfo=UTC), "44")


@dataclass
class Timeline:
    story: Story
    events: list[ActivityEvent] = field(default_factory=list[ActivityEvent])

    def at(self, seconds: float) -> datetime:
        return self.story.t0 + timedelta(seconds=seconds)

    def add[E: WireModel](
        self, cls: type[E], seconds: float, actor: Actor, summary: str, data: WireModel
    ) -> E:
        event = cls.model_validate(
            {
                "run_id": self.story.run_id,
                "seq": len(self.events) + 1,
                "ts": self.at(seconds),
                "actor": actor,
                "summary": summary,
                "data": data,
            }
        )
        self.events.append(activity_event_adapter.validate_python(event))
        return event

    @property
    def last(self) -> ActivityEvent:
        return self.events[-1]


def open_step() -> ApprovalStepView:
    return ApprovalStepView(index=0, label="Team approver", status="open")


def decided_step(verdict: Verdict, at: datetime) -> ApprovalStepView:
    status = "approved" if verdict is Verdict.APPROVE else "declined"
    return ApprovalStepView(
        index=0, label="Team approver", status=status, decided_by=BOB, decided_at=at
    )


def run_created(tl: Timeline) -> None:
    tl.add(
        RunCreated,
        0.0,
        USER_ALICE,
        f"Alice started a run of {USE_CASE_NAME}.",
        RunCreatedData(use_case_id=USE_CASE_ID, use_case_version=1, started_by=ALICE),
    )
    tl.add(
        LegDispatched,
        0.18,
        PLATFORM,
        "The work leg was sent to the workflow engine (attempt 1).",
        LegDispatchedData(leg="work", attempt=1),
    )
    tl.add(
        StepStarted,
        2.1,
        WORKFLOW,
        f"Workflow step run_agents started (n8n execution {tl.story.work_execution}).",
        StepStartedData(step="run_agents", n8n_execution_id=tl.story.work_execution, try_number=1),
    )


def room_opens(tl: Timeline, base: float) -> None:
    tl.add(
        AgentJoined,
        base + 0.29,
        AGENT_ROOM_LEAD,
        "Room lead brought in Release checker to read the GitHub releases.",
        AgentJoinedData(agent=CHECKER, reason="The task asks about releases of a GitHub repo."),
    )
    tl.add(
        AgentMessage,
        base + 0.41,
        AGENT_ROOM_LEAD,
        "Room lead asked Release checker to look for releases newer than 1.2.14.",
        AgentMessageData(
            speaker=ROOM_LEAD,
            addressee=TO_CHECKER,
            text=f"Please check {REPO} for releases newer than {LAST_KNOWN_TAG} that match "
            "the plain version pattern.",
        ),
    )
    tl.add(
        AgentStepStarted,
        base + 0.54,
        AGENT_CHECKER,
        f"Release checker is fetching releases from {REPO}.",
        AgentStepStartedData(step="fetch_releases"),
    )


def work_leg_to_announcement(tl: Timeline) -> None:
    run_created(tl)
    room_opens(tl, 2.1)
    tl.add(
        AgentStepFinished,
        4.873,
        AGENT_CHECKER,
        "Release checker fetched 30 releases. The latest is 1.2.16.",
        AgentStepFinishedData(
            step="fetch_releases", result={"release_count": 30, "latest": "1.2.16"}
        ),
    )
    tl.add(
        AgentStepStarted,
        4.901,
        AGENT_CHECKER,
        "Release checker is comparing them with the last known tag 1.2.14.",
        AgentStepStartedData(step="find_new"),
    )
    tl.add(
        AgentStepFinished,
        4.955,
        AGENT_CHECKER,
        "Release checker found 2 new releases: 1.2.16, 1.2.15.",
        AgentStepFinishedData(step="find_new", result={"new_count": 2, "tags": NEW_TAGS}),
    )
    tl.add(
        AgentMessage,
        5.12,
        AGENT_CHECKER,
        "Release checker reported 2 new releases to the room and suggested one ticket.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="Two releases are newer than 1.2.14: 1.2.16 and 1.2.15. I suggest one ticket "
            "so the team reviews both.",
        ),
    )
    tl.add(
        AgentMessage,
        5.301,
        AGENT_ROOM_LEAD,
        "Room lead agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=ROOM_LEAD,
            addressee=TO_CHECKER,
            text="Agreed. I will propose the ticket. The platform asks an Approver before "
            "anything is written.",
        ),
    )
    tl.add(
        WriteActionProposed,
        5.844,
        AGENT_ROOM_LEAD,
        "The agents proposed 1 write action: create a Jira ticket in MOCK.",
        WriteActionProposedData(
            proposal_id=tl.story.proposal_id, digest=DIGEST, actions=[ACTION_LINE]
        ),
    )
    tl.add(
        StepFinished,
        5.902,
        WORKFLOW,
        "Workflow step run_agents finished: 2 new releases: 1.2.16, 1.2.15.",
        StepFinishedData(
            step="run_agents",
            n8n_execution_id=tl.story.work_execution,
            try_number=1,
            outcome="proposed",
            detail="2 new releases: 1.2.16, 1.2.15",
        ),
    )
    tl.add(
        StepStarted,
        8.217,
        WORKFLOW,
        f"Workflow step ask_approval started (n8n execution {tl.story.work_execution}).",
        StepStartedData(
            step="ask_approval", n8n_execution_id=tl.story.work_execution, try_number=1
        ),
    )
    tl.add(
        ApprovalRequested,
        8.244,
        PLATFORM,
        "Approval requested. Waiting for the Team approver.",
        ApprovalRequestedData(
            approval_id=tl.story.approval_id, steps=[open_step()], link=tl.story.approval_link
        ),
    )
    tl.add(
        StepFinished,
        8.26,
        WORKFLOW,
        "Workflow step ask_approval finished. The work leg ends here.",
        StepFinishedData(
            step="ask_approval",
            n8n_execution_id=tl.story.work_execution,
            try_number=1,
            outcome="approval_opened",
            detail=f"Approval {tl.story.approval_id} opened",
        ),
    )
    tl.add(
        ApprovalAnnounced,
        10.612,
        PLATFORM,
        f"The approval request was posted to the Teams channel {CHANNEL}.",
        ApprovalAnnouncedData(
            approval_id=tl.story.approval_id, channel=CHANNEL, link=tl.story.approval_link
        ),
    )


def success_events() -> Timeline:
    tl = Timeline(SUCCESS)
    work_leg_to_announcement(tl)
    decided = tl.add(
        ApprovalDecided,
        383.447,
        USER_BOB,
        "Bob approved step 0 (Team approver).",
        ApprovalDecidedData(approval_id=SUCCESS.approval_id, step=0, verdict="approve", by=BOB),
    )
    tl.add(
        LegDispatched,
        383.61,
        PLATFORM,
        "The act leg was sent to the workflow engine (attempt 1).",
        LegDispatchedData(leg="act", attempt=1),
    )
    tl.add(
        StepStarted,
        385.902,
        WORKFLOW,
        f"Workflow step write_action started (n8n execution {SUCCESS.act_execution}).",
        StepStartedData(step="write_action", n8n_execution_id=SUCCESS.act_execution, try_number=1),
    )
    tl.add(
        WriteActionDone,
        386.344,
        PLATFORM,
        f"Jira ticket {TICKET_KEY} was created, approved by Bob.",
        WriteActionDoneData(
            connector="jira",
            operation="create_ticket",
            external_reference=TICKET_KEY,
            approved_by=[decided.data.by],
        ),
    )
    tl.add(
        StepFinished,
        386.371,
        WORKFLOW,
        f"Workflow step write_action finished: created {TICKET_KEY}.",
        StepFinishedData(
            step="write_action",
            n8n_execution_id=SUCCESS.act_execution,
            try_number=1,
            outcome="written",
            detail=f"Created {TICKET_KEY}",
        ),
    )
    tl.add(
        RunSucceeded,
        386.38,
        PLATFORM,
        "The run succeeded. 1 write action was done.",
        RunSucceededData(outcome="written"),
    )
    return tl


GITHUB_503 = "GitHub returned 503 Service Unavailable three times"


def failure_events() -> Timeline:
    tl = Timeline(FAILURE)
    run_created(tl)
    room_opens(tl, 2.08)
    for try_number, seconds in enumerate((4.702, 8.811, 12.934), start=1):
        last = try_number == 3
        tl.add(
            AgentMessage,
            seconds,
            AGENT_CHECKER,
            f"Release checker reported that GitHub answered 503 (try {try_number} of 3).",
            AgentMessageData(
                speaker=CHECKER,
                addressee=TO_ROOM,
                text=f"GitHub answered 503 Service Unavailable (try {try_number} of 3). "
                + ("I am giving up." if last else "Waiting 2 s before trying again."),
            ),
        )
    tl.add(
        AgentFailed,
        12.961,
        AGENT_CHECKER,
        "Release checker failed: GitHub was unavailable.",
        AgentFailedData(
            step="fetch_releases",
            error_type="UpstreamUnavailable",
            message=GITHUB_503,
            retryable=True,
        ),
    )
    tl.add(
        StepFinished,
        13.02,
        WORKFLOW,
        "Workflow step run_agents finished with a failure.",
        StepFinishedData(
            step="run_agents",
            n8n_execution_id=FAILURE.work_execution,
            try_number=1,
            outcome="failed",
            detail=f"Release checker failed: {GITHUB_503}",
        ),
    )
    tl.add(
        RunFailed,
        13.031,
        PLATFORM,
        "The run failed while the agents were working. GitHub was unavailable. You can retry.",
        RunFailedData(
            stage="working",
            reason="AgentError",
            retryable=True,
            message=f"Release checker failed: {GITHUB_503}",
        ),
    )
    return tl


def rejected_events() -> Timeline:
    tl = Timeline(REJECTED)
    work_leg_to_announcement(tl)
    tl.add(
        ApprovalDecided,
        251.903,
        USER_BOB,
        "Bob declined step 0 (Team approver).",
        ApprovalDecidedData(approval_id=REJECTED.approval_id, step=0, verdict="decline", by=BOB),
    )
    tl.add(
        RunRejected,
        251.92,
        PLATFORM,
        "The run was rejected by Bob. Nothing was written.",
        RunRejectedData(by=BOB, step=0),
    )
    return tl


def proposal_view(story: Story) -> ProposalView:
    return ProposalView(proposal_id=story.proposal_id, digest=DIGEST, actions=[ACTION_VIEW])


def approval_ref(story: Story, steps: list[ApprovalStepView]) -> ApprovalRef:
    return ApprovalRef(approval_id=story.approval_id, link=story.approval_link, steps=steps)


class RunBaseFields(TypedDict):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    use_case_version: int
    started_by: UserId
    started_at: datetime
    updated_at: datetime
    last_seq: int
    events_url: str


def _base(story: Story, tl: Timeline, seq: int) -> RunBaseFields:
    return RunBaseFields(
        run_id=story.run_id,
        use_case_id=USE_CASE_ID,
        use_case_name=USE_CASE_NAME,
        use_case_version=1,
        started_by=ALICE,
        started_at=story.t0,
        updated_at=tl.events[seq - 1].ts,
        last_seq=seq,
        events_url=story.events_url,
    )


def awaiting_approval_view(story: Story, tl: Timeline) -> RunView:
    seq = next(e.seq for e in tl.events if e.kind == "approval_announced")
    return AwaitingApprovalView(
        **_base(story, tl, seq),
        proposal=proposal_view(story),
        approval=approval_ref(story, [open_step()]),
    )


def success_final_view(tl: Timeline) -> RunView:
    return SucceededView(
        **_base(SUCCESS, tl, len(tl.events)),
        outcome="written",
        written=[
            WriteDoneView(
                connector="jira",
                operation="create_ticket",
                external_reference=TICKET_KEY,
                approved_by=[BOB],
            )
        ],
    )


def failure_working_view(tl: Timeline) -> RunView:
    seq = next(e.seq for e in tl.events if e.kind == "agent_step_started")
    return WorkingView(
        **_base(FAILURE, tl, seq), n8n_execution_id=FAILURE.work_execution, attempt=1
    )


def failure_final_view(tl: Timeline) -> RunView:
    failed = tl.last
    assert failed.kind == "run_failed"
    return FailedView(
        **_base(FAILURE, tl, failed.seq),
        stage=failed.data.stage,
        reason=failed.data.reason,
        retryable=failed.data.retryable,
        message=failed.data.message,
    )


def rejected_final_view(tl: Timeline) -> RunView:
    decided = next(e for e in tl.events if e.kind == "approval_decided")
    return RejectedView(
        **_base(REJECTED, tl, len(tl.events)),
        proposal=proposal_view(REJECTED),
        approval=approval_ref(REJECTED, [decided_step(Verdict.DECLINE, decided.ts)]),
        rejected_by=BOB,
        step=0,
    )


def approval_view_for(story: Story, viewer: UserId) -> ApprovalView:
    own_work = viewer == ALICE
    return ApprovalView(
        approval_id=story.approval_id,
        run_id=story.run_id,
        digest=DIGEST,
        actions=[ACTION_VIEW],
        steps=[open_step()],
        you_can_decide=not own_work,
        why_not=Refusal.OWN_WORK if own_work else None,
    )


def decision_out(tl: Timeline) -> DecisionOut:
    decided = next(e for e in tl.events if e.kind == "approval_decided")
    return DecisionOut(
        status="approved",
        decision=DecisionView(step=0, by=BOB, verdict=Verdict.APPROVE, at=decided.ts),
    )


OWN_WORK_REFUSAL = RefusalOut(
    refusal=Refusal.OWN_WORK, message="You started this run, so another Approver must decide."
)

RELEASE_CHECK_TEMPLATE = TemplateView(
    key="release_check",
    name="Release check",
    description="Watch a public GitHub repository and open a ticket when new releases appear.",
    blocks=[
        BlockView(
            key="read_releases",
            name="Read GitHub releases",
            description="The Release checker reads the repository's releases.",
            kind="agent",
        ),
        BlockView(
            key="approval_gate",
            name="Approval gate",
            description="An Approver reviews the proposed ticket in Teams before it is written.",
            kind="approval",
        ),
        BlockView(
            key="create_ticket",
            name="Create Jira ticket",
            description="One ticket in the chosen project listing the new releases.",
            kind="write_action",
        ),
    ],
    params=[
        ParamSpec(name="repo", description="GitHub repository, owner/name", example=REPO),
        ParamSpec(
            name="tag_pattern",
            description="Regular expression a release tag must match",
            example=TAG_PATTERN,
        ),
        ParamSpec(name="ticket_project", description="Jira project key", example="MOCK"),
    ],
)

TEMPLATES = TemplateList(templates=[RELEASE_CHECK_TEMPLATE])

USE_CASE = UseCaseView(
    use_case_id=USE_CASE_ID,
    version=1,
    template="release_check",
    name=USE_CASE_NAME,
    instruction=INSTRUCTION,
    params={"repo": REPO, "tag_pattern": TAG_PATTERN, "ticket_project": "MOCK"},
    owner=ALICE,
    created_at=datetime(2026, 11, 2, 9, 30, tzinfo=UTC),
)

SUGGESTION = SuggestOut(template=RELEASE_CHECK_TEMPLATE, matched_terms=["releases", "ticket"])

STEP_RESPONSES = [
    StepResponseOut(proceed=True, outcome="proposed", detail="2 new releases: 1.2.16, 1.2.15"),
    StepResponseOut(
        proceed=False, outcome="nothing_to_write", detail="No new releases since 1.2.16"
    ),
    StepResponseOut(proceed=False, outcome="superseded", detail="Execution 40 holds this leg"),
    StepResponseOut(
        proceed=False,
        outcome="refused",
        detail="write_action is not allowed while the run is proposed",
    ),
    StepResponseOut(proceed=True, outcome="written", detail=f"Created {TICKET_KEY}"),
]

WORKFLOW_FAILURE = WorkflowFailureIn(
    execution_id="41",
    workflow="release_check",
    last_node="Run agents",
    message="The service refused the connection",
    execution_url="http://n8n:5678/execution/41",
)


def teams_messages(tl: Timeline) -> TeamsStubMessages:
    announced = next(e for e in tl.events if e.kind == "approval_announced")
    return TeamsStubMessages(
        messages=[
            TeamsStubMessage(
                id="tm_01JB8",
                ts=announced.ts,
                channel=CHANNEL,
                text=f"Approval needed: {USE_CASE_NAME} wants to create a Jira ticket in MOCK "
                f'titled "{TICKET_TITLE}". Open the approval page to decide.',
                link=SUCCESS.approval_link,
                run_id=SUCCESS.run_id,
                approval_id=SUCCESS.approval_id,
            )
        ]
    )


def mock_jira_tickets(tl: Timeline) -> MockJiraTickets:
    done = next(e for e in tl.events if e.kind == "write_action_done")
    return MockJiraTickets(
        tickets=[
            MockJiraTicket(
                key=TICKET_KEY,
                project="MOCK",
                title=TICKET_TITLE,
                body=TICKET_BODY,
                created_at=done.ts,
                run_id=SUCCESS.run_id,
                proposal_id=SUCCESS.proposal_id,
            )
        ]
    )


def troubleshooting(tl: Timeline) -> TroubleshootingOut:
    failed = tl.last
    assert failed.kind == "run_failed"
    return TroubleshootingOut(
        run_id=FAILURE.run_id, failure=failed.data, advice=explain(failed.data.reason)
    )


def fixtures() -> dict[str, WireModel | list[WireModel]]:
    success = success_events()
    failure = failure_events()
    rejected = rejected_events()
    return {
        "runs/success.json": list(success.events),
        "runs/failure.json": list(failure.events),
        "runs/rejected.json": list(rejected.events),
        "views/success.awaiting_approval.json": awaiting_approval_view(SUCCESS, success),
        "views/success.final.json": success_final_view(success),
        "views/failure.working.json": failure_working_view(failure),
        "views/failure.final.json": failure_final_view(failure),
        "views/rejected.awaiting_approval.json": awaiting_approval_view(REJECTED, rejected),
        "views/rejected.final.json": rejected_final_view(rejected),
        "approvals/apr_01JB8.alice.json": approval_view_for(SUCCESS, ALICE),
        "approvals/apr_01JB8.bob.json": approval_view_for(SUCCESS, BOB),
        "approvals/decision.approved.json": decision_out(success),
        "approvals/refusal.own_work.json": OWN_WORK_REFUSAL,
        "builder/templates.json": TEMPLATES,
        "builder/use-case.json": USE_CASE,
        "builder/suggest.json": SUGGESTION,
        "internal/step-responses.json": list(STEP_RESPONSES),
        "internal/workflow-failure.json": WORKFLOW_FAILURE,
        "stubs/dev-users.json": DEV_USERS,
        "stubs/teams-messages.json": teams_messages(success),
        "stubs/mock-jira-tickets.json": mock_jira_tickets(success),
        "troubleshooting/failure.json": troubleshooting(failure),
    }
