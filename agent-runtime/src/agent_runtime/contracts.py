import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_runtime.api import AGENT_CARDS
from agent_runtime.contract import (
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
    CarryForward,
    Connected,
    ConnectRequest,
    Finding,
    FoundModel,
    GithubSource,
    ModelAccess,
    ModelProblem,
    ModelTestPassed,
    ProposedIntent,
    ReleaseCheckInputs,
    RoomAddressee,
    SoftwareToCheck,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    WatchlistInputs,
    WireModel,
    agent_event_adapter,
)
from agent_runtime.model_access import KEY_REFUSED

ROOM_LEAD = AgentRef(id="room_lead", display="Room lead")
CHECKER = AgentRef(id="release_checker", display="Release checker")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
TO_ROOM = RoomAddressee()

REPO = "langchain-ai/langgraph"
LAST_KNOWN_TAG = "1.2.14"
NEW_TAGS = ["1.2.16", "1.2.15"]
TICKET_TITLE = "New LangGraph releases: 1.2.16, 1.2.15"
TICKET_BODY = (
    "Releases newer than 1.2.14 on langchain-ai/langgraph:\n- 1.2.16\n- 1.2.15\n\n"
    "Proposed by the AI workflow builder."
)
LANGGRAPH_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2M"
REDIS_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2N"
FASTAPI_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2P"
WATCHLIST_TICKET_BODY = (
    "LangGraph has 2 new releases on GitHub (langchain-ai/langgraph) newer than our version "
    "1.2.14:\n- 1.2.16\n- 1.2.15\n\nProposed by the AI workflow builder."
)
GITHUB_503 = "GitHub returned 503 Service Unavailable three times"

WATCHLIST_T0 = datetime(2026, 11, 10, 2, 14, tzinfo=UTC)
SUCCESS_T0 = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)
FAILURE_T0 = datetime(2026, 11, 4, 2, 14, tzinfo=UTC)


def task_request(run_id: str) -> TaskRequest:
    task_id = f"{run_id}/work/1/1"
    return TaskRequest(
        task_id=task_id,
        run_id=run_id,
        instruction="Check langchain-ai/langgraph for new releases and open a ticket for the team.",
        inputs=ReleaseCheckInputs(repo=REPO, tag_pattern=r"^\d+\.\d+\.\d+$"),
        carry_forward=CarryForward(last_known_tag=LAST_KNOWN_TAG),
        callback=Callback(
            url=f"http://platform-api:8000/internal/v1/runs/{run_id}/agent-events?task={task_id}",
            token="example-callback-token-not-a-secret",
        ),
    )


def watchlist_software() -> list[SoftwareToCheck]:
    return [
        SoftwareToCheck(
            id=LANGGRAPH_ID,
            name="LangGraph",
            source=GithubSource(ref=REPO),
            our_version=LAST_KNOWN_TAG,
        ),
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
        instruction="Check the team's watched software for new releases and raise an upgrade "
        "ticket for each one that is behind.",
        inputs=WatchlistInputs(tag_pattern=r"^\d+\.\d+\.\d+$", software=watchlist_software()),
        carry_forward=CarryForward(last_known_tag=None),
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


def room_opens(rec: Recorder, base: float) -> None:
    rec.add(
        AgentJoinedEvent,
        base + 0.29,
        ROOM_LEAD,
        "Room lead brought in Release checker to read the GitHub releases.",
        AgentJoinedData(agent=CHECKER, reason="The task asks about releases of a GitHub repo."),
    )
    rec.add(
        AgentMessageEvent,
        base + 0.41,
        ROOM_LEAD,
        "Room lead asked Release checker to look for releases newer than 1.2.14.",
        AgentMessageData(
            speaker=ROOM_LEAD,
            addressee=TO_CHECKER,
            text=f"Please check {REPO} for releases newer than {LAST_KNOWN_TAG}.",
        ),
    )
    rec.add(
        AgentStepStartedEvent,
        base + 0.54,
        CHECKER,
        f"Release checker is fetching releases from {REPO}.",
        AgentStepStartedData(step="fetch_releases"),
    )


def finished_task() -> TaskFinished:
    rec = Recorder(SUCCESS_T0)
    room_opens(rec, 2.1)
    rec.add(
        AgentStepFinishedEvent,
        4.873,
        CHECKER,
        "Release checker fetched 30 releases. The latest is 1.2.16.",
        AgentStepFinishedData(
            step="fetch_releases", result={"release_count": 30, "latest": "1.2.16"}
        ),
    )
    rec.add(
        AgentStepStartedEvent,
        4.901,
        CHECKER,
        "Release checker is comparing them with the last known tag 1.2.14.",
        AgentStepStartedData(step="find_new"),
    )
    rec.add(
        AgentStepFinishedEvent,
        4.955,
        CHECKER,
        "Release checker found 2 new releases: 1.2.16, 1.2.15.",
        AgentStepFinishedData(step="find_new", result={"new_count": 2, "tags": NEW_TAGS}),
    )
    rec.add(
        AgentMessageEvent,
        5.12,
        CHECKER,
        "Release checker reported 2 new releases to the room and suggested one ticket.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="Two releases are newer than 1.2.14: 1.2.16 and 1.2.15. "
            "I suggest one ticket for both.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.301,
        ROOM_LEAD,
        "Room lead agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=ROOM_LEAD,
            addressee=TO_CHECKER,
            text="Agreed. I'll draft one ticket for an Approver to check.",
        ),
    )
    return TaskFinished(
        task_id="run_01JB8/work/1/1",
        output=TaskOutput(
            summary="2 new releases: 1.2.16, 1.2.15",
            new_tags=NEW_TAGS,
            proposed=[
                ProposedIntent(
                    kind="create_ticket",
                    fields={"title": TICKET_TITLE, "body": TICKET_BODY},
                    reason="New plain-version releases since 1.2.14",
                )
            ],
            carry_forward=CarryForward(last_known_tag="1.2.16"),
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
        f"Release checker is reading the releases of {name}.",
        AgentStepStartedData(step="read_source"),
    )
    rec.add(
        AgentStepFinishedEvent,
        start + 0.4,
        CHECKER,
        f"Release checker {said}",
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
        ROOM_LEAD,
        "Room lead brought in Release checker to read the sources of 3 watched software.",
        AgentJoinedData(
            agent=CHECKER, reason="The task asks about releases of several watched software."
        ),
    )
    rec.add(
        AgentMessageEvent,
        2.3,
        ROOM_LEAD,
        "Room lead asked Release checker to check 3 watched software for new releases.",
        AgentMessageData(
            speaker=ROOM_LEAD,
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
        "Release checker could not check FastAPI and carried on.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="I could not read FastAPI's releases: GitHub answered 404 Not Found. "
            "I will carry on with the rest.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.0,
        CHECKER,
        "Release checker reported 1 of 3 watched software behind and suggested 1 ticket.",
        AgentMessageData(
            speaker=CHECKER,
            addressee=TO_ROOM,
            text="1 of 3 watched software has new releases: LangGraph. I suggest one ticket.",
        ),
    )
    rec.add(
        AgentMessageEvent,
        5.2,
        ROOM_LEAD,
        "Room lead agreed and will propose the ticket for approval.",
        AgentMessageData(
            speaker=ROOM_LEAD,
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
                    fields={
                        "title": "Upgrade LangGraph from 1.2.14 to 1.2.16",
                        "body": WATCHLIST_TICKET_BODY,
                    },
                    reason="LangGraph 1.2.16 is out, and we run 1.2.14",
                    subject=LANGGRAPH_ID,
                )
            ],
            carry_forward=CarryForward(last_known_tag=None),
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
    room_opens(rec, 2.08)
    for try_number, seconds in enumerate((4.702, 8.811, 12.934), start=1):
        last = try_number == 3
        rec.add(
            AgentMessageEvent,
            seconds,
            CHECKER,
            f"Release checker reported that GitHub answered 503 (try {try_number} of 3).",
            AgentMessageData(
                speaker=CHECKER,
                addressee=TO_ROOM,
                text=f"GitHub answered 503 Service Unavailable (try {try_number} of 3). "
                + ("I am giving up." if last else "Waiting 2 s before trying again."),
            ),
        )
    rec.add(
        AgentFailedEvent,
        12.961,
        CHECKER,
        "Release checker failed: GitHub was unavailable.",
        AgentFailedData(
            step="fetch_releases",
            error_type="UpstreamUnavailable",
            message=GITHUB_503,
            retryable=True,
        ),
    )
    return TaskFailed(
        task_id="run_01JB9/work/1/1",
        error=TaskError(type="UpstreamUnavailable", message=GITHUB_503, retryable=True),
        events=rec.events,
    )


GATEWAY = "https://llm-gateway.example"
EXAMPLE_KEY = "example-key-not-a-secret"


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
