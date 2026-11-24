"""What platform-api answers for a fix (ADR 0055, PR 5): the coordinator in the agent runtime asks
it for scenarios, a simulation and the checker's grade of a plan, and writes the fix's events.
The runtime holds no simulation secret and reaches no gateway, so platform-api lays the plan out
as any layout, sends it to the simulation gateway, and grades it as it grades any version.

Each call carries a token for one fix on one stopped run, which ends a few minutes after the
fix's deadline, so the hand-back for time can still be written. The model writes scenarios and
explains failures only when Simulation mode's model is turned on, and only when the runtime says
the fix can still pay for it. Otherwise code's templates run, and nothing is explained."""

import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.builder import fix_http
from platform_api.builder.fix_parts import (
    FIX_TOKEN_GRACE,
    FIX_TOKEN_HEADER,
    FixLayouts,
    FixParts,
    FixScenariosIn,
    FixSimulationIn,
    fix_token,
    fix_token_ok,
)
from platform_api.monitoring import FixData, FixHandedBackData, FixRefused
from platform_api.orchestration import (
    DIDNT_ANSWER,
    FailureNote,
    KnownOptions,
    NotSimulated,
    PlanOut,
    ResultOut,
    ScenarioSpec,
    SimulationOut,
    WorkflowPlan,
)
from platform_api.shared import RunId
from tests.test_drafted_layout import ERROR_WORKFLOW, KNOWN, ZONE, release_check

KEY = secrets.token_hex(32)
RUN = RunId("run_01STOPPED")
FIX = "fix_01EVAL"
ENDS_BY = datetime(2026, 11, 25, 6, 20, tzinfo=UTC)
KINDS = ["happy_path", "nothing_new", "approver_says_no"]


def plan_out() -> PlanOut:
    return PlanOut.model_validate({"blocks": [], "kinds": KINDS, "samples": []})


def result(name: str, verdict: str = "passed", **changes: Any) -> ResultOut:
    given: dict[str, Any] = {
        "name": name,
        "kind": "happy_path",
        "verdict": verdict,
        "expected": "It reaches the yes.",
        "happened": "It reached the yes.",
        "ran": ["Start from the Portal", "Read new releases"],
        "not_tried": [],
        "ending": "reached_yes",
        "stopped_at": None,
        "plays": [],
        "reached": ["read:github_releases"],
    }
    return ResultOut.model_validate(given | changes)


def simulation_out(*results: ResultOut) -> SimulationOut:
    return SimulationOut.model_validate(
        {
            "tried": len(results),
            "passed": sum(r.verdict == "passed" for r in results),
            "results": [r.model_dump() for r in results],
            "coverage": {
                "not_reached": ["Tell"],
                "not_tried": [],
                "kinds_without_a_scenario": [],
            },
            "blocks": [],
            "scenarios_from": "given",
            "refused": [],
            "named": ["propose:jira.create_ticket", "read:github_releases"],
        }
    )


class FakeGateway:
    def __init__(self) -> None:
        self.planned: list[Mapping[str, Any]] = []
        self.simulated: list[tuple[Mapping[str, Any], list[ScenarioSpec] | None, bool]] = []
        self.answer: SimulationOut | NotSimulated = simulation_out(result("happy_path"))
        self.plan_answer: PlanOut | NotSimulated = plan_out()

    async def plan(self, version: Mapping[str, Any]) -> PlanOut | NotSimulated:
        self.planned.append(version)
        return self.plan_answer

    async def simulate(
        self,
        version: Mapping[str, Any],
        scenarios: Sequence[ScenarioSpec] | None = None,
        *,
        fall_back: bool = False,
    ) -> SimulationOut | NotSimulated:
        self.simulated.append((version, None if scenarios is None else list(scenarios), fall_back))
        return self.answer


class FakeModel:
    def __init__(self) -> None:
        self.wrote: list[PlanOut] = []
        self.noted: list[list[str]] = []

    async def write(self, plan: PlanOut) -> list[ScenarioSpec] | None:
        self.wrote.append(plan)
        return [ScenarioSpec(kind="happy_path", name="happy_path", reads={})]

    async def notes(self, results: Sequence[ResultOut]) -> dict[str, FailureNote]:
        self.noted.append([r.name for r in results])
        return {
            r.name: FailureNote(
                scenario=r.name, block="Read new releases", kind="stopped", source=None, detail=None
            )
            for r in results
            if r.verdict == "failed"
        }


class FakeLog:
    def __init__(self) -> None:
        self.noted: list[tuple[RunId, FixData]] = []
        self.refuse: FixRefused | None = None

    async def note_fix(self, run_id: RunId, data: FixData) -> FixRefused | None:
        self.noted.append((run_id, data))
        return self.refuse


class FakeFacts:
    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions:
        return KNOWN


class FakeN8n:
    async def error_workflow_id(self) -> str | None:
        return ERROR_WORKFLOW


class Parts:
    def __init__(self, model: bool = False) -> None:
        self.gateway = FakeGateway()
        self.model = FakeModel() if model else None
        self.log = FakeLog()
        layouts = FixLayouts(FakeFacts(), FakeN8n(), "https://portal.example", ZONE)
        self.parts = FixParts(layouts, self.gateway, self.model, self.log)


def plan() -> WorkflowPlan:
    return release_check()


def asked_scenarios(**changes: Any) -> FixScenariosIn:
    given = {"version": plan().model_dump(mode="json"), "within_seconds": 60} | changes
    return FixScenariosIn.model_validate(given)


def asked_simulation(**changes: Any) -> FixSimulationIn:
    given = {
        "version": plan().model_dump(mode="json"),
        "scenarios": [{"kind": "happy_path", "name": "happy_path"}],
        "within_seconds": 60,
    } | changes
    return FixSimulationIn.model_validate(given)


# The token


def test_a_token_opens_one_fix_on_one_run_until_a_few_minutes_after_its_deadline() -> None:
    token = fix_token(KEY, RUN, FIX, ENDS_BY)
    assert fix_token_ok(KEY, RUN, FIX, token, ENDS_BY)
    assert fix_token_ok(KEY, RUN, FIX, token, ENDS_BY + FIX_TOKEN_GRACE - timedelta(seconds=1))
    assert not fix_token_ok(KEY, RUN, FIX, token, ENDS_BY + FIX_TOKEN_GRACE)
    assert not fix_token_ok(KEY, RunId("run_01OTHER"), FIX, token, ENDS_BY)
    assert not fix_token_ok(KEY, RUN, "fix_01OTHER", token, ENDS_BY)
    assert not fix_token_ok(secrets.token_hex(32), RUN, FIX, token, ENDS_BY)
    assert not fix_token_ok(KEY, RUN, FIX, "not.a-token", ENDS_BY)


# Scenarios


@pytest.mark.anyio
async def test_without_the_model_code_s_template_runs_for_each_kind_that_applies() -> None:
    parts = Parts(model=False)
    written = await parts.parts.scenarios(FIX, asked_scenarios(may_ask_model=True))
    assert not isinstance(written, NotSimulated)
    assert [(s.kind, s.name, s.reads, s.agents) for s in written.scenarios] == [
        (kind, kind, {}, {}) for kind in KINDS
    ]
    assert written.asked_model is False


@pytest.mark.anyio
async def test_the_model_writes_only_when_turned_on_and_the_fix_can_pay_for_it() -> None:
    parts = Parts(model=True)
    kept = await parts.parts.scenarios(FIX, asked_scenarios(may_ask_model=False))
    assert not isinstance(kept, NotSimulated)
    assert (len(kept.scenarios), kept.asked_model) == (len(KINDS), False)
    assert parts.model is not None and parts.model.wrote == []
    written = await parts.parts.scenarios(FIX, asked_scenarios(may_ask_model=True))
    assert not isinstance(written, NotSimulated)
    assert ([s.name for s in written.scenarios], written.asked_model) == (["happy_path"], True)


@pytest.mark.anyio
async def test_the_stopped_version_is_laid_out_before_the_gateway_reads_it() -> None:
    parts = Parts()
    await parts.parts.scenarios(FIX, asked_scenarios())
    [version] = parts.gateway.planned
    assert set(version) == {"name", "nodes", "connections", "settings"}
    names = {node["name"] for node in version["nodes"]}
    assert {"Start from the Portal", "Read new releases", "Ask for a yes"} <= names


@pytest.mark.anyio
async def test_an_ask_to_cover_blocks_finds_nothing_new_yet() -> None:
    parts = Parts(model=True)
    covered = await parts.parts.scenarios(FIX, asked_scenarios(cover=["Make the ticket"]))
    assert not isinstance(covered, NotSimulated)
    assert (covered.scenarios, covered.asked_model) == ([], False)
    assert parts.gateway.planned == []


@pytest.mark.anyio
async def test_a_gateway_that_does_not_answer_gives_no_scenarios() -> None:
    parts = Parts()
    parts.gateway.plan_answer = NotSimulated(DIDNT_ANSWER, again=True)
    assert await parts.parts.scenarios(FIX, asked_scenarios()) == NotSimulated(
        DIDNT_ANSWER, again=True
    )


# A simulation


@pytest.mark.anyio
async def test_a_simulation_runs_the_scenarios_as_given_and_says_what_each_run_reached() -> None:
    parts = Parts()
    parts.gateway.answer = simulation_out(
        result("happy_path"),
        result(
            "replay_the_stop",
            "failed",
            ending="stopped",
            stopped_at="Read new releases",
            reached=["read:github_releases", "read:confluence_page"],
        ),
        result("timeout", "not_tried", ending=None, reached=[]),
    )
    done = await parts.parts.simulate(FIX, asked_simulation(may_ask_model=True))
    assert not isinstance(done, NotSimulated)
    [(_, scenarios, fall_back)] = parts.gateway.simulated
    assert (scenarios, fall_back) == ([ScenarioSpec(kind="happy_path", name="happy_path")], False)
    assert [r.model_dump() for r in done.results] == [
        {
            "name": "happy_path",
            "verdict": "passed",
            "step": None,
            "why": None,
            "reached": ["read:github_releases"],
            "note": None,
        },
        {
            "name": "replay_the_stop",
            "verdict": "failed",
            "step": "Read new releases",
            "why": "stopped",
            "reached": ["read:github_releases", "read:confluence_page"],
            "note": None,
        },
        {
            "name": "timeout",
            "verdict": "not_tried",
            "step": None,
            "why": None,
            "reached": [],
            "note": None,
        },
    ]
    assert (done.not_reached, done.named) == (
        ["Tell"],
        ["propose:jira.create_ticket", "read:github_releases"],
    )
    assert done.asked_model is False, "without the model nothing is explained"


@pytest.mark.anyio
async def test_the_model_explains_failures_in_picks_only_when_on_and_paid_for() -> None:
    parts = Parts(model=True)
    parts.gateway.answer = simulation_out(
        result("happy_path"), result("replay_the_stop", "failed", stopped_at="Read new releases")
    )
    unpaid = await parts.parts.simulate(FIX, asked_simulation(may_ask_model=False))
    assert not isinstance(unpaid, NotSimulated)
    assert [r.note for r in unpaid.results] == [None, None]
    paid = await parts.parts.simulate(FIX, asked_simulation(may_ask_model=True))
    assert not isinstance(paid, NotSimulated)
    assert paid.asked_model is True
    note = paid.results[1].note
    assert note is not None
    assert note.model_dump() == {"block": "Read new releases", "kind": "stopped", "source": None}


@pytest.mark.anyio
async def test_a_simulation_with_nothing_failed_asks_no_model() -> None:
    parts = Parts(model=True)
    done = await parts.parts.simulate(FIX, asked_simulation(may_ask_model=True))
    assert not isinstance(done, NotSimulated)
    assert done.asked_model is False
    assert parts.model is not None and parts.model.noted == []


@pytest.mark.anyio
async def test_a_simulation_that_does_not_answer_in_time_gives_no_answer() -> None:
    parts = Parts()
    parts.gateway.answer = NotSimulated(DIDNT_ANSWER, again=True)
    assert await parts.parts.simulate(FIX, asked_simulation()) == NotSimulated(
        DIDNT_ANSWER, again=True
    )


# The checker


@pytest.mark.anyio
async def test_the_checker_grades_the_plan_as_it_grades_any_layout() -> None:
    parts = Parts()
    assert (await parts.parts.check(FIX, plan())).model_dump() == {"passes": True, "findings": []}


@pytest.mark.anyio
async def test_the_checker_fails_a_plan_that_isn_t_safe_and_names_the_rules() -> None:
    parts = Parts()
    given = plan().model_dump(mode="json")
    given["blocks"].append(
        {
            "name": "Call out",
            "type": "n8n-nodes-base.httpRequest",
            "version": 4.2,
            "parameters": {"url": "https://example.com"},
        }
    )
    given["wires"].append(
        {
            "from_block": "Read new releases",
            "exit": "main",
            "to_block": "Call out",
            "exit_index": 0,
            "input_index": 0,
        }
    )
    checked = await parts.parts.check(FIX, WorkflowPlan.model_validate(given))
    assert checked.passes is False
    assert checked.findings


# The routes


def client(parts: Parts) -> TestClient:
    app = FastAPI()
    app.include_router(fix_http.router)
    app.state.fix_parts = parts.parts
    app.state.settings = SimpleNamespace(callback_signing_key=KEY)
    return TestClient(app)


def base(run: str = RUN, fix: str = FIX) -> str:
    return f"/internal/v1/runs/{run}/fixes/{fix}"


def headers(token: str | None = None) -> dict[str, str]:
    now = datetime.now(UTC) + timedelta(minutes=10)
    return {FIX_TOKEN_HEADER: token or fix_token(KEY, RUN, FIX, now)}


def test_every_route_needs_the_fix_s_own_token() -> None:
    parts = Parts()
    with client(parts) as http:
        other = fix_token(KEY, RUN, "fix_01OTHER", datetime.now(UTC) + timedelta(minutes=10))
        for path, body in [
            ("/events", {"kind": "fix_handed_back", "data": {"fix_id": FIX, "why": "gave_up"}}),
            ("/scenarios", asked_scenarios().model_dump(mode="json")),
            ("/simulations", asked_simulation().model_dump(mode="json")),
            ("/checks", {"version": plan().model_dump(mode="json")}),
        ]:
            assert http.post(base() + path, json=body).status_code == 422
            assert http.post(base() + path, json=body, headers=headers(other)).status_code == 401
    assert parts.log.noted == []
    assert parts.gateway.planned == parts.gateway.simulated == []


def test_an_event_is_written_on_the_stopped_run_and_the_log_s_refusal_comes_back() -> None:
    parts = Parts()
    event = {"kind": "fix_handed_back", "data": {"fix_id": FIX, "why": "no_progress"}}
    with client(parts) as http:
        assert http.post(base() + "/events", json=event, headers=headers()).json() == {
            "refused": None
        }
        parts.log.refuse = FixRefused("ended")
        assert http.post(base() + "/events", json=event, headers=headers()).json() == {
            "refused": "ended"
        }
    assert parts.log.noted[0] == (RUN, FixHandedBackData(fix_id=FIX, why="no_progress"))


def test_an_event_of_another_fix_or_of_no_known_kind_is_refused() -> None:
    parts = Parts()
    with client(parts) as http:
        other = {"kind": "fix_handed_back", "data": {"fix_id": "fix_01OTHER", "why": "gave_up"}}
        assert http.post(base() + "/events", json=other, headers=headers()).status_code == 422
        unknown = {"kind": "fix_approved", "data": {"fix_id": FIX}}
        assert http.post(base() + "/events", json=unknown, headers=headers()).status_code == 422
    assert parts.log.noted == []


def test_the_simulation_route_answers_503_when_the_practice_systems_don_t_answer() -> None:
    parts = Parts()
    parts.gateway.answer = NotSimulated(DIDNT_ANSWER, again=True)
    with client(parts) as http:
        answer = http.post(
            base() + "/simulations",
            json=asked_simulation().model_dump(mode="json"),
            headers=headers(),
        )
    assert (answer.status_code, answer.json()) == (503, {"detail": DIDNT_ANSWER})


def test_the_routes_answer_scenarios_a_simulation_and_a_grade() -> None:
    parts = Parts()
    with client(parts) as http:
        written = http.post(
            base() + "/scenarios", json=asked_scenarios().model_dump(mode="json"), headers=headers()
        )
        assert [s["name"] for s in written.json()["scenarios"]] == KINDS
        ran = http.post(
            base() + "/simulations",
            json=asked_simulation().model_dump(mode="json"),
            headers=headers(),
        )
        assert [r["verdict"] for r in ran.json()["results"]] == ["passed"]
        graded = http.post(
            base() + "/checks", json={"version": plan().model_dump(mode="json")}, headers=headers()
        )
        assert graded.json() == {"passes": True, "findings": []}
