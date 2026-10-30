"""Fixtures for agent cards: the tool list, the library, a check, the three plans and a use case,
and a recorded run of one card.

The recorded run follows the agent runtime's agent/card-task-finished.json event by event, so a
test can hold the two side by side.
"""

from datetime import UTC, datetime

from platform_api.builder.cards import (
    VERSION_CHECKER,
    card_view,
    check_card,
    plan_for_cards,
    sorted_for_library,
    tool_list,
)
from platform_api.builder.models import (
    CannotDo,
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CardList,
    MissingTool,
    NewAgent,
    PlannedAgent,
    UseCaseAgentView,
    UseCaseView,
    UseSaved,
)
from platform_api.contracts.stories import (
    AGENT_PLANNER,
    ALICE,
    BOB,
    CHANNEL,
    PLANNER,
    PLATFORM,
    TO_ROOM,
    USER_ALICE,
    USER_BOB,
    WORKFLOW,
    Story,
    Timeline,
    open_step,
)
from platform_api.monitoring.agent_events import (
    AgentAddressee,
    AgentJoinedData,
    AgentMessageData,
    AgentRef,
    AgentStepFinishedData,
    AgentStepStartedData,
)
from platform_api.monitoring.events import (
    Actor,
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
from platform_api.orchestration.write_actions import WriteAction, describe, digest
from platform_api.shared import RunId, UserId
from platform_api.wire import WireModel

CARD_RUN = Story("card", RunId("run_01JD1"), datetime(2026, 11, 5, 2, 14, tzinfo=UTC), "61", "62")
USE_CASE_ID = "uc_01JD0"
USE_CASE_NAME = "LangGraph release check"
INSTRUCTION = "Check langchain-ai/langgraph for a new release and raise a ticket in MOCK."
REPO = "langchain-ai/langgraph"
VALUES = {"GitHub repository": REPO, "Jira project": "MOCK"}
TICKET_KEY = "MOCK-150"
TITLE = "Upgrade LangGraph to 1.2.16"
BODY = (
    "LangGraph 1.2.16 is out on GitHub (langchain-ai/langgraph). MOCK has no ticket for it."
    "\n\nProposed by the AI workflow builder."
)
SUMMARY = (
    "LangGraph 1.2.16 is the newest release and MOCK has no ticket for it, so I proposed one "
    "ticket for an Approver to check."
)
CARD = AgentRef(id=VERSION_CHECKER.card_id, display=VERSION_CHECKER.name)
AGENT_CARD = Actor(kind="agent", id=CARD.id, display=CARD.display)
TO_CARD = AgentAddressee(id=CARD.id, display=CARD.display)
ACTION = WriteAction(
    connector="jira",
    operation="create_ticket",
    target={"project": "MOCK"},
    fields={"title": TITLE, "body": BODY},
)
DIGEST = digest([ACTION])
TAGS = ["1.2.16", "1.2.15", "1.2.14", "1.2.13", "1.2.12", "1.2.11", "1.2.10", "1.2.9"]

WEEKLY = card_view(
    card_id="crd_01JD0WEEKLYSUMMARY000001",
    version=2,
    starter=False,
    owner=UserId("alice"),
    created_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
    definition=CardDefinition(
        name="Weekly summary",
        purpose="Lists the tickets finished in a Jira project this week.",
        good_for=["Every Friday summarise what we finished"],
        inputs=[CardInput(name="Jira project", kind="jira_project", example="MOCK")],
        blocks=[CardBlock(say="Find the tickets finished this week.", tool="jira.search")],
        approvals=[],
    ),
)

DRAFT = CardDefinition(
    name="Done ticket reporter",
    purpose="Raises a ticket that lists what was finished in a Jira project.",
    good_for=["Raise a ticket listing what we finished this week"],
    inputs=[CardInput(name="Jira project", kind="jira_project", example="MOCK")],
    blocks=[
        CardBlock(say="Find the tickets finished this week.", tool="jira.search"),
        CardBlock(say="Propose a ticket that lists them.", tool="jira.create_ticket"),
    ],
    approvals=[CardApprovalView(tool="jira.create_ticket", approvers=1)],
)
CHECKED_DRAFT = check_card(DRAFT)
BROKEN = DRAFT.model_copy(update={"inputs": [], "name": "Forge reporter"})


def plan_use_one() -> UseSaved:
    return UseSaved(
        decision="use_one",
        agents=[
            PlannedAgent(
                card=VERSION_CHECKER,
                part="Check LangGraph for a new release and raise a ticket.",
                values={"GitHub repository": REPO},
                missing=["Jira project"],
            )
        ],
        reason="The Version checker already does this for any public repository.",
        questions=["Which Jira project should get the ticket?"],
    )


def plan_new_agent() -> NewAgent:
    checked = check_card(BROKEN)
    return NewAgent(
        draft=checked.card,
        approvals=checked.approvals,
        problems=checked.problems,
        reason="No saved agent raises tickets from finished work.",
        missing_tools=[MissingTool(need="Post in Teams", why="To share the list with the team.")],
        questions=["Which Jira project?"],
    )


def plan_cannot_do() -> CannotDo:
    return CannotDo(
        reason="Booking a meeting room needs a calendar, and the platform has no calendar tool.",
        missing_tools=[MissingTool(need="Calendar", why="To find and book a free room.")],
    )


USE_CASE = UseCaseView(
    use_case_id=USE_CASE_ID,
    version=1,
    template="agent_cards",
    name=USE_CASE_NAME,
    instruction=INSTRUCTION,
    params={},
    owner=ALICE,
    created_at=datetime(2026, 11, 4, 9, 30, tzinfo=UTC),
    state="on",
    next_run_at=None,
    schedule=None,
    plan=plan_for_cards([VERSION_CHECKER]),
    agents=[
        UseCaseAgentView(
            card_id=VERSION_CHECKER.card_id,
            card_version=VERSION_CHECKER.version,
            name=VERSION_CHECKER.name,
            values=VALUES,
        )
    ],
)


def card_run_events() -> Timeline:
    tl = Timeline(CARD_RUN)
    execution = CARD_RUN.work_execution
    tl.add(
        RunCreated,
        0.0,
        USER_ALICE,
        f"Alice started a run of the {USE_CASE_NAME}.",
        RunCreatedData(use_case_id=USE_CASE_ID, use_case_version=1, started_by=ALICE),
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
        1.9,
        WORKFLOW,
        f"Workflow step run_agents started (n8n execution {execution}).",
        StepStartedData(step="run_agents", n8n_execution_id=execution, try_number=1),
    )
    tl.add(
        AgentJoined,
        2.1,
        AGENT_PLANNER,
        "Planner brought in Version checker.",
        AgentJoinedData(agent=CARD, reason=VERSION_CHECKER.purpose),
    )
    tl.add(
        AgentMessage,
        2.3,
        AGENT_PLANNER,
        "Planner asked Version checker to do its part of the task.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CARD,
            text="Please run your plan with these inputs. GitHub repository: "
            f"{REPO}; Jira project: MOCK.",
        ),
    )
    tl.add(
        AgentStepStarted,
        3.4,
        AGENT_CARD,
        f"Version checker reads the releases of {REPO}.",
        AgentStepStartedData(step="github_read_releases"),
    )
    tl.add(
        AgentStepFinished,
        4.2,
        AGENT_CARD,
        f"Version checker read 8 releases of {REPO}. The newest is 1.2.16.",
        AgentStepFinishedData(step="github_read_releases", result={"releases": 8, "tags": TAGS}),
    )
    tl.add(
        AgentStepStarted,
        5.6,
        AGENT_CARD,
        "Version checker searches Jira project MOCK.",
        AgentStepStartedData(step="jira_search"),
    )
    tl.add(
        AgentStepFinished,
        5.9,
        AGENT_CARD,
        "Version checker found no tickets in MOCK.",
        AgentStepFinishedData(step="jira_search", result={"count": 0, "tickets": []}),
    )
    tl.add(
        AgentStepStarted,
        7.3,
        AGENT_CARD,
        f"Version checker drafts a Jira ticket for approval: {TITLE}",
        AgentStepStartedData(step="jira_create_ticket"),
    )
    tl.add(
        AgentStepFinished,
        7.31,
        AGENT_CARD,
        f"Version checker proposed a ticket for approval: {TITLE}",
        AgentStepFinishedData(step="jira_create_ticket", result={"title": TITLE}),
    )
    tl.add(
        AgentMessage,
        9.0,
        AGENT_CARD,
        f"Version checker reported to the room: {SUMMARY}",
        AgentMessageData(speaker=CARD, addressee=TO_ROOM, text=SUMMARY),
    )
    tl.add(
        AgentMessage,
        9.2,
        AGENT_PLANNER,
        "Planner agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CARD,
            text="Agreed. I'll draft one ticket for an Approver to check.",
        ),
    )
    line = describe(ACTION)
    tl.add(
        WriteActionProposed,
        9.8,
        AGENT_PLANNER,
        f"The agents proposed 1 write action: {line.line}.",
        WriteActionProposedData(proposal_id=CARD_RUN.proposal_id, digest=DIGEST, actions=[line]),
    )
    tl.add(
        StepFinished,
        9.86,
        WORKFLOW,
        f"Workflow step run_agents finished: {SUMMARY}",
        StepFinishedData(
            step="run_agents",
            n8n_execution_id=execution,
            try_number=1,
            outcome="proposed",
            detail=SUMMARY,
        ),
    )
    tl.add(
        StepStarted,
        12.2,
        WORKFLOW,
        f"Workflow step ask_approval started (n8n execution {execution}).",
        StepStartedData(step="ask_approval", n8n_execution_id=execution, try_number=1),
    )
    tl.add(
        ApprovalRequested,
        12.24,
        PLATFORM,
        "Approval requested. Waiting for the Team approver.",
        ApprovalRequestedData(
            approval_id=CARD_RUN.approval_id, steps=[open_step()], link=CARD_RUN.approval_link
        ),
    )
    tl.add(
        StepFinished,
        12.26,
        WORKFLOW,
        "Workflow step ask_approval finished. The work leg ends here.",
        StepFinishedData(
            step="ask_approval",
            n8n_execution_id=execution,
            try_number=1,
            outcome="approval_opened",
            detail=f"Approval {CARD_RUN.approval_id} opened",
        ),
    )
    tl.add(
        ApprovalAnnounced,
        14.6,
        PLATFORM,
        f"The approval request was posted to the Teams channel {CHANNEL}.",
        ApprovalAnnouncedData(
            approval_id=CARD_RUN.approval_id, channel=CHANNEL, link=CARD_RUN.approval_link
        ),
    )
    decided = tl.add(
        ApprovalDecided,
        420.0,
        USER_BOB,
        "Bob approved the request (Team approver).",
        ApprovalDecidedData(approval_id=CARD_RUN.approval_id, step=0, verdict="approve", by=BOB),
    )
    tl.add(
        LegDispatched,
        420.16,
        PLATFORM,
        "The act leg was queued for the workflow engine (attempt 1).",
        LegDispatchedData(leg="act", attempt=1),
    )
    tl.add(
        StepStarted,
        422.4,
        WORKFLOW,
        f"Workflow step write_action started (n8n execution {CARD_RUN.act_execution}).",
        StepStartedData(step="write_action", n8n_execution_id=CARD_RUN.act_execution, try_number=1),
    )
    tl.add(
        WriteActionDone,
        422.9,
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
        422.93,
        WORKFLOW,
        f"Workflow step write_action finished: created {TICKET_KEY}.",
        StepFinishedData(
            step="write_action",
            n8n_execution_id=CARD_RUN.act_execution,
            try_number=1,
            outcome="written",
            detail=f"Created {TICKET_KEY}",
        ),
    )
    tl.add(
        RunSucceeded,
        422.94,
        PLATFORM,
        "The run succeeded. 1 write action was done.",
        RunSucceededData(outcome="written"),
    )
    return tl


def card_fixtures() -> dict[str, WireModel | list[WireModel]]:
    return {
        "cards/tools.json": tool_list(),
        "cards/list.json": CardList(cards=sorted_for_library([VERSION_CHECKER], [WEEKLY])),
        "cards/check.json": check_card(BROKEN),
        "cards/plan.use-one.json": plan_use_one(),
        "cards/plan.new-agent.json": plan_new_agent(),
        "cards/plan.cannot-do.json": plan_cannot_do(),
        "cards/use-case.json": USE_CASE,
        "runs/card.json": list(card_run_events().events),
    }
