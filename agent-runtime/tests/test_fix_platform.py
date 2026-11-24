"""The fix's parts that platform-api answers (ADR 0055, PR 5): the Scenario writer, the simulation,
the checker and the recorder of the fix's events. The runtime holds no simulation secret and
reaches no gateway, so each is a call to platform-api with the fix's own token, told the seconds
left. The model writes or explains only when the fix can still pay for the call at its most, and
a call that asked the model counts toward the fix's cost at that most. The recorder tries an end
event again when the log can't be reached, so a lost end never leaves the fix open."""

import json
import secrets
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.fixing.cost import FixCost, counted, prices_by_model
from agent_runtime.fixing.events import (
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
)
from agent_runtime.fixing.platform_parts import (
    END_TRIES,
    EXPLAIN_CHARGE,
    FIX_TOKEN_HEADER,
    WRITE_CHARGE,
    PlatformParts,
)
from agent_runtime.fixing.ports import (
    Scenario,
    ScenarioNote,
    ScenarioResult,
    Simulated,
    StoredRevision,
)
from agent_runtime.model_cost import packaged_prices

BASE = "http://platform-api:8000"
RUN = "run_01STOPPED"
FIX = "fix_01EVAL"
TOKEN = ".".join(["1999999999", secrets.token_hex(32)])
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
HAPPY = Scenario(name="happy_path", kind="happy_path")


class Platform:
    """platform-api's fix routes, as a test plays them."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, Any], httpx.Request]] = []
        self.answers: dict[str, list[httpx.Response | Exception]] = {}

    def answer(self, route: str, *answers: httpx.Response | Exception) -> None:
        self.answers[route] = list(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        route = request.url.path.rsplit("/", 1)[-1]
        self.asked.append((route, json.loads(request.content), request))
        given = self.answers.get(route) or [httpx.Response(500)]
        answer = given.pop(0) if len(given) > 1 else given[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def parts(platform: Platform, slept: list[float] | None = None) -> PlatformParts:
    client = httpx.Client(transport=httpx.MockTransport(platform))
    naps = slept if slept is not None else []
    return PlatformParts(BASE, RUN, FIX, TOKEN, client=client, sleep=naps.append)


def plenty() -> float:
    return 2.0


def nothing() -> float:
    return 0.0


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


# Every call


def test_each_call_goes_to_the_stopped_run_s_fix_with_its_token_and_the_seconds_left():
    platform = Platform()
    platform.answer("checks", ok({"passes": True, "findings": []}))
    assert parts(platform).passes(VERSION, 42.0, plenty) is True
    [(route, body, request)] = platform.asked
    assert str(request.url) == f"{BASE}/internal/v1/runs/{RUN}/fixes/{FIX}/checks"
    assert request.headers[FIX_TOKEN_HEADER] == TOKEN
    assert body == {"version": VERSION.model_dump(mode="json")}
    assert request.extensions["timeout"]["read"] == pytest.approx(42.0)


# The Scenario writer


def test_the_writer_s_scenarios_come_back_as_data_with_their_kinds():
    platform = Platform()
    platform.answer(
        "scenarios",
        ok(
            {
                "scenarios": [
                    {"kind": "happy_path", "name": "happy_path", "reads": {}, "agents": {}},
                    {
                        "kind": "source_not_found",
                        "name": "source_not_found",
                        "reads": {"Read new releases": {"serve": "not_found"}},
                        "agents": {},
                    },
                ],
                "asked_model": False,
            }
        ),
    )
    written = parts(platform).write(VERSION, [], 30.0, plenty)
    assert written == [
        HAPPY,
        Scenario(
            name="source_not_found",
            kind="source_not_found",
            reads={"Read new releases": {"serve": "not_found"}},
        ),
    ]
    [(_, body, _)] = platform.asked
    assert body == {
        "version": VERSION.model_dump(mode="json"),
        "cover": [],
        "may_ask_model": True,
        "within_seconds": 30.0,
    }


def test_the_writer_asks_the_model_only_when_the_fix_can_pay_for_its_most():
    platform = Platform()
    platform.answer("scenarios", ok({"scenarios": [], "asked_model": False}))
    parts(platform).write(VERSION, [], 30.0, lambda: WRITE_CHARGE / 2)
    assert platform.asked[0][1]["may_ask_model"] is False


def test_a_call_that_asked_the_model_counts_at_its_most_toward_the_fix_s_cost():
    platform = Platform()
    platform.answer(
        "scenarios",
        ok({"scenarios": [HAPPY.model_dump(mode="json")], "asked_model": True}),
    )
    platform.answer(
        "simulations",
        ok(
            {
                "results": [{"name": "happy_path", "verdict": "failed", "reached": []}],
                "not_reached": [],
                "named": [],
                "asked_model": True,
            }
        ),
    )
    cost = FixCost(prices_by_model(packaged_prices()))
    with counted(cost):
        parts(platform).write(VERSION, [], 30.0, plenty)
        parts(platform).run(VERSION, [HAPPY], 60.0, plenty)
    assert cost.dollars == pytest.approx(WRITE_CHARGE + EXPLAIN_CHARGE)
    assert 0 < EXPLAIN_CHARGE < WRITE_CHARGE < 0.2


def test_no_scenarios_or_a_platform_that_does_not_answer_is_no_answer():
    for answer in (
        ok({"scenarios": [], "asked_model": False}),
        httpx.Response(503, json={"detail": "The practice systems didn't answer."}),
        httpx.ConnectError("refused"),
        ok({"scenarios": [{"kind": "made_up", "name": "x"}], "asked_model": False}),
    ):
        platform = Platform()
        platform.answer("scenarios", answer)
        assert parts(platform).write(VERSION, [], 30.0, plenty) is None


# The simulation


def test_a_simulation_gives_each_grade_where_it_stopped_why_and_what_it_reached():
    platform = Platform()
    platform.answer(
        "simulations",
        ok(
            {
                "results": [
                    {
                        "name": "replay_the_stop",
                        "verdict": "failed",
                        "step": "Read new releases",
                        "why": "stopped",
                        "reached": ["read:github_releases"],
                        "note": {"block": "Read new releases", "kind": "stopped", "source": None},
                    },
                ],
                "not_reached": ["Tell"],
                "named": ["read:github_releases"],
                "asked_model": False,
            }
        ),
    )
    simulated = parts(platform).run(VERSION, [HAPPY], 60.0, nothing)
    assert simulated == Simulated(
        results=[
            ScenarioResult(
                name="replay_the_stop",
                verdict="failed",
                step="Read new releases",
                why="stopped",
                reached=["read:github_releases"],
                note=ScenarioNote(block="Read new releases", kind="stopped"),
            )
        ],
        not_reached=["Tell"],
        named=["read:github_releases"],
    )
    [(_, body, _)] = platform.asked
    assert body == {
        "version": VERSION.model_dump(mode="json"),
        "scenarios": [HAPPY.model_dump(mode="json")],
        "may_ask_model": False,
        "within_seconds": 60.0,
    }


def test_a_simulation_that_does_not_answer_is_no_answer():
    for answer in (httpx.Response(503), httpx.ReadTimeout("slow"), ok({"results": "nope"})):
        platform = Platform()
        platform.answer("simulations", answer)
        assert parts(platform).run(VERSION, [HAPPY], 60.0, plenty) is None


# The checker


def test_the_checker_s_refusal_or_no_answer_is_a_fail():
    for answer in (
        ok({"passes": False, "findings": ["off_block"]}),
        httpx.Response(500),
        httpx.ConnectError("refused"),
    ):
        platform = Platform()
        platform.answer("checks", answer)
        assert parts(platform).passes(VERSION, 10.0, plenty) is False


# The recorder

PROPOSED = FixProposedData(fix_id=FIX, version=2, digest="sha256:" + "a" * 64)
HANDED_BACK = FixHandedBackData(fix_id=FIX, why="no_progress")
HANDOFF = FixHandoffData(fix_id=FIX, handoff=1, to="checker", found="passed")


def test_an_event_goes_to_the_log_with_its_kind_and_the_log_s_refusal_comes_back():
    platform = Platform()
    platform.answer("events", ok({"refused": None}), ok({"refused": "ended"}))
    recorder = parts(platform)
    assert recorder.note(HANDOFF) is None
    assert recorder.note(HANDED_BACK) == "ended"
    assert [body for _, body, _ in platform.asked] == [
        {"kind": "fix_handoff", "data": HANDOFF.model_dump(mode="json")},
        {"kind": "fix_handed_back", "data": HANDED_BACK.model_dump(mode="json")},
    ]


@pytest.mark.parametrize("end", [PROPOSED, HANDED_BACK])
def test_an_end_event_is_tried_again_until_the_log_takes_it(end: Any):
    platform = Platform()
    platform.answer(
        "events", httpx.ConnectError("down"), httpx.Response(502), ok({"refused": None})
    )
    slept: list[float] = []
    assert parts(platform, slept).note(end) is None
    assert len(platform.asked) == 3
    assert len(slept) == 2 and all(0 < nap <= 2 for nap in slept)


def test_an_end_event_the_log_never_takes_fails_after_its_tries():
    platform = Platform()
    platform.answer("events", httpx.ConnectError("down"))
    with pytest.raises(httpx.HTTPError):
        parts(platform).note(PROPOSED)
    assert len(platform.asked) == END_TRIES


def test_a_hand_off_s_event_is_tried_once_so_the_fix_goes_on():
    platform = Platform()
    platform.answer("events", httpx.ConnectError("down"))
    with pytest.raises(httpx.HTTPError):
        parts(platform).note(HANDOFF)
    assert len(platform.asked) == 1


def test_a_refusal_is_never_tried_again():
    platform = Platform()
    platform.answer("events", ok({"refused": "not_stopped"}))
    assert parts(platform).note(PROPOSED) == "not_stopped"
    assert len(platform.asked) == 1


# The store of revisions

CAUSE = CauseFound(
    failed_part=["Read new releases"],
    system="github",
    failure_kind="not_found",
    detail="langchain-ai/langgraph",
)
DIGEST = "sha256:" + "c" * 64


def test_a_fix_is_stored_under_its_fix_id_with_the_cause_code_confirmed():
    platform = Platform()
    platform.answer("revisions", ok({"version": 3, "digest": DIGEST}))
    assert parts(platform).store(VERSION, CAUSE, 20.0) == StoredRevision(3, DIGEST)
    [(_, body, request)] = platform.asked
    assert str(request.url) == f"{BASE}/internal/v1/runs/{RUN}/fixes/{FIX}/revisions"
    assert request.headers[FIX_TOKEN_HEADER] == TOKEN
    assert body == {
        "version": VERSION.model_dump(mode="json"),
        "cause": CAUSE.model_dump(mode="json", exclude={"kind"}),
    }


@pytest.mark.parametrize("answer", [httpx.Response(409), httpx.ConnectError("down")])
def test_a_store_platform_api_refused_or_never_answered_raises(answer: Any):
    platform = Platform()
    platform.answer("revisions", answer)
    with pytest.raises(httpx.HTTPError):
        parts(platform).store(VERSION, CAUSE, 20.0)


# platform-api's contract

OPENAPI = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
ROUTES = {
    "events": ("FixEventIn", "FixEventOut"),
    "scenarios": ("FixScenariosIn", "FixScenariosOut"),
    "simulations": ("FixSimulationIn", "FixSimulationOut"),
    "checks": ("FixCheckIn", "FixCheckOut"),
    "revisions": ("FixRevisionIn", "FixRevisionOut"),
}


@pytest.mark.skipif(not OPENAPI.exists(), reason="contracts/ is not in the test image")
def test_each_call_sends_what_platform_api_publishes_and_reads_what_it_answers():
    published = json.loads(OPENAPI.read_text())
    schemas = published["components"]["schemas"]
    platform = Platform()
    platform.answer("events", ok({"refused": None}))
    platform.answer("scenarios", ok({"scenarios": [], "asked_model": False}))
    platform.answer(
        "simulations", ok({"results": [], "not_reached": [], "named": [], "asked_model": False})
    )
    platform.answer("checks", ok({"passes": True, "findings": []}))
    platform.answer("revisions", ok({"version": 3, "digest": DIGEST}))
    recorder = parts(platform)
    recorder.note(HANDOFF)
    recorder.write(VERSION, [], 30.0, plenty)
    recorder.run(VERSION, [HAPPY], 60.0, plenty)
    recorder.passes(VERSION, 10.0, plenty)
    recorder.store(VERSION, CAUSE, 10.0)
    assert [route for route, _, _ in platform.asked] == list(ROUTES)
    for route, body, request in platform.asked:
        sent, answered = ROUTES[route]
        path = request.url.path.replace(RUN, "{run_id}").replace(FIX, "{fix_id}")
        assert "post" in published["paths"][path], path
        schema = schemas[sent]
        assert set(schema["required"]) <= set(body) <= set(schema["properties"]), route
        assert set(schemas[answered]["required"]) == set(schemas[answered]["properties"])
    assert set(schemas["FixResultOut"]["properties"]) == set(ScenarioResult.model_fields)
    assert set(schemas["FixNoteOut"]["properties"]) == {"block", "kind", "source"}
    assert set(schemas["ScenarioSpec"]["properties"]) == set(Scenario.model_fields)
