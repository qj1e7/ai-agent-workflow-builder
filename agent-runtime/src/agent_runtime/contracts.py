import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    Callback,
    CardBlock,
    CardDraft,
    CardInput,
    CardsInputs,
    CardSpec,
    CardToRun,
    CarryForward,
    Choice,
    ChooseRequest,
    Chosen,
    ChosenAgent,
    Connected,
    ConnectRequest,
    DraftApproval,
    DraftBlock,
    Drafted,
    DraftInput,
    DraftRequest,
    Finding,
    FoundModel,
    GithubSource,
    LibraryCard,
    LibraryInput,
    MissingTool,
    ModelAccess,
    ModelProblem,
    ModelTestPassed,
    ProposedIntent,
    RoomAddressee,
    SoftwareToCheck,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    UnderstandRequest,
    WatchlistInputs,
    WireModel,
    agent_event_adapter,
)
from agent_runtime.model_access import KEY_REFUSED
from agent_runtime.planner import RowAnswer, UnderstandAnswer, understood_of
from agent_runtime.tools import tool_list

PLANNER = AgentRef(id="planner", display="Planner")
CHECKER = AgentRef(id="version_checker", display="Version checker")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
TO_ROOM = RoomAddressee()

REPO = "langchain-ai/langgraph"
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
        callback=Callback(
            url=f"http://platform-api:8000/internal/v1/runs/{run_id}/agent-events?task={task_id}",
            token="example-callback-token-not-a-secret",
        ),
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
                ),
                Finding(
                    software_id=REDIS_ID,
                    state="up_to_date",
                    newest="8.2.1",
                    new_versions=[],
                    detail="Nothing is newer than 8.2.1.",
                ),
                Finding(
                    software_id=FASTAPI_ID,
                    state="cant_check",
                    newest=None,
                    new_versions=[],
                    detail="GitHub answered 404 Not Found.",
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
        "Version checker searches Jira project MOCK.",
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
RELEASE_TASK = "Tell me when LangGraph has a new release"


def understand_request() -> UnderstandRequest:
    return UnderstandRequest(task=FOLLOW_UP_TASK, model=draft_request().model)


def understood() -> WireModel:
    answer = UnderstandAnswer(
        belongs_on_watchlist=False,
        rows=[
            RowAnswer(kind="schedule", text="Every weekday at 3pm", state="understood"),
            RowAnswer(
                kind="look_for",
                text="Bug tickets in MOCK with no update for 10 days",
                state="understood",
            ),
            RowAnswer(
                kind="do", text="Create one follow-up ticket that lists them", state="understood"
            ),
            RowAnswer(kind="where", text="Jira project MOCK", state="understood"),
        ],
    )
    result = understood_of(answer, FOLLOW_UP_TASK)
    assert result is not None
    return result


def belongs_on_watchlist() -> WireModel:
    answer = UnderstandAnswer(
        belongs_on_watchlist=True, watchlist_word="release", software="LangGraph"
    )
    result = understood_of(answer, RELEASE_TASK)
    assert result is not None
    return result


def fixtures() -> dict[str, WireModel]:
    finished = finished_task()
    return {
        "task-request.json": task_request("run_01JB8"),
        "task-finished.json": finished,
        "task-failed.json": failed_task(),
        "watchlist-task-request.json": watchlist_request("run_01JC2"),
        "watchlist-task-finished.json": watchlist_finished(),
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
        "tools.json": tool_list(),
        "card-task-request.json": card_request("run_01JD1"),
        "card-task-finished.json": card_finished(),
        "card-draft-request.json": draft_request(),
        "card-drafted.json": drafted(),
        "planner-choose-request.json": choose_request(),
        "planner-chosen.json": chosen(),
        "planner-understand-request.json": understand_request(),
        "planner-understood.json": understood(),
        "planner-watchlist.json": belongs_on_watchlist(),
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
