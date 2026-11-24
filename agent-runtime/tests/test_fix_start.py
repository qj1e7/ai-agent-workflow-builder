"""Starting a fix in the runtime (ADR 0055, PR 6). platform-api writes the fix's start, with who
asked from the session, and mints the fix's token only once the log took it. Then it asks the
runtime to run the coordinator. The runtime runs each fix id once, sends the token only to an
allowed origin, and keeps trying a hand-back the log never took until the token's grace ends."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from agent_runtime.api import Settings, create_app
from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.contracts import cause_request, draft_request
from agent_runtime.fixing.coordinator import HandedBack, HandedIn, Stopped
from agent_runtime.fixing.events import FixData, FixHandedBackData, FixRefusal
from agent_runtime.fixing.ledger import Unlogged
from agent_runtime.fixing.ports import StoredRevision
from agent_runtime.fixing.starter import (
    TOKEN_GRACE,
    FixStart,
    ModelTroubleshooter,
    Starter,
    hand_back_again,
)
from agent_runtime.summary import ChatFor
from tests.test_api import KEY, ORIGIN, SETTINGS, make_runtime

FIX = "fix_01START"
RUN = "run_01STOPPED"
ENDS_BY = datetime(2026, 11, 25, 6, 20, tzinfo=UTC)
TOKEN = ".".join(["1999999999", "ab" * 32])
VERSION = WorkflowPlan.model_validate(
    {
        "name": "Release check",
        "blocks": [
            {
                "name": "Read new releases",
                "type": "CUSTOM.wabRead",
                "version": 1,
                "parameters": {"source": "github_releases", "place": "langchain-ai/langgraph"},
            }
        ],
        "wires": [],
        "settings": [],
    }
)
LOST_HAND_BACK = Unlogged("fix_handed_back", None, "failed")


def body(platform_url: str = ORIGIN, fix_id: str = FIX) -> dict[str, Any]:
    asked = cause_request()
    return {
        "run_id": RUN,
        "request": {
            "fix_id": fix_id,
            "asked_by": "alice",
            "asked_by_name": "Alice",
            "ends_by": ENDS_BY.isoformat(),
            "stop": asked.stop.model_dump(mode="json"),
            "version": VERSION.model_dump(mode="json"),
            "stopped_at": ["Read new releases"],
        },
        "events": asked.events,
        "facts": {"repositories": ["langchain-ai/langgraph"]},
        "model": json.loads(draft_request().model.model_dump_json()),
        "platform_url": platform_url,
        "token": TOKEN,
    }


def app_with(starter: Starter, settings: Settings = SETTINGS) -> TestClient:
    return TestClient(
        create_app(settings, make_runtime(), fixes=starter), headers={"X-Agent-Key": KEY}
    )


class Ran:
    """The fixes a starter ran, in order, run at once rather than in a thread."""

    def __init__(self) -> None:
        self.fixes: list[FixStart] = []

    def starter(self) -> Starter:
        return Starter(self.fixes.append, spawn=lambda work: work())


# The route


def test_a_fix_runs_once_for_its_fix_id_however_often_it_is_asked():
    ran = Ran()
    client = app_with(ran.starter())
    first = client.post("/v1/fixes", json=body())
    again = client.post("/v1/fixes", json=body())
    assert (first.status_code, first.json()) == (202, {"fix_id": FIX, "started": True})
    assert (again.status_code, again.json()) == (202, {"fix_id": FIX, "started": False})
    [started] = ran.fixes
    assert (started.run_id, started.token, started.request.asked_by) == (RUN, TOKEN, "alice")


def test_the_fix_s_token_goes_only_to_an_allowed_origin():
    ran = Ran()
    answer = app_with(ran.starter()).post(
        "/v1/fixes", json=body(platform_url="https://elsewhere.example")
    )
    assert answer.status_code == 422
    assert ran.fixes == []


def test_only_platform_api_with_the_agent_key_starts_a_fix():
    ran = Ran()
    client = app_with(ran.starter())
    client.headers.pop("X-Agent-Key")
    assert client.post("/v1/fixes", json=body()).status_code == 401
    assert ran.fixes == []


def test_a_request_the_coordinator_can_t_take_starts_nothing():
    ran = Ran()
    broken = body()
    broken["request"]["stopped_at"] = ["A block the version doesn't have"]
    assert app_with(ran.starter()).post("/v1/fixes", json=broken).status_code == 422
    assert ran.fixes == []


# The troubleshooter


def test_the_troubleshooter_asks_the_model_with_the_run_s_facts_and_never_past_ten_seconds():
    seen: list[float] = []
    found = CauseFound(
        failed_part=["Read new releases"],
        system="github",
        failure_kind="not_found",
        detail="langchain-ai/langgraph",
    )

    def ask(request: Any, chat_for: ChatFor) -> CauseFound:
        seen.append(request.within_seconds)
        assert request.stopped_at == ["Read new releases"]
        assert request.blocks == ["Read new releases"]
        return found

    start = FixStart.model_validate(body())
    troubleshooter = ModelTroubleshooter(start, lambda _timeout: None, ask=ask)  # type: ignore[arg-type,return-value]
    assert troubleshooter.find_cause(None, 600.0) == found
    assert troubleshooter.find_cause(None, 0.0) is None
    assert seen == [10.0]


# A hand-back the log never took


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Log:
    def __init__(self, *answers: FixRefusal | None | Exception) -> None:
        self.answers = list(answers)
        self.noted: list[FixData] = []

    def note(self, data: FixData) -> FixRefusal | None:
        self.noted.append(data)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def handed_back(*unlogged: Unlogged) -> HandedBack:
    return HandedBack(why="no_progress", cause=None, rounds=(), unlogged=unlogged)


def test_a_hand_back_a_log_that_stays_down_never_took_is_tried_until_the_token_s_grace_ends():
    clock = Clock(ENDS_BY - timedelta(minutes=5))
    log = Log(ConnectionError("platform-api didn't answer"))
    until = ENDS_BY + TOKEN_GRACE
    taken = hand_back_again(handed_back(LOST_HAND_BACK), log, FIX, until, clock, clock.wait)
    assert taken is False
    assert clock.now >= until
    assert len(log.noted) > 2
    assert all(data == FixHandedBackData(fix_id=FIX, why="no_progress") for data in log.noted[:2])


def test_the_tries_stop_once_the_log_takes_the_hand_back():
    clock = Clock(ENDS_BY - timedelta(minutes=5))
    log = Log(ConnectionError("down"), ConnectionError("down"), None)
    taken = hand_back_again(
        handed_back(LOST_HAND_BACK), log, FIX, ENDS_BY + TOKEN_GRACE, clock, clock.wait
    )
    assert taken is True
    assert log.noted == [FixHandedBackData(fix_id=FIX, why="no_progress")] * 3


def test_past_the_deadline_the_hand_back_is_tried_for_time():
    clock = Clock(ENDS_BY + timedelta(minutes=1))
    log = Log(ConnectionError("down"), "ended", None)
    taken = hand_back_again(
        handed_back(LOST_HAND_BACK), log, FIX, ENDS_BY + TOKEN_GRACE, clock, clock.wait
    )
    assert taken is True
    assert log.noted[-1] == FixHandedBackData(fix_id=FIX, why="time_limit")


def test_nothing_is_tried_again_when_the_log_took_the_end():
    clock = Clock(ENDS_BY)
    log = Log(None)
    stored = StoredRevision(2, "sha256:" + "ab" * 32)
    for outcome in (
        handed_back(),
        handed_back(Unlogged("fix_handoff", 2, "failed")),
        Stopped("failed", stored=stored),
        HandedIn(2, stored.digest, VERSION, None, (), ()),  # type: ignore[arg-type]
    ):
        assert hand_back_again(outcome, log, FIX, ENDS_BY + TOKEN_GRACE, clock, clock.wait)
    assert log.noted == []
