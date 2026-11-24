"""The simulation and the checker joined to the coordinator (ADR 0055, PR 5), on the eval's fakes
and recorded replies, so no model is called.

Before a draft's first simulation, code adds its own scenario that replays the stop, built from
the stopped run's own facts, and tries every scenario on the stopped version first. The replay
must fail there, or no fix can be proven. Each run says what it reached, and a draft that reaches
anything the stopped version neither names nor reached widens the change. Each port is told the
seconds and the dollars left, and what a port charges counts toward the fix's cost. A proposal the
log never takes ends the fix as stopped, with the revision code stored."""

import importlib.resources
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from agent_runtime.fixing.replay import REPLAY, replay_of
from evals.fix import (
    FIX,
    FIX_ID,
    STARTED,
    Clock,
    FakeLog,
    Fakes,
    FakeScenarioWriter,
    FixCase,
    RecordedChat,
    request_of,
    run_case,
)
from evals.runner import PRICING

from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.fixing.coordinator import (
    MOST_DOLLARS,
    HandedBack,
    HandedIn,
    Stopped,
    coordinating,
)
from agent_runtime.fixing.cost import charge
from agent_runtime.fixing.events import FixData, FixHandoffData, FixProposedData, FixRefusal
from agent_runtime.fixing.ports import Scenario, StoredRevision
from agent_runtime.model_cost import PRICES, packaged_prices

CASES = {case.id: case for case in FIX.cases()}
READ = "Read new releases"
RENAMED = "fixable-renamed-repository"


def case(id_: str, **changes: Any) -> FixCase:
    return FixCase.model_validate({**CASES[id_].model_dump(), **changes})


def fixed(base: FixCase, fakes: Fakes, clock: Clock) -> Any:
    chat = RecordedChat(turns=list(base.replies), clock=clock)
    return coordinating(request_of(base), lambda _t: chat, fakes.parts(), packaged_prices(), clock)


def cause(kind: str = "not_found", detail: str | None = "langchain-ai/langgraph") -> CauseFound:
    return CauseFound.model_validate(
        {"failed_part": [READ], "system": None, "failure_kind": kind, "detail": detail}
    )


# The replay of the stop


def test_a_stop_at_a_source_not_found_replays_as_that_place_gone():
    version = request_of(CASES[RENAMED]).version
    replay = replay_of(version, [READ], cause())
    assert replay == Scenario(
        name=REPLAY,
        kind="happy_path",
        reads={READ: {"serve": "recorded", "gone": ["langchain-ai/langgraph"]}},
    )


def test_with_no_name_from_the_stop_the_replay_takes_the_place_the_block_reads():
    version = request_of(CASES[RENAMED]).version
    assert replay_of(version, [READ], cause(detail=None)).reads == {
        READ: {"serve": "recorded", "gone": ["langchain-ai/langgraph"]}
    }


def test_n8n_s_github_block_replays_its_owner_and_repository():
    version = WorkflowPlan.model_validate(
        {
            "name": "Release check",
            "blocks": [
                {
                    "name": "GitHub releases",
                    "type": "n8n-nodes-base.github",
                    "version": 1.1,
                    "parameters": {"owner": "langchain-ai", "repository": "langgraph"},
                }
            ],
            "wires": [],
            "settings": [],
        }
    )
    found = cause(detail=None).model_copy(update={"failed_part": ["GitHub releases"]})
    assert replay_of(version, ["GitHub releases"], found).reads == {
        "GitHub releases": {"serve": "recorded", "gone": ["langchain-ai/langgraph"]}
    }


def test_any_other_stop_replays_as_the_happy_path_with_the_stopped_run_s_samples():
    version = request_of(CASES[RENAMED]).version
    for kind in ("changed_field", "wrong_value", "unknown"):
        assert replay_of(version, [READ], cause(kind, None)) == Scenario(
            name=REPLAY, kind="happy_path"
        )


def test_a_place_an_expression_picks_is_never_guessed():
    version = request_of(CASES[RENAMED]).version
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "place": "={{ $json.repo }}"}})
        if b.name == READ
        else b
        for b in version.blocks
    ]
    picked = version.model_copy(update={"blocks": blocks})
    assert replay_of(picked, [READ], cause(detail=None)).reads == {}


# The first simulation


def test_the_first_simulation_adds_the_replay_and_tries_the_stopped_version_first():
    run = run_case(CASES[RENAMED])
    ledger, simulation = run.fixing.ledger, run.fakes.simulation
    assert REPLAY in ledger.scenarios
    assert ledger.scenarios[REPLAY].reads == {
        READ: {"serve": "recorded", "gone": ["langchain-ai/langgraph"]}
    }
    stopped = request_of(CASES[RENAMED]).version
    assert simulation.versions[0] == stopped
    assert simulation.versions[1] != stopped
    assert simulation.dollars[0] == 0.0, "the stopped version is tried without the model"
    assert ledger.baseline[REPLAY].verdict == "failed"
    assert isinstance(run.fixing.outcome, HandedIn)


def test_the_stopped_version_is_tried_once_for_each_scenario():
    run = run_case(CASES["fixable-jira-key-in-a-second-round"])
    stopped = request_of(CASES["fixable-jira-key-in-a-second-round"]).version
    assert run.fakes.simulation.versions.count(stopped) == 1
    assert isinstance(run.fixing.outcome, HandedIn)


def test_a_written_scenario_can_t_take_the_replay_s_name():
    base = CASES[RENAMED]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)

    class Squats(FakeScenarioWriter):
        def write(
            self,
            version: WorkflowPlan,
            cover: Sequence[str],
            seconds: float,
            dollars_left: Callable[[], float],
        ) -> list[Scenario] | None:
            return [Scenario(name=REPLAY, kind="happy_path")]

    fakes.scenario_writer = Squats(fakes.scenario_writer.script, fakes.played)
    fixing = fixed(base, fakes, clock)
    [writer] = [
        e for e in fakes.log.events if isinstance(e, FixHandoffData) and e.to == "scenario_writer"
    ]
    assert writer.found == "refused"
    assert fixing.ledger.scenarios == {}, "the whole set is refused"
    assert not isinstance(fixing.outcome, HandedIn)


def test_a_replay_the_stopped_version_passes_proves_nothing_so_the_fix_is_handed_back():
    run = run_case(case(RENAMED, baseline={REPLAY: "passed"}))
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "not_replayed"
    assert run.fakes.revisions.stored == []


def test_hand_in_needs_the_replay_to_have_failed_on_the_stopped_version():
    run = run_case(CASES[RENAMED])
    ledger = run.fixing.ledger
    assert ledger.done_needs() == []
    ledger.baseline.pop(REPLAY)
    assert "a replay of the stop that fails on the stopped version" in ledger.done_needs()


# What each run reached


def test_a_draft_that_reaches_a_system_the_stopped_version_never_did_widens_the_fix():
    run = run_case(
        case(
            RENAMED,
            baseline_reached=["read:github_releases"],
            reached=[{"New release": ["read:github_releases", "read:confluence_page"]}],
        )
    )
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "widened"
    [tried] = outcome.rounds
    assert (tried.found, tried.widened_by) == ("widened", "adds_a_system")
    assert run.fakes.revisions.stored == []


def test_a_system_the_stopped_version_names_is_no_widening():
    run = run_case(
        case(
            RENAMED,
            named=["read:github_releases", "propose:jira.create_ticket"],
            reached=[{"New release": ["read:github_releases", "propose:jira.create_ticket"]}],
        )
    )
    assert isinstance(run.fixing.outcome, HandedIn)


# Seconds and dollars


def test_the_writer_the_simulation_and_the_checker_are_told_the_dollars_left():
    run = run_case(CASES[RENAMED])
    fakes = run.fakes
    for told in (
        fakes.scenario_writer.dollars,
        fakes.simulation.dollars[1:],
        fakes.checker.dollars,
    ):
        assert told and all(0 < dollars <= MOST_DOLLARS for dollars in told)
    assert all(0 < s < 1200 for s in fakes.simulation.script.given)
    assert all(0 < s < 1200 for s in fakes.checker.script.given)


def test_what_a_port_charges_counts_toward_the_fix_s_cost():
    base = CASES[RENAMED]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)

    class Dear(FakeScenarioWriter):
        def write(
            self,
            version: WorkflowPlan,
            cover: Sequence[str],
            seconds: float,
            dollars_left: Callable[[], float],
        ) -> list[Scenario] | None:
            charge(MOST_DOLLARS)
            return super().write(version, cover, seconds, dollars_left)

    fakes.scenario_writer = Dear(fakes.scenario_writer.script, fakes.played)
    fixing = fixed(base, fakes, clock)
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "cost_limit"


def test_the_price_table_ships_in_the_runtime_package_and_the_evals_read_it_too():
    packaged = importlib.resources.files("agent_runtime").joinpath("pricing.json")
    assert packaged.is_file()
    assert PRICING == PRICES
    assert "claude-sonnet-5-5" in packaged_prices()


def test_the_coordinator_counts_cost_at_the_packaged_prices_when_given_none():
    base = CASES[RENAMED]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    chat = RecordedChat(turns=list(base.replies), clock=clock)
    fixing = coordinating(request_of(base), lambda _t: chat, fakes.parts(), now=clock)
    assert fixing.cost.dollars > 0 and not fixing.cost.unpriced


# The end events


class Loses(FakeLog):
    """A log that can't be reached for a proposal, however often it is tried."""

    def note(self, data: FixData) -> FixRefusal | None:
        if isinstance(data, FixProposedData):
            raise httpx.ConnectError("the log is down")
        return super().note(data)


def test_a_proposal_the_log_never_takes_stops_the_fix_with_its_stored_version():
    base = CASES[RENAMED]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    fakes.log = Loses(clock)
    outcome = fixed(base, fakes, clock).outcome
    assert isinstance(outcome, Stopped) and outcome.why == "failed"
    assert len(fakes.revisions.stored) == 1
    assert isinstance(outcome.stored, StoredRevision) and outcome.stored.version == 2
    assert [u.kind for u in outcome.unlogged] == ["fix_proposed"]


class Retried(FakeLog):
    """A log whose run was retried just before the proposal."""

    def note(self, data: FixData) -> FixRefusal | None:
        if isinstance(data, FixProposedData):
            self.stopped = False
        return super().note(data)


def test_a_proposal_the_log_refuses_stops_the_fix_with_its_stored_version():
    base = CASES[RENAMED]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    fakes.log = Retried(clock)
    outcome = fixed(base, fakes, clock).outcome
    assert isinstance(outcome, Stopped) and outcome.why == "not_stopped"
    assert outcome.stored is not None and outcome.stored.version == 2
    assert FIX_ID in {e.fix_id for e in fakes.log.events}
