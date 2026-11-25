import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pydantic import JsonValue

from agent_runtime.abilities import CAPABILITY_LIST
from agent_runtime.answers import SkipRead, TaskRead, answer_of, check_one_part, parts_of
from agent_runtime.api import AGENT_CARDS
from agent_runtime.contract import (
    RELEASE_TAG_PATTERN,
    AgentAddressee,
    AgentApiSchema,
    AgentEvent,
    AgentEventPost,
    AgentFailedData,
    AgentFailedEvent,
    AgentJoinedData,
    AgentJoinedEvent,
    AgentMessageData,
    AgentMessageEvent,
    AgentRef,
    AgentStepFinishedData,
    AgentStepFinishedEvent,
    AgentStepStartedData,
    AgentStepStartedEvent,
    Answered,
    AnswerRequest,
    Callback,
    CardBlock,
    CardDraft,
    CardInput,
    CardsInputs,
    CardSpec,
    CardToRun,
    CarryForward,
    CauseFound,
    CauseKept,
    CauseRequest,
    CheckPartRequest,
    Choice,
    ChooseRequest,
    Chosen,
    ChosenAgent,
    Connected,
    ConnectRequest,
    CoverBlock,
    DidntFollowAnswer,
    DraftApproval,
    DraftBlock,
    Drafted,
    DrafterFacts,
    DraftInput,
    DraftRequest,
    ExplainFact,
    ExplainKept,
    ExplainReworded,
    ExplainWordingRequest,
    FailedScenario,
    FailureNote,
    Finding,
    FindSoftwareRequest,
    FoundModel,
    FoundSoftware,
    FreeReplyAnswer,
    GitHubProblem,
    GithubSource,
    GitHubWorking,
    KeyShapes,
    LibraryCard,
    LibraryInput,
    MavenSource,
    MissingTool,
    ModelAccess,
    ModelProblem,
    ModelTestPassed,
    PlannerFacts,
    PreviousTurn,
    ProposedIntent,
    QuestionAnswer,
    ReadReleasesRequest,
    ReleaseRead,
    ReleasesRead,
    ReplyAbout,
    ReplyEnvelope,
    RoomAddressee,
    ScenarioBlock,
    ScenarioExplainRequest,
    ScenarioPlay,
    ScenarioSample,
    ScenarioServe,
    ScenariosExplained,
    ScenariosKept,
    ScenariosWritten,
    ScenarioWriteRequest,
    SoftwareMatch,
    SoftwareToCheck,
    StoppedRun,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    TurnTrace,
    Vulnerability,
    WatchedFact,
    WatchlistInputs,
    WatchlistScheduleFact,
    WireModel,
    WorkflowFact,
    WorkflowPlan,
    WrittenRead,
    WrittenScenario,
    agent_event_adapter,
)
from agent_runtime.fixing.coordinator import CheckedCase, FixRequest, RefineRequest
from agent_runtime.fixing.starter import FixAccepted, FixStart, RefineStart
from agent_runtime.free_reply import answer_of_envelope
from agent_runtime.github import TOKEN_REFUSED
from agent_runtime.model_access import KEY_REFUSED
from agent_runtime.monitoring.masking import (
    CODE_PARAMETERS,
    KEPT_KEY,
    KEY_SHAPE_SOURCES,
    SECRET_NAME_ENDS,
)
from agent_runtime.reading import DaysRead, PlaceRead, SearchRead, TicketRead
from agent_runtime.tools import tool_list
from agent_runtime.watchlist import ticket_for

PLANNER = AgentRef(id="planner", display="Planner")
CHECKER = AgentRef(id="version_checker", display="Version checker")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
TO_ROOM = RoomAddressee()

REPO = "langchain-ai/langgraph"
TIME_ZONE = "Asia/Singapore"
OUR_VERSION = "1.2.14"
NEWEST = "1.2.16"
NEW_TAGS = ["1.2.16", "1.2.15"]
LANGGRAPH_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2M"
REDIS_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2N"
FASTAPI_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2P"
INSTRUCTION = (
    "Check the team's watched software for new releases and raise an upgrade ticket for each "
    "one that is behind."
)
TICKET_TITLE = "Upgrade LangGraph from 1.2.14 to 1.2.16"
TICKET_BODY = (
    "LangGraph has 2 new releases on GitHub (langchain-ai/langgraph) newer than our version "
    "1.2.14:\n- 1.2.16\n- 1.2.15\n\nProposed by the AI workflow builder."
)
SUMMARY = "LangGraph has a new release: 1.2.16."
GITHUB_503 = "GitHub returned 503 Service Unavailable three times"
NOTHING_READABLE = f"Could not check LangGraph: {GITHUB_503}"

WATCHLIST_T0 = datetime(2026, 11, 10, 2, 14, tzinfo=UTC)
SUCCESS_T0 = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)
FAILURE_T0 = datetime(2026, 11, 4, 2, 14, tzinfo=UTC)


def langgraph() -> SoftwareToCheck:
    return SoftwareToCheck(
        id=LANGGRAPH_ID, name="LangGraph", source=GithubSource(ref=REPO), our_version=OUR_VERSION
    )


def task_request(run_id: str) -> TaskRequest:
    task_id = f"{run_id}/work/1/1"
    return TaskRequest(
        task_id=task_id,
        run_id=run_id,
        instruction=INSTRUCTION,
        inputs=WatchlistInputs(tag_pattern=RELEASE_TAG_PATTERN, software=[langgraph()]),
        carry_forward=CarryForward(),
        time_zone=TIME_ZONE,
        callback=Callback(
            url=f"http://platform-api:8000/internal/v1/runs/{run_id}/agent-events?task={task_id}",
            token="example-callback-token-not-a-secret",
        ),
    )


def watchlist_software() -> list[SoftwareToCheck]:
    return [
        langgraph(),
        SoftwareToCheck(
            id=REDIS_ID,
            name="Redis",
            source=GithubSource(ref="redis/redis"),
            our_version="8.2.1",
        ),
        SoftwareToCheck(
            id=FASTAPI_ID,
            name="FastAPI",
            source=GithubSource(ref="fastapi/fastapi"),
            our_version="0.115.0",
        ),
    ]


def watchlist_request(run_id: str) -> TaskRequest:
    task_id = f"{run_id}/work/1/1"
    return TaskRequest(
        task_id=task_id,
        run_id=run_id,
        instruction=INSTRUCTION,
        inputs=WatchlistInputs(tag_pattern=RELEASE_TAG_PATTERN, software=watchlist_software()),
        carry_forward=CarryForward(),
        time_zone=TIME_ZONE,
        callback=Callback(
            url=f"http://platform-api:8000/internal/v1/runs/{run_id}/agent-events?task={task_id}",
            token="example-callback-token-not-a-secret",
        ),
    )


LOG4J_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2L"
LOG4J = SoftwareToCheck(
    id=LOG4J_ID,
    name="Log4j",
    source=MavenSource(ref="org.apache.logging.log4j:log4j-core"),
    our_version="2.14.1",
)
LOG4SHELL = Finding(
    software_id=LOG4J_ID,
    state="behind",
    newest="2.24.3",
    new_versions=["2.24.3", "2.17.1"],
    detail="2 releases newer than 2.14.1.",
    vulnerability_check="checked",
    vulnerabilities=[
        Vulnerability(
            id="CVE-2021-44228",
            severity="critical",
            score=10.0,
            summary="Log4Shell",
            fixed_in="2.15.0",
            reported_by=["OSV", "NVD"],
            url="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
        )
    ],
)


def urgent_request(run_id: str) -> TaskRequest:
    """A watchlist check of one Maven package, Log4j 2.14.1 (ADR 0025)."""
    request = watchlist_request(run_id)
    assert isinstance(request.inputs, WatchlistInputs)
    inputs = request.inputs.model_copy(update={"software": [LOG4J]})
    return request.model_copy(update={"inputs": inputs})


def urgent_output() -> TaskOutput:
    """What the Version checker answers for urgent_request when Log4Shell is found: the ticket
    is the runtime's own, titled "Urgent: ...". platform-api's review() must keep it."""
    return TaskOutput(
        summary="Log4j has a new release: 2.24.3. Log4j 2.14.1 has 1 known vulnerability, "
        "1 critical.",
        new_tags=[],
        proposed=[ticket_for(LOG4J, LOG4SHELL)],
        carry_forward=CarryForward(),
        findings=[LOG4SHELL],
    )


class Recorder:
    def __init__(self, t0: datetime) -> None:
        self.t0 = t0
        self.events: list[AgentEvent] = []

    def add[E: WireModel](
        self, cls: type[E], seconds: float, agent: AgentRef, summary: str, data: WireModel
    ) -> E:
        event = cls.model_validate(
            {
                "agent_seq": len(self.events) + 1,
                "ts": self.t0 + timedelta(seconds=seconds),
                "agent": agent,
                "summary": summary,
                "data": data,
            }
        )
        self.events.append(agent_event_adapter.validate_python(event))
        return event


def planner_opens(rec: Recorder, base: float) -> None:
    rec.add(
        AgentJoinedEvent,
        base + 0.29,
        PLANNER,
        "Planner brought in Version checker to read the source of LangGraph.",
        AgentJoinedData(agent=CHECKER, reason="The task asks about new releases of LangGraph."),
    )
    rec.add(
        AgentMessageEvent,
        base + 0.41,
        PLANNER,
        "Planner asked Version checker to check LangGraph for new releases.",
        AgentMessageData(
            speaker=PLANNER, addressee=TO_CHECKER, text="Please check LangGraph for new releases."
        ),
    )
    rec.add(
        AgentStepStartedEvent,
        base + 0.54,
        CHECKER,
        "Version checker is reading the releases of LangGraph.",
        AgentStepStartedData(step="read_source"),
    )


def finished_task() -> TaskFinished:
    rec = Recorder(SUCCESS_T0)
    planner_opens(rec, 2.1)
    rec.add(
        AgentStepFinishedEvent,
        4.873,
        CHECKER,
        "Version checker read LangGraph. 2 releases newer than 1.2.14.",
        AgentStepFinishedData(
            step="read_source",
            result={"software_id": LANGGRAPH_ID, "state": "behind", "newest": NEWEST},
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.12,
        CHECKER,
        "Version checker reported that LangGraph is behind and suggested one ticket.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="LangGraph has a new release: 1.2.16. I suggest one ticket.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.301,
        PLANNER,
        "Planner agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CHECKER,
            text="Agreed. I'll draft one ticket for an Approver to check.",
        ),
    )
    return TaskFinished(
        task_id="run_01JB8/work/1/1",
        output=TaskOutput(
            summary=SUMMARY,
            new_tags=[],
            proposed=[
                ProposedIntent(
                    kind="create_ticket",
                    fields={"title": TICKET_TITLE, "body": TICKET_BODY},
                    reason="LangGraph 1.2.16 is out, and we run 1.2.14",
                    subject=LANGGRAPH_ID,
                )
            ],
            carry_forward=CarryForward(),
            findings=[
                Finding(
                    software_id=LANGGRAPH_ID,
                    state="behind",
                    newest=NEWEST,
                    new_versions=NEW_TAGS,
                    detail="2 releases newer than 1.2.14.",
                    full_name="langchain-ai/langgraph",
                )
            ],
        ),
        events=rec.events,
    )


def _read(
    rec: Recorder,
    start: float,
    name: str,
    software_id: str,
    state: str,
    newest: str | None,
    said: str,
) -> None:
    rec.add(
        AgentStepStartedEvent,
        start,
        CHECKER,
        f"Version checker is reading the releases of {name}.",
        AgentStepStartedData(step="read_source"),
    )
    rec.add(
        AgentStepFinishedEvent,
        start + 0.4,
        CHECKER,
        f"Version checker {said}",
        AgentStepFinishedData(
            step="read_source",
            result={"software_id": software_id, "state": state, "newest": newest},
        ),
    )


def watchlist_finished() -> TaskFinished:
    rec = Recorder(WATCHLIST_T0)
    rec.add(
        AgentJoinedEvent,
        2.1,
        PLANNER,
        "Planner brought in Version checker to read the sources of 3 watched software.",
        AgentJoinedData(
            agent=CHECKER, reason="The task asks about releases of several watched software."
        ),
    )
    rec.add(
        AgentMessageEvent,
        2.3,
        PLANNER,
        "Planner asked Version checker to check 3 watched software for new releases.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CHECKER,
            text="Please check these for new releases: LangGraph, Redis and FastAPI.",
        ),
    )
    _read(
        rec,
        2.5,
        "LangGraph",
        LANGGRAPH_ID,
        "behind",
        "1.2.16",
        "read LangGraph. 2 releases newer than 1.2.14.",
    )
    _read(
        rec,
        3.4,
        "Redis",
        REDIS_ID,
        "up_to_date",
        "8.2.1",
        "read Redis. Nothing is newer than 8.2.1.",
    )
    _read(rec, 4.3, "FastAPI", FASTAPI_ID, "cant_check", None, "could not read FastAPI.")
    rec.add(
        AgentMessageEvent,
        4.8,
        CHECKER,
        "Version checker could not check FastAPI.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="I could not read FastAPI's releases: GitHub answered 404 Not Found.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.0,
        CHECKER,
        "Version checker reported 1 of 3 watched software behind and suggested 1 ticket.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="1 of 3 watched software has new releases: LangGraph. I suggest one ticket.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.2,
        PLANNER,
        "Planner agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=TO_CHECKER,
            text="Agreed. I'll draft one ticket for an Approver to check.",
        ),
    )
    return TaskFinished(
        task_id="run_01JC2/work/1/1",
        output=TaskOutput(
            summary="1 of 3 watched software has new releases: LangGraph 1.2.16. "
            "FastAPI could not be checked.",
            new_tags=[],
            proposed=[
                ProposedIntent(
                    kind="create_ticket",
                    fields={"title": TICKET_TITLE, "body": TICKET_BODY},
                    reason="LangGraph 1.2.16 is out, and we run 1.2.14",
                    subject=LANGGRAPH_ID,
                )
            ],
            carry_forward=CarryForward(),
            findings=[
                Finding(
                    software_id=LANGGRAPH_ID,
                    state="behind",
                    newest="1.2.16",
                    new_versions=NEW_TAGS,
                    detail="2 releases newer than 1.2.14.",
                    full_name="langchain-ai/langgraph",
                ),
                Finding(
                    software_id=REDIS_ID,
                    state="up_to_date",
                    newest="8.2.1",
                    new_versions=[],
                    detail="Nothing is newer than 8.2.1.",
                    full_name="redis/redis",
                ),
                Finding(
                    software_id=FASTAPI_ID,
                    state="cant_check",
                    newest=None,
                    new_versions=[],
                    detail="GitHub answered 404 Not Found.",
                    not_found=True,
                ),
            ],
        ),
        events=rec.events,
    )


def failed_task() -> TaskFailed:
    rec = Recorder(FAILURE_T0)
    planner_opens(rec, 2.08)
    for try_number, seconds in enumerate((4.702, 8.811, 12.934), start=1):
        last = try_number == 3
        rec.add(
            AgentMessageEvent,
            seconds,
            CHECKER,
            f"Version checker reported that GitHub answered 503 (try {try_number} of 3).",
            AgentMessageData(
                speaker=CHECKER,
                addressee=TO_ROOM,
                text=f"GitHub answered 503 Service Unavailable (try {try_number} of 3). "
                + ("I am giving up." if last else "Waiting 2 s before trying again."),
            ),
        )
    rec.add(
        AgentStepFinishedEvent,
        12.95,
        CHECKER,
        "Version checker could not read LangGraph.",
        AgentStepFinishedData(
            step="read_source",
            result={"software_id": LANGGRAPH_ID, "state": "cant_check", "newest": None},
        ),
    )
    rec.add(
        AgentMessageEvent,
        12.955,
        CHECKER,
        "Version checker could not check LangGraph.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text=f"I could not read LangGraph's releases: {GITHUB_503}.",
        ),
    )
    rec.add(
        AgentFailedEvent,
        12.961,
        CHECKER,
        "Version checker failed: LangGraph could not be checked.",
        AgentFailedData(
            step=None, error_type="UpstreamUnavailable", message=NOTHING_READABLE, retryable=True
        ),
    )
    return TaskFailed(
        task_id="run_01JB9/work/1/1",
        error=TaskError(type="UpstreamUnavailable", message=NOTHING_READABLE, retryable=True),
        events=rec.events,
        findings=[
            Finding(
                software_id=LANGGRAPH_ID,
                state="cant_check",
                newest=None,
                new_versions=[],
                detail=f"{GITHUB_503}.",
            )
        ],
    )


CARD_ID = "crd_version_checker"
CARD_T0 = datetime(2026, 11, 5, 2, 14, tzinfo=UTC)
CARD_TICKET_TITLE = "Upgrade LangGraph to 1.2.16"
CARD_TICKET_BODY = (
    "LangGraph 1.2.16 is out on GitHub (langchain-ai/langgraph). MOCK has no ticket for it.\n\n"
    "Proposed by the AI workflow builder."
)
CARD_REPORT = (
    "LangGraph 1.2.16 is the newest release and MOCK has no ticket for it, so I proposed one "
    "ticket for an Approver to check."
)


def version_checker_card() -> CardSpec:
    """The starter card the platform ships, as the runtime receives it."""
    return CardSpec(
        id=CARD_ID,
        version=1,
        name="Version checker",
        purpose="Checks a public GitHub repository for a new release and proposes a Jira "
        "ticket for it.",
        inputs=[
            CardInput(
                name="GitHub repository",
                kind="github_repo",
                what="The public repository to check.",
                example="langchain-ai/langgraph",
            ),
            CardInput(
                name="Jira project",
                kind="jira_project",
                what="Where the ticket goes.",
                example="MOCK",
            ),
        ],
        blocks=[
            CardBlock(
                say="Read the newest releases of the repository.", tool="github.read_releases"
            ),
            CardBlock(
                say="Look in Jira for a ticket about the newest release, so it is not raised "
                "twice.",
                tool="jira.search",
            ),
            CardBlock(
                say="If there is none, propose a ticket naming the release, its date and its link.",
                tool="jira.create_ticket",
            ),
        ],
    )


def card_request(run_id: str) -> TaskRequest:
    task_id = f"{run_id}/work/1/1"
    return TaskRequest(
        task_id=task_id,
        run_id=run_id,
        instruction="Check langchain-ai/langgraph for a new release and open a ticket if Jira "
        "has none.",
        inputs=CardsInputs(
            agents=[
                CardToRun(
                    card=version_checker_card(),
                    values={"GitHub repository": REPO, "Jira project": "MOCK"},
                )
            ]
        ),
        carry_forward=CarryForward(),
        time_zone=TIME_ZONE,
        callback=Callback(
            url=f"http://platform-api:8000/internal/v1/runs/{run_id}/agent-events?task={task_id}",
            token="example-callback-token-not-a-secret",
        ),
    )


def card_finished() -> TaskFinished:
    rec = Recorder(CARD_T0)
    checker = AgentRef(id=CARD_ID, display="Version checker")
    rec.add(
        AgentJoinedEvent,
        2.1,
        PLANNER,
        "Planner brought in Version checker.",
        AgentJoinedData(
            agent=checker,
            reason="Checks a public GitHub repository for a new release and proposes a Jira "
            "ticket for it.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        2.3,
        PLANNER,
        "Planner asked Version checker to do its part of the task.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=AgentAddressee(id=CARD_ID, display="Version checker"),
            text=f"Please run your plan with these inputs. GitHub repository: {REPO}; "
            "Jira project: MOCK.",
        ),
    )
    rec.add(
        AgentStepStartedEvent,
        3.4,
        checker,
        f"Version checker reads the releases of {REPO}.",
        AgentStepStartedData(step="github_read_releases"),
    )
    tags = ["1.2.16", "1.2.15", "1.2.14", "1.2.13", "1.2.12", "1.2.11", "1.2.10", "1.2.9"]
    rec.add(
        AgentStepFinishedEvent,
        4.2,
        checker,
        f"Version checker read 8 releases of {REPO}. The newest is 1.2.16.",
        AgentStepFinishedData(step="github_read_releases", result={"releases": 8, "tags": tags}),
    )
    rec.add(
        AgentStepStartedEvent,
        5.6,
        checker,
        'Version checker searches MOCK for tickets with "1.2.16" in the title or body.',
        AgentStepStartedData(step="jira_search"),
    )
    rec.add(
        AgentStepFinishedEvent,
        5.9,
        checker,
        "Version checker found no tickets in MOCK.",
        AgentStepFinishedData(step="jira_search", result={"count": 0, "tickets": []}),
    )
    rec.add(
        AgentStepStartedEvent,
        7.3,
        checker,
        f"Version checker drafts a Jira ticket for approval: {CARD_TICKET_TITLE}",
        AgentStepStartedData(step="jira_create_ticket"),
    )
    rec.add(
        AgentStepFinishedEvent,
        7.31,
        checker,
        f"Version checker proposed a ticket for approval: {CARD_TICKET_TITLE}",
        AgentStepFinishedData(step="jira_create_ticket", result={"title": CARD_TICKET_TITLE}),
    )
    rec.add(
        AgentMessageEvent,
        9.0,
        checker,
        f"Version checker reported to the room: {CARD_REPORT}",
        AgentMessageData(speaker=checker, addressee=TO_ROOM, text=CARD_REPORT),
    )
    rec.add(
        AgentMessageEvent,
        9.2,
        PLANNER,
        "Planner agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=PLANNER,
            addressee=AgentAddressee(id=CARD_ID, display="Version checker"),
            text="Agreed. I'll draft one ticket for an Approver to check.",
        ),
    )
    return TaskFinished(
        task_id="run_01JD1/work/1/1",
        output=TaskOutput(
            summary=CARD_REPORT,
            new_tags=[],
            proposed=[
                ProposedIntent(
                    kind="jira.create_ticket",
                    fields={"title": CARD_TICKET_TITLE, "body": CARD_TICKET_BODY},
                    reason="If there is none, propose a ticket naming the release, its date and "
                    "its link.",
                    subject=CARD_ID,
                )
            ],
            carry_forward=CarryForward(),
        ),
        events=rec.events,
    )


DRAFT_TASK = (
    "Every Friday, look at the tickets finished this week in one Jira project and open a "
    "summary ticket for the team."
)
CHOOSE_TASK = "Check fastapi/fastapi for a new release and raise a ticket in project MOCK."


def draft_request() -> DraftRequest:
    return DraftRequest(
        task=DRAFT_TASK,
        model=ModelAccess(
            style="anthropic", base_url=GATEWAY, model="claude-sonnet-5-5", api_key=EXAMPLE_KEY
        ),
    )


def drafted() -> Drafted:
    return Drafted(
        draft=CardDraft(
            can_do=True,
            name="Weekly finished tickets summary",
            purpose="Looks at the Jira tickets finished this week in one project and proposes a "
            "summary ticket for the team.",
            good_for=[
                "Summarise what we finished this week",
                "Make a weekly report of finished Jira tickets",
                "Tell the team what was closed in a project",
            ],
            inputs=[
                DraftInput(
                    name="Jira project",
                    kind="jira_project",
                    what="The project to summarise, and where the summary ticket goes.",
                    example="SUP",
                )
            ],
            blocks=[
                DraftBlock(
                    say="Find the tickets in the project that were finished since last Friday.",
                    tool="jira.search",
                ),
                DraftBlock(
                    say="Group them by what they were about and write a short summary.",
                    tool=None,
                ),
                DraftBlock(
                    say="Propose one ticket that lists the summary.", tool="jira.create_ticket"
                ),
            ],
            approvals=[
                DraftApproval(
                    tool="jira.create_ticket",
                    approvers=1,
                    why="It writes a new ticket that the team will read.",
                )
            ],
            missing_tools=[
                MissingTool(
                    need="Post the summary in a Teams channel",
                    why="No tool posts in Teams yet, so the summary goes in a Jira ticket.",
                )
            ],
            questions=["Which Jira project should the summary cover?"],
        )
    )


def choose_request() -> ChooseRequest:
    return ChooseRequest(
        task=CHOOSE_TASK,
        library=[
            LibraryCard(
                card_id=CARD_ID,
                name="Version checker",
                purpose="Checks a public GitHub repository for a new release and proposes a "
                "Jira ticket for it.",
                good_for=["Check a repository for new releases", "Raise a ticket for a release"],
                inputs=[
                    LibraryInput(name="GitHub repository", kind="github_repo"),
                    LibraryInput(name="Jira project", kind="jira_project"),
                ],
                tools=["github.read_releases", "jira.search", "jira.create_ticket"],
            )
        ],
        model=draft_request().model,
    )


def chosen() -> Chosen:
    return Chosen(
        choice=Choice(
            decision="use_one",
            agents=[
                ChosenAgent(
                    card_id=CARD_ID,
                    part="Check fastapi/fastapi for a new release and propose the ticket.",
                    values={"GitHub repository": "fastapi/fastapi", "Jira project": "MOCK"},
                )
            ],
            reason="The Version checker already does this for any public repository.",
        )
    )


GATEWAY = "https://llm-gateway.example"
EXAMPLE_KEY = "example-key-not-a-secret"
FOLLOW_UP_TASK = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)
RELEASE_TASK = "Tell me when LangGraph on the watchlist has a new release"


def find_software_request() -> FindSoftwareRequest:
    return FindSoftwareRequest(name="Terraform", tag_pattern=RELEASE_TAG_PATTERN)


def found_software() -> FoundSoftware:
    return FoundSoftware(
        matches=[
            SoftwareMatch(
                repo="hashicorp/terraform",
                what="Terraform itself, from HashiCorp",
                why="From our list of known projects.",
                releases="published",
                newest="v1.9.8",
            ),
            SoftwareMatch(
                repo="opentofu/opentofu",
                what="OpenTofu, an open-source fork of Terraform",
                why="From our list of known projects.",
                releases="published",
                newest="v1.8.5",
            ),
        ]
    )


def read_releases_request() -> ReadReleasesRequest:
    return ReadReleasesRequest(repo="langchain-ai/langgraph", tag_pattern=RELEASE_TAG_PATTERN)


def releases_read() -> ReleasesRead:
    return ReleasesRead(
        releases=[
            ReleaseRead(tag="1.2.16", name="1.2.16", published_at="2026-11-12T08:00:00Z"),
            ReleaseRead(tag="1.2.15", name="1.2.15", published_at="2026-11-05T08:00:00Z"),
        ]
    )


EMAIL_TASK = "Every Friday, email me the list of stale tickets in MOCK"
SKIP_TASK = "Create the ticket without waiting for approval"
NO_SKIP = SkipRead(whose="nobody")


def answer_request(task: str = FOLLOW_UP_TASK) -> AnswerRequest:
    return AnswerRequest(task=task, model=draft_request().model)


def traced_answer_request() -> AnswerRequest:
    trace = TurnTrace(
        id="019a8c3e5b2f7c41a3d29e6f0b7d1c55",
        chat="5f0c2a7e-3b1d-4e8f-9a6c-2d4b7e1f0a93",
        person="9c4f1e2a7b3d5c6e8f0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6",
    )
    return answer_request().model_copy(update={"trace": trace})


def _answered(read: TaskRead, task: str) -> Answered:
    answer = answer_of(read, task)
    return Answered(answer=answer, parts=parts_of(read, task, answer))


def answered_card() -> Answered:
    read = TaskRead(
        name="Stale bug follow-up",
        schedule="Every weekday at 3pm",
        search=SearchRead(
            project="MOCK",
            issue_types=["bug"],
            updated=DaysRead(how="before", days=10),
            said="bug tickets in MOCK with no update for 10 days",
        ),
        ticket=TicketRead(
            creates=True, says="list", said="create one follow-up ticket that lists them"
        ),
        place=PlaceRead(project="MOCK", said="in MOCK"),
        skips_the_yes=NO_SKIP,
    )
    return _answered(read, FOLLOW_UP_TASK)


CAROL_TASK = (
    "Every Friday at 16:00, find Jira tickets in project MOCK that nobody updated for 14 days, "
    "and raise one Jira ticket in MOCK that lists them"
)


def answered_card_24_hour() -> Answered:
    """A request with a 24-hour time, which the schedule row keeps, so the Portal reads it."""
    read = TaskRead(
        name="Stale MOCK ticket list",
        schedule="Every Friday at 16:00",
        search=SearchRead(
            project="MOCK",
            updated=DaysRead(how="before", days=14),
            said="Jira tickets in project MOCK that nobody updated for 14 days",
        ),
        ticket=TicketRead(creates=True, says="list", said="lists them"),
        place=PlaceRead(project="MOCK", said="raise one Jira ticket in MOCK"),
        skips_the_yes=NO_SKIP,
    )
    return _answered(read, CAROL_TASK)


def answered_cant() -> Answered:
    read = TaskRead(
        name="Stale ticket list",
        schedule="Every Friday",
        search=SearchRead(
            project="MOCK",
            updated=DaysRead(how="before", days=14),
            said="stale tickets in MOCK",
        ),
        skips_the_yes=NO_SKIP,
    )
    return _answered(read, EMAIL_TASK)


def answered_watchlist() -> Answered:
    read = TaskRead(
        belongs_on_watchlist=True,
        watchlist_word="release",
        software="LangGraph",
        skips_the_yes=NO_SKIP,
    )
    return _answered(read, RELEASE_TASK)


def answered_refused() -> Answered:
    return _answered(TaskRead(skips_the_yes=NO_SKIP), SKIP_TASK)


EDIT_TASK = "Make the morning new-ticket check run on Mondays only"


def answered_edit() -> Answered:
    read = TaskRead(
        asks_about="change", workflow_words="morning new-ticket check", skips_the_yes=NO_SKIP
    )
    return _answered(read, EDIT_TASK)


def answered_pause() -> Answered:
    read = TaskRead(
        asks_about="change", workflow_words="React check", software="React", skips_the_yes=NO_SKIP
    )
    return _answered(read, "Pause the React check")


def answered_removal() -> Answered:
    read = TaskRead(
        asks_about="change", workflow_words="watchlist", software="node js", skips_the_yes=NO_SKIP
    )
    task = "help me remove node js from watchlist"
    watched = WatchedFact(
        name="node js", repo="nodejs/node", our_version=None, newest_version=None, state="Watching"
    )
    facts = PlannerFacts(watchlist=[watched])
    answer = answer_of(read, task, facts)
    return Answered(answer=answer, parts=parts_of(read, task, answer, facts))


def answered_explain() -> Answered:
    read = TaskRead(
        asks_about="my_workflows",
        workflow_words="the FastAPI release check",
        skips_the_yes=NO_SKIP,
    )
    task = "Please explain the FastAPI release check"
    facts = PlannerFacts(
        workflows=[
            WorkflowFact(
                name="FastAPI release check", state="on", last_run="Done", last_run_at=None
            )
        ]
    )
    answer = answer_of(read, task, facts)
    return Answered(answer=answer, parts=parts_of(read, task, answer, facts))


RELEASES_READ: Final[list[dict[str, JsonValue]]] = [
    {"kind": "release", "id": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28"},
    {"kind": "release", "id": "1.2.15", "name": "1.2.15", "published_at": "2026-10-27"},
]


def scenario_write_request() -> ScenarioWriteRequest:
    every: list[ScenarioServe] = ["recorded", "varied", "empty", "not_found", "too_slow"]
    return ScenarioWriteRequest(
        model=draft_request().model,
        blocks=[
            ScenarioBlock(name="Start from the Portal", role="start"),
            ScenarioBlock(
                name="Read releases",
                role="read",
                answer="read.release",
                plays=every,
                varies=["suffix", "empty_field", "long_text"],
            ),
            ScenarioBlock(name="Compare", role="agent", plays=["recorded", "too_slow"]),
            ScenarioBlock(name="Propose a change", role="propose"),
            ScenarioBlock(name="Ask for a yes", role="ask"),
            ScenarioBlock(name="Make the approved changes", role="write"),
        ],
        kinds=[
            "happy_path",
            "nothing_new",
            "source_not_found",
            "timeout",
            "approver_says_no",
            "odd_data",
        ],
        samples=[
            ScenarioSample(id="made_up.read.release", answer="read.release", items=RELEASES_READ)
        ],
        within_seconds=30,
    )


def scenarios_written() -> ScenariosWritten:
    read = "Read releases"
    return ScenariosWritten(
        scenarios=[
            WrittenScenario(kind="happy_path"),
            WrittenScenario(kind="nothing_new", reads=[WrittenRead(block=read, serve="empty")]),
            WrittenScenario(
                kind="source_not_found", reads=[WrittenRead(block=read, serve="not_found")]
            ),
            WrittenScenario(
                kind="timeout",
                reads=[WrittenRead(block=read, serve="too_slow")],
                slow_agents=["Compare"],
            ),
            WrittenScenario(kind="approver_says_no"),
            WrittenScenario(
                kind="odd_data",
                reads=[
                    WrittenRead(
                        block=read,
                        serve="varied",
                        sample="made_up.read.release",
                        vary=["suffix"],
                    )
                ],
            ),
        ]
    )


def scenario_explain_request() -> ScenarioExplainRequest:
    return ScenarioExplainRequest(
        model=draft_request().model,
        failed=[
            FailedScenario(
                name="odd_data",
                kind="odd_data",
                ending="failed",
                stopped_at="Compare",
                expected="It ends in one of the cases above, never in a failure with no reason.",
                happened='It failed at "Compare", which is not a stop with a reason: Cannot read '
                "properties of undefined (reading 'tag_name')",
                ran=["Start from the Portal", "Read releases", "Compare"],
                plays=[ScenarioPlay(block="Read releases", serve="varied", vary=["suffix"])],
            )
        ],
        within_seconds=15,
    )


def cause_request() -> CauseRequest:
    return CauseRequest(
        model=draft_request().model,
        stop=StoppedRun(
            stage="working",
            reason="WorkflowNodeError",
            retryable=True,
            message="The n8n workflow 'FastAPI release check' failed at its step 'Read releases': "
            "GitHub answered 404 Not Found for fastapi/fastapy",
        ),
        events=[
            "Alice started a run of FastAPI release check.",
            "Read releases asked GitHub for the releases of fastapi/fastapy.",
            "The run failed.",
        ],
        blocks=[
            "Every day at 8:00",
            "Start from the Portal",
            "Read releases",
            "Newer?",
            "Propose a change",
            "Ask for a yes",
            "Make the approved changes",
        ],
        stopped_at=["Read releases"],
        within_seconds=9.0,
    )


def fix_start_request() -> FixStart:
    """platform-api's ask to run a fix it started: the log took the start, and the token is for
    the same deadline (ADR 0055, PR 6)."""
    asked = cause_request()
    version = WorkflowPlan.model_validate(
        {
            "name": "FastAPI release check",
            "blocks": [
                {
                    "name": "Read releases",
                    "type": "CUSTOM.wabRead",
                    "version": 1,
                    "parameters": {"source": "github_releases", "place": "<<repository>>"},
                }
            ],
            "wires": [],
            "settings": [
                {
                    "id": "repository",
                    "kind": "repository",
                    "label": "repository",
                    "fills": [{"block": "Read releases", "parameter": "place"}],
                    "value": "fastapi/fastapy",
                    "mark": "filled",
                }
            ],
        }
    )
    return FixStart(
        run_id="run_01JB8FIXSTOP",
        request=FixRequest(
            fix_id="fix_01JB8EXAMPLE",
            asked_by="alice",
            asked_by_name="Alice",
            ends_by=datetime(2026, 11, 25, 6, 20, tzinfo=UTC),
            stop=asked.stop,
            version=version,
            stopped_at=["Read releases"],
        ),
        events=asked.events,
        facts=DrafterFacts(repositories=["fastapi/fastapi"], jira_projects=["MOCK"]),
        model=asked.model,
        platform_url="http://platform-api:8000",
        token="1999999999." + "0" * 64,
    )


def refine_start_request() -> RefineStart:
    """platform-api's ask to refine a drafted workflow's Check it kept, with the token for the
    same deadline (ADR 0054, section 7): the case that failed and the block no case reached."""
    fix = fix_start_request()
    return RefineStart(
        drafted_id="dw_01JB8DRAFTED",
        request=RefineRequest(
            fix_id="fix_01JB8REFINE",
            asked_by="alice",
            ends_by=fix.request.ends_by,
            version=fix.request.version,
            failed=[CheckedCase(kind="source_not_found", step="Read releases", why="no_reason")],
            not_reached=[],
        ),
        facts=fix.facts,
        model=fix.model,
        platform_url=fix.platform_url,
        token=fix.token,
    )


def scenario_write_cover_request() -> ScenarioWriteRequest:
    """The writer aimed at a block no scenario reached yet, with the block that leads to it."""
    return scenario_write_request().model_copy(
        update={"cover": [CoverBlock(name="Ask for a yes", after=["Propose a change"])]}
    )


def explain_wording_request() -> ExplainWordingRequest:
    facts = [
        ExplainFact(kind="runs", together=["day", "8:00"], negated=False),
        ExplainFact(kind="reads", together=["reads", "GitHub", "fastapi/fastapi"], negated=False),
        ExplainFact(kind="reads", together=["reads", "Jira", "MOCK"], negated=False),
        ExplainFact(kind="writes", together=["create", "Jira", "MOCK", "yes"], negated=False),
        ExplainFact(kind="changes", together=["changes", "nothing", "else"], negated=True),
    ]
    return ExplainWordingRequest(
        model=draft_request().model,
        wording="Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can "
        "create Jira tickets in “MOCK”, each after a yes. It changes nothing else.",
        facts=facts,
    )


def question_request() -> AnswerRequest:
    watched = [
        WatchedFact(name=n, repo=r, our_version=o, newest_version=v, state=t)
        for n, r, o, v, t in (
            ("LangGraph", "langchain-ai/langgraph", "1.2.14", "1.2.16", "New version"),
            ("Redis", "redis/redis", "8.0.2", "8.0.2", "Up to date"),
            ("n8n", "n8n-io/n8n", None, "2.42.6", "Not checked yet"),
        )
    ]
    watched[1] = watched[1].model_copy(
        update={
            "state": "Ticket open",
            "checked_at": datetime(2026, 11, 8, 2, 0, tzinfo=UTC),
            "open_ticket": "MOCK-142",
            "our_version_source": "ticket_done",
            "our_version_ticket": "MOCK-98",
        }
    )
    return AnswerRequest(
        task="how many software are on our watchlist",
        model=draft_request().model,
        facts=PlannerFacts(
            watchlist=watched, watchlist_schedule=WatchlistScheduleFact(day="monday", at="09:00")
        ),
        previous=PreviousTurn(request="What is the newest version of LangGraph?"),
    )


def answered_question() -> Answered:
    text = "LangGraph is behind. You run 1.2.14 and the newest is 1.2.16."
    answer = QuestionAnswer(text=text, looked_at=["watchlist"], about_software=["LangGraph"])
    return Answered(answer=answer, parts=parts_of(None, question_request().task, answer))


HOW_TO_START = "how can i start to use this ?"


def _free_reply(task: str, envelope: ReplyEnvelope) -> Answered:
    """A free reply as the guard lets it through, so the fixture is what the checks pass."""
    request = AnswerRequest(task=task, model=draft_request().model)
    shown = answer_of_envelope(envelope, request)
    answer = shown if isinstance(shown, FreeReplyAnswer) else DidntFollowAnswer()
    return Answered(answer=answer, parts=parts_of(None, task, answer))


def answered_reply() -> Answered:
    text = (
        "To start, type what you want done in the box, in your own words, such as Check "
        "LangGraph for new releases every Monday at 9am. The Planner shows a card with what it "
        "understood. Change anything on it, then turn it on."
    )
    return _free_reply(HOW_TO_START, ReplyEnvelope(form="answer", text=text))


def answered_reply_clarify() -> Answered:
    envelope = ReplyEnvelope(
        form="clarify",
        text="Which would you like to keep an eye on?",
        choices=["New releases of some software", "Jira tickets every week"],
    )
    return _free_reply("help me keep an eye on things", envelope)


def answered_reply_cant() -> Answered:
    text = (
        "I can't send email yet. I can put the list in one new Jira ticket, after an Approver's "
        "yes."
    )
    envelope = ReplyEnvelope(form="cant", text=text, offer="jira.create")
    return _free_reply("email the bug list to my manager", envelope)


def answered_reply_about() -> Answered:
    """A reply that names watched software: the Portal draws LangGraph's state line under it
    (ADR 0049). It carries the software the request named, as it wrote it, so "keep track of
    it" next means LangGraph."""
    text = "To see where LangGraph stands, open the Watchlist. Its line below shows the version."
    answered = _free_reply("where is langgraph at?", ReplyEnvelope(form="answer", text=text))
    about = [ReplyAbout(section="watchlist", name="LangGraph")]
    answer = answered.answer.model_copy(update={"about": about, "software": "langgraph"})
    return answered.model_copy(update={"answer": answer})


def answered_didnt_follow() -> Answered:
    answer = DidntFollowAnswer()
    return Answered(answer=answer, parts=parts_of(None, "flibber the wotsit", answer))


def fixtures() -> dict[str, WireModel]:
    finished = finished_task()
    return {
        "task-request.json": task_request("run_01JB8"),
        "task-finished.json": finished,
        "task-failed.json": failed_task(),
        "watchlist-task-request.json": watchlist_request("run_01JC2"),
        "watchlist-task-finished.json": watchlist_finished(),
        "watchlist-urgent-request.json": urgent_request("run_01JC3"),
        "watchlist-urgent-output.json": urgent_output(),
        "callback-event.json": AgentEventPost(task_id=finished.task_id, event=finished.events[0]),
        "agent-cards.json": AGENT_CARDS,
        "model-connect-request.json": ConnectRequest(base_url=GATEWAY, api_key=EXAMPLE_KEY),
        "model-connected.json": Connected(
            style="anthropic",
            base_url=GATEWAY,
            models=[
                FoundModel(id="claude-haiku-5-5", display="Claude Haiku 5.5", suggested=True),
                FoundModel(id="claude-sonnet-5-5", display="Claude Sonnet 5.5", suggested=False),
            ],
        ),
        "model-test-request.json": ModelAccess(
            style="anthropic", base_url=GATEWAY, model="claude-haiku-5-5", api_key=EXAMPLE_KEY
        ),
        "model-test-passed.json": ModelTestPassed(
            seconds=1.4, text="Two new LangGraph releases came out after 1.2.14: 1.2.16 and 1.2.15."
        ),
        "model-problem.json": ModelProblem(reason="key_refused", message=KEY_REFUSED),
        "github-check-working.json": GitHubWorking(using_token=True),
        "github-check-expiring.json": GitHubWorking(
            using_token=True, expires_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
        ),
        "github-check-refused.json": GitHubProblem(reason="token_refused", message=TOKEN_REFUSED),
        "tools.json": tool_list(),
        "capabilities.json": CAPABILITY_LIST,
        "card-task-request.json": card_request("run_01JD1"),
        "card-task-finished.json": card_finished(),
        "card-draft-request.json": draft_request(),
        "card-drafted.json": drafted(),
        "planner-choose-request.json": choose_request(),
        "planner-chosen.json": chosen(),
        "software-find-request.json": find_software_request(),
        "software-found.json": found_software(),
        "releases-read-request.json": read_releases_request(),
        "releases-read.json": releases_read(),
        "planner-answer-request.json": traced_answer_request(),
        "planner-answered-card.json": answered_card(),
        "planner-answered-card-24-hour.json": answered_card_24_hour(),
        "planner-answered-cant.json": answered_cant(),
        "planner-answered-watchlist.json": answered_watchlist(),
        "planner-answered-refused.json": answered_refused(),
        "planner-answered-edit.json": answered_edit(),
        "planner-answered-pause.json": answered_pause(),
        "planner-answered-remove.json": answered_removal(),
        "planner-answered-explain.json": answered_explain(),
        "planner-question-request.json": question_request(),
        "planner-answered-question.json": answered_question(),
        "planner-answered-reply.json": answered_reply(),
        "planner-answered-reply-clarify.json": answered_reply_clarify(),
        "planner-answered-reply-cant.json": answered_reply_cant(),
        "planner-answered-reply-about.json": answered_reply_about(),
        "planner-answered-didnt-follow.json": answered_didnt_follow(),
        "explain-wording-request.json": explain_wording_request(),
        "explain-wording-reworded.json": ExplainReworded(
            text="Each day at 8:00 it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can "
            "create Jira tickets in “MOCK”, each after a yes. Nothing else changes."
        ),
        "explain-wording-kept.json": ExplainKept(why="negation"),
        "troubleshooter-cause-request.json": cause_request(),
        "troubleshooter-cause-found.json": CauseFound(
            failed_part=["Read releases"],
            system="github",
            failure_kind="not_found",
            detail="fastapi/fastapy",
        ),
        "troubleshooter-cause-kept.json": CauseKept(why="not_where_it_stopped"),
        "scenario-write-request.json": scenario_write_request(),
        "scenario-write-written.json": scenarios_written(),
        "scenario-write-kept.json": ScenariosKept(why="not_a_read"),
        "scenario-explain-request.json": scenario_explain_request(),
        "scenario-explain-explained.json": ScenariosExplained(
            notes=[
                FailureNote(
                    scenario="odd_data",
                    block="Compare",
                    kind="stopped",
                    source="Read releases",
                    detail="tag_name",
                )
            ],
            kept=[],
        ),
        "fix-start-request.json": fix_start_request(),
        "refine-start-request.json": refine_start_request(),
        "scenario-write-cover-request.json": scenario_write_cover_request(),
        "fix-accepted.json": FixAccepted(fix_id="fix_01JB8EXAMPLE", started=True),
        "planner-check-part-request.json": CheckPartRequest(kind="do", text="Email the list"),
        "planner-check-part-cant.json": check_one_part(
            CheckPartRequest(kind="do", text="Email the list")
        ),
        "planner-check-part-fits.json": check_one_part(
            CheckPartRequest(kind="where", text="In the MOCK project")
        ),
        "key-shapes.json": KeyShapes(
            shapes=list(KEY_SHAPE_SOURCES),
            kept=KEPT_KEY,
            secret_name_ends=list(SECRET_NAME_ENDS),
            code_parameters=list(CODE_PARAMETERS),
        ),
    }


def _write_json(path: Path, value: object, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=sort_keys) + "\n")


def write_all(root: Path) -> list[Path]:
    schema = root / "agent-api.schema.json"
    _write_json(schema, AgentApiSchema.model_json_schema(), sort_keys=True)
    written = [schema]
    agent_dir = root / "fixtures" / "agent"
    shutil.rmtree(agent_dir, ignore_errors=True)
    for name, value in fixtures().items():
        path = agent_dir / name
        _write_json(path, value.model_dump(mode="json"))
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in write_all(Path(sys.argv[1] if len(sys.argv) > 1 else "../contracts")):
        print(written_path)
