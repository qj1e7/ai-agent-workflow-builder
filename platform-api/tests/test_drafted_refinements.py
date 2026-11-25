"""Refining a drafted workflow's Check (ADR 0054, section 7, PR 8), in platform-api with the agent
runtime faked. Once the newest revision's simulation failed a case, or no case reached a block,
an Operator may ask to refine it, only where Simulation mode's model is on and a model is
connected. platform-api keeps the refinement and mints its token, and the coordinator reaches
this refinement's own routes. A refined plan is kept as the next revision only once a simulation
here passed every case, with no setting changed and the change inside the blocks where a case
failed, and it goes through the normal Check. The card says honestly how it stands: offered,
refining, refined, unchanged, or given up with why."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from platform_api.builder.fix_parts import (
    FIX_TOKEN_HEADER,
    fix_token,
    refine_token,
    refine_token_ok,
)
from platform_api.builder.fixes import NotStored
from platform_api.builder.refinements import (
    NOTHING_TO_REFINE,
    OUTSIDE,
    REFINING,
    SETTING,
    TRIED,
    UNCHANGED_SAID,
    UNPROVEN,
    WHY_SAID,
    Refinements,
    RefineSettings,
    refined_said,
)
from platform_api.db import Database
from platform_api.monitoring import FixHandedBackData, FixProposedData, FixRoundData
from platform_api.orchestration import (
    AgentRejected,
    AgentUnavailable,
    CauseFound,
    FixAccepted,
    ModelAccess,
    RefineStartRequest,
    WorkflowPlan,
)
from platform_api.orchestration.simulation_driver import Simulated
from platform_api.orchestration.simulation_gateway import (
    CoverageOut,
    ResultOut,
    SimulationOut,
)
from tests.conftest import PostgresUrls
from tests.support import LOCAL_ENV
from tests.test_drafted_simulations import Bench, Driver, bench_of, case

pytestmark = pytest.mark.anyio

KEY = LOCAL_ENV["CALLBACK_SIGNING_KEY"]
PROPOSE = "Propose a ticket"
TITLE = "={{ 'New release ' + $json.release.tag }}"


def failing(stopped_at: str = PROPOSE, not_reached: tuple[str, ...] = ()) -> Simulated:
    """The Check's simulation: odd data stops the run at the ticket, every other case passes."""
    odd = case("odd_data", "failed", "It stopped.").model_copy(
        update={"stopped_at": stopped_at, "ending": "stopped"}
    )
    cases = [case("happy_path", "passed"), odd]
    return Simulated(
        SimulationOut(
            tried=2,
            passed=1,
            results=cases,
            coverage=CoverageOut(
                not_reached=list(not_reached), not_tried=[], kinds_without_a_scenario=[]
            ),
            blocks=[],
            scenarios_from="given",
            refused=[],
        )
    )


def passing(not_reached: tuple[str, ...] = ()) -> Simulated:
    done = failing(not_reached=not_reached)
    results: list[ResultOut] = [case("happy_path", "passed"), case("odd_data", "passed")]
    return Simulated(done.out.model_copy(update={"results": results, "passed": 2}))


@dataclass
class Runtime:
    """The agent runtime's POST /v1/refinements."""

    started: list[RefineStartRequest] = field(default_factory=list[RefineStartRequest])
    answer: FixAccepted | AgentUnavailable | AgentRejected | None = None

    async def start_refinement(
        self, request: RefineStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected:
        self.started.append(request)
        return self.answer or FixAccepted(fix_id=request.request.fix_id, started=True)


@dataclass
class Models:
    connected: bool = True

    async def access(self) -> ModelAccess | None:
        if not self.connected:
            return None
        return ModelAccess.model_validate(
            {
                "style": "anthropic",
                "base_url": "https://model.example",
                "model": "m",
                "api_key": "x" * 8,
            }
        )


@dataclass
class Lab:
    bench: Bench
    refinements: Refinements
    runtime: Runtime
    models: Models

    async def checked(self, user: str = "alice") -> dict[str, Any]:
        """A drafted release check with nothing still needed, its Check tried and settled."""
        first = await self.bench.start(user)
        await self.bench.drafted.settle()
        return await self.bench.read(first["drafted_id"], user)

    async def refine(self, view: Mapping[str, Any], user: str = "alice") -> httpx.Response:
        path = f"/api/v1/drafted-workflows/{view['drafted_id']}/refinements"
        return await self.bench.call(user, "POST", path, {"revision": view["revision"]})

    async def plan(self, view: Mapping[str, Any]) -> WorkflowPlan:
        got = await self.bench.drafted.revision_plan(view["drafted_id"], view["revision"])
        assert got is not None
        return got[0]

    async def simulated(self, fix_id: str, plan: WorkflowPlan, **grades: str) -> None:
        """A simulation platform-api ran for the refinement, as its route keeps it."""
        results = {
            name: {
                "kind": name,
                "verdict": verdict.partition(":")[0],
                "step": verdict.partition(":")[2] or None,
            }
            for name, verdict in grades.items()
        }
        await self.refinements.simulated_on(fix_id, plan, results)


async def lab_of(
    db: Database, answers: list[Simulated], on: bool = True, connected: bool = True
) -> AsyncIterator[Lab]:
    async for bench in bench_of(db, Driver(answers=list(answers))):
        runtime, models = Runtime(), Models(connected)
        refinements = Refinements(
            db,
            bench.drafted,
            bench.simulations,
            runtime,
            models,
            RefineSettings(on=on, signing_key=KEY, platform_url="http://platform-api:8000"),
        )
        bench.drafted.serve_refinements(refinements)
        transport = bench.client._transport  # pyright: ignore[reportPrivateUsage]
        app = transport.app  # type: ignore[attr-defined]
        app.state.refinements = refinements
        yield Lab(bench, refinements, runtime, models)


@pytest.fixture
async def lab(postgres: PostgresUrls, db: Database) -> AsyncIterator[Lab]:
    async for made in lab_of(db, [failing()]):
        yield made


def refined(plan: WorkflowPlan) -> WorkflowPlan:
    """The draft with only the ticket's title changed."""
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "title": TITLE}})
        if b.name == PROPOSE
        else b
        for b in plan.blocks
    ]
    return plan.model_copy(update={"blocks": blocks})


CAUSE = CauseFound(failed_part=[PROPOSE], system=None, failure_kind="unknown", detail=None)


# The offer


async def test_an_operator_is_offered_a_refinement_once_a_case_failed(lab: Lab):
    view = await lab.checked()
    assert view["simulation"]["state"] == "done"
    offer = view["refinement"]
    assert offer["state"] == "offered" and offer["can_start"] is True
    assert offer["said"].startswith("A case failed on practice systems.")
    assert (await lab.bench.read(view["drafted_id"], "bob"))["refinement"] is None


async def test_a_block_no_case_reached_is_offered_too(postgres: PostgresUrls, db: Database):
    async for lab in lab_of(db, [passing(not_reached=(PROPOSE,))]):
        offer = (await lab.checked())["refinement"]
        assert offer["state"] == "offered"
        assert offer["said"].startswith("No case reached every block.")


@pytest.mark.parametrize(("on", "connected"), [(False, True), (True, False)])
async def test_nothing_is_offered_unless_the_model_is_on_and_connected(
    postgres: PostgresUrls, db: Database, on: bool, connected: bool
):
    async for lab in lab_of(db, [failing()], on=on, connected=connected):
        view = await lab.checked()
        assert view["simulation"]["state"] == "done"
        assert view["refinement"] is None
        answer = await lab.refine(view)
        assert answer.status_code == 409
        assert lab.runtime.started == []


async def test_nothing_is_offered_when_every_case_passed_and_reached_every_block(
    postgres: PostgresUrls, db: Database
):
    async for lab in lab_of(db, [passing()]):
        view = await lab.checked()
        assert view["refinement"] is None
        answer = await lab.refine(view)
        assert (answer.status_code, answer.json()["detail"]) == (409, NOTHING_TO_REFINE)


# The start


async def test_the_start_sends_the_draft_its_failed_cases_and_a_refinement_s_own_token(lab: Lab):
    view = await lab.checked()
    answer = await lab.refine(view)
    assert answer.status_code == 200, answer.text
    assert answer.json()["refinement"]["state"] == "refining"
    [started] = lab.runtime.started
    asked = started.request
    assert started.drafted_id == view["drafted_id"]
    assert asked.version == await lab.plan(view)
    assert [(c.kind, c.step) for c in asked.failed] == [("odd_data", PROPOSE)]
    assert asked.ends_by - datetime.now(UTC) <= timedelta(minutes=20)
    now = datetime.now(UTC)
    assert refine_token_ok(KEY, view["drafted_id"], asked.fix_id, started.token, now)
    assert started.token != fix_token(KEY, view["drafted_id"], asked.fix_id, asked.ends_by)


async def test_one_refinement_at_a_time_and_once_for_each_revision(lab: Lab):
    view = await lab.checked()
    assert (await lab.refine(view)).status_code == 200
    again = await lab.refine(view)
    assert (again.status_code, again.json()["detail"]) == (409, REFINING)
    fix_id = lab.runtime.started[0].request.fix_id
    gone = FixHandedBackData(fix_id=fix_id, why="no_progress")
    assert await lab.refinements.note(view["drafted_id"], fix_id, gone) is None
    after = await lab.refine(view)
    assert (after.status_code, after.json()["detail"]) == (409, TRIED)


async def test_only_an_operator_starts_a_refinement(lab: Lab):
    view = await lab.checked()
    assert (await lab.refine(view, "bob")).status_code == 403
    assert lab.runtime.started == []


async def test_a_runtime_that_does_not_take_it_gives_up_at_once(lab: Lab):
    lab.runtime.answer = AgentUnavailable("down")
    view = await lab.checked()
    shown = (await lab.refine(view)).json()["refinement"]
    assert shown["state"] == "gave_up"
    assert shown["said"] == "I couldn't refine it. Nothing it tried passed every case."


# The refined draft


async def test_a_refined_plan_a_simulation_here_passed_is_the_next_revision(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    fix_id = lab.runtime.started[0].request.fix_id
    original = await lab.plan(view)
    better = refined(original)
    await lab.simulated(fix_id, original, happy_path="passed", odd_data=f"failed:{PROPOSE}")
    await lab.simulated(fix_id, better, happy_path="passed", odd_data="passed")
    kept = await lab.refinements.store(view["drafted_id"], fix_id, better, CAUSE)
    assert kept.version == view["revision"] + 1 and kept.digest.startswith("sha256:")
    assert await lab.refinements.store(view["drafted_id"], fix_id, better, CAUSE) == kept
    round_one = FixRoundData(fix_id=fix_id, round=1, passed=2, scenarios=2, progress=True)
    assert await lab.refinements.note(view["drafted_id"], fix_id, round_one) is None
    proposal = FixProposedData(fix_id=fix_id, version=kept.version, digest=kept.digest)
    assert await lab.refinements.note(view["drafted_id"], fix_id, proposal) is None
    await lab.bench.drafted.settle()

    after = await lab.bench.read(view["drafted_id"], "alice")
    assert (after["revision"], after["made_by"]) == (kept.version, "refined")
    assert after["card_revision"] == view["card_revision"]
    assert after["state"] == "draft" and after["approval"] is None
    assert after["simulation"]["state"] == "done", "it goes through the normal Check"
    shown = after["refinement"]
    assert (shown["state"], shown["revision"]) == ("refined", kept.version)
    assert shown["said"] == refined_said(1)
    assert shown["rounds"] == [{"round": 1, "passed": 2, "scenarios": 2}]
    assert len(lab.bench.driver.versions) == 2


async def test_a_plan_no_simulation_here_passed_is_not_kept(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    fix_id = lab.runtime.started[0].request.fix_id
    better = refined(await lab.plan(view))
    await lab.simulated(fix_id, better, happy_path="passed", odd_data=f"failed:{PROPOSE}")
    with pytest.raises(NotStored, match=UNPROVEN):
        await lab.refinements.store(view["drafted_id"], fix_id, better, CAUSE)


async def test_a_refinement_never_changes_a_setting_or_a_block_where_nothing_failed(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    fix_id = lab.runtime.started[0].request.fix_id
    original = await lab.plan(view)
    await lab.simulated(fix_id, original, happy_path="passed", odd_data=f"failed:{PROPOSE}")
    moved = original.model_copy(
        update={
            "settings": [
                s.model_copy(update={"value": "MOCK2"}) if s.id == "jira_project" else s
                for s in original.settings
            ]
        }
    )
    elsewhere = original.model_copy(
        update={
            "blocks": [
                b.model_copy(update={"parameters": {**b.parameters, "source": "confluence_page"}})
                if b.name == "Read new releases"
                else b
                for b in original.blocks
            ]
        }
    )
    read = CauseFound(
        failed_part=["Read new releases"], system=None, failure_kind="unknown", detail=None
    )
    for plan in (moved, elsewhere):
        await lab.simulated(fix_id, plan, happy_path="passed", odd_data="passed")
    with pytest.raises(NotStored, match=SETTING):
        await lab.refinements.store(view["drafted_id"], fix_id, moved, CAUSE)
    with pytest.raises(NotStored, match=OUTSIDE):
        await lab.refinements.store(view["drafted_id"], fix_id, elsewhere, CAUSE)
    with pytest.raises(NotStored, match=OUTSIDE):
        await lab.refinements.store(view["drafted_id"], fix_id, elsewhere, read)


async def test_a_draft_every_case_passed_comes_back_unchanged(postgres: PostgresUrls, db: Database):
    async for lab in lab_of(db, [passing(not_reached=(PROPOSE,))]):
        view = await lab.checked()
        await lab.refine(view)
        fix_id = lab.runtime.started[0].request.fix_id
        original = await lab.plan(view)
        await lab.simulated(fix_id, original, happy_path="passed", reach_abc="passed")
        kept = await lab.refinements.store(view["drafted_id"], fix_id, original, None)
        assert kept.version == view["revision"]
        proposal = FixProposedData(fix_id=fix_id, version=kept.version, digest=kept.digest)
        assert await lab.refinements.note(view["drafted_id"], fix_id, proposal) is None
        after = await lab.bench.read(view["drafted_id"], "alice")
        assert after["revision"] == view["revision"]
        assert (after["refinement"]["state"], after["refinement"]["said"]) == (
            "unchanged",
            UNCHANGED_SAID,
        )


# Its events


async def test_its_events_keep_a_fix_s_rules_by_the_drafted_workflow(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    drafted_id, fix_id = view["drafted_id"], lab.runtime.started[0].request.fix_id
    one = FixRoundData(fix_id=fix_id, round=1, passed=1, scenarios=2, progress=True)
    assert await lab.refinements.note(drafted_id, fix_id, one) is None
    assert await lab.refinements.note(drafted_id, fix_id, one) is None
    other = one.model_copy(update={"passed": 2})
    assert await lab.refinements.note(drafted_id, fix_id, other) == "conflict"
    assert await lab.refinements.note("dw_01OTHER", fix_id, one) == "not_started"
    wrong = FixProposedData(fix_id=fix_id, version=99, digest="sha256:" + "0" * 64)
    with pytest.raises(NotStored):
        await lab.refinements.note(drafted_id, fix_id, wrong)
    gone = FixHandedBackData(fix_id=fix_id, why="widened")
    assert await lab.refinements.note(drafted_id, fix_id, gone) is None
    two = FixRoundData(fix_id=fix_id, round=2, passed=2, scenarios=2, progress=True)
    assert await lab.refinements.note(drafted_id, fix_id, two) == "ended"
    shown = (await lab.bench.read(drafted_id, "alice"))["refinement"]
    assert shown["state"] == "gave_up"
    assert shown["said"] == f"I couldn't refine it. {WHY_SAID['widened']}"
    assert shown["rounds"] == [{"round": 1, "passed": 1, "scenarios": 2}]


async def test_past_its_deadline_only_the_hand_back_for_time_is_kept(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    drafted_id, fix_id = view["drafted_id"], lab.runtime.started[0].request.fix_id
    async with lab.bench.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.drafted_refinements SET ends_by = %s WHERE fix_id = %s",
            (uow.now - timedelta(minutes=1), fix_id),
        )
    one = FixRoundData(fix_id=fix_id, round=1, passed=1, scenarios=2, progress=True)
    assert await lab.refinements.note(drafted_id, fix_id, one) == "ended"
    for_time = FixHandedBackData(fix_id=fix_id, why="time_limit")
    assert await lab.refinements.note(drafted_id, fix_id, for_time) is None
    shown = (await lab.bench.read(drafted_id, "alice"))["refinement"]
    assert shown["said"] == f"I couldn't refine it. {WHY_SAID['time_limit']}"


# Its routes


async def test_its_routes_need_its_own_token_and_never_a_fix_s(lab: Lab):
    view = await lab.checked()
    await lab.refine(view)
    started = lab.runtime.started[0]
    fix_id, drafted_id = started.request.fix_id, view["drafted_id"]
    path = f"/internal/v1/drafted/{drafted_id}/refinements/{fix_id}/events"
    event = {
        "kind": "fix_round",
        "data": {"fix_id": fix_id, "round": 1, "passed": 1, "scenarios": 2, "progress": True},
    }
    client = lab.bench.client
    assert (await client.post(path, json=event)).status_code == 401
    a_fix_s = fix_token(KEY, drafted_id, fix_id, started.request.ends_by)
    assert (
        await client.post(path, json=event, headers={FIX_TOKEN_HEADER: a_fix_s})
    ).status_code == 401
    other = refine_token(KEY, "dw_01OTHER", fix_id, started.request.ends_by)
    assert (
        await client.post(path, json=event, headers={FIX_TOKEN_HEADER: other})
    ).status_code == 401
    ok = await client.post(path, json=event, headers={FIX_TOKEN_HEADER: started.token})
    assert (ok.status_code, ok.json()) == (200, {"refused": None})
