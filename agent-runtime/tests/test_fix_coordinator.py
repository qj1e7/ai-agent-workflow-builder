"""The coordinator of a fix (ADR 0055, sections 3 to 6), on the eval's fakes and recorded
replies, so no model is called. The red-team bars are the eval's cases (test_eval_fix.py). These
pin the mechanics around them: the strict tools, what the model reads, how the log's refusals
are handled, and what counts toward the cost."""

import ast
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from evals.fix import (
    FIX,
    FIX_ID,
    STARTED,
    Clock,
    FakeDrafter,
    FakeLog,
    Fakes,
    FakeTroubleshooter,
    FixCase,
    RecordedChat,
    RecordedTurn,
    Run,
    prices,
    request_of,
    run_case,
)

from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.fixing import coordinator
from agent_runtime.fixing.coordinator import (
    HAND_BACK,
    MOST_DOLLARS,
    MOST_SCENARIOS_TRIED,
    HandedBack,
    HandedIn,
    Stopped,
    coordinating,
)
from agent_runtime.fixing.events import (
    FIX_TIME_LIMIT,
    MOST_BLOCKS,
    FixData,
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
    FixRefusal,
    FixStartedData,
)
from agent_runtime.fixing.ports import FixDraftRequest, NotDrafted

CASES = {case.id: case for case in FIX.cases()}
READ = "Read new releases"
TOOLS = [
    "find_cause",
    "write_scenarios",
    "draft_fix",
    "simulate",
    "check_version",
    "hand_in",
    "hand_back",
]


def case(id_: str, **changes: Any) -> FixCase:
    return FixCase.model_validate({**CASES[id_].model_dump(), **changes})


def turns(*calls: tuple[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"calls": [{"name": name, "args": args}]} for name, args in calls]


def played(run: Run) -> list[str]:
    return [name for name, _ in run.fakes.played.calls]


def handoffs_of(fakes: Fakes) -> list[FixHandoffData]:
    return [e for e in fakes.log.events if isinstance(e, FixHandoffData)]


def fixed_with(base: FixCase, clock: Clock, fakes: Fakes, **chat: Any) -> tuple[Any, RecordedChat]:
    """The case's fix on `fakes`, which a test changed, with its recorded replies."""
    model = RecordedChat(turns=list(base.replies), clock=clock, **chat)
    return coordinating(request_of(base), lambda _t: model, fakes.parts(), prices(), clock), model


def test_the_coordinator_is_offered_only_its_seven_strict_tools():
    run = run_case(CASES["fixable-renamed-repository"])
    assert isinstance(run.chat, RecordedChat)
    for offered in run.chat.offered:
        assert [tool["function"]["name"] for tool in offered] == TOOLS
        for tool in offered:
            function = tool["function"]
            assert function["strict"] is True
            parameters = function["parameters"]
            assert parameters["additionalProperties"] is False
            assert sorted(parameters.get("required", [])) == sorted(parameters["properties"])
    assert all(bound["strict"] is True for bound in run.chat.bound_with)


def test_a_fix_code_accepts_is_stored_once_and_proposed_with_its_version_and_digest():
    run = run_case(CASES["fixable-renamed-repository"])
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedIn)
    assert run.fakes.revisions.stored == [outcome.plan]
    assert run.fakes.revisions.causes == [outcome.cause]
    [proposed] = [e for e in run.fakes.log.events if isinstance(e, FixProposedData)]
    assert (proposed.version, proposed.digest) == (outcome.version, outcome.digest)
    read = next(b for b in outcome.plan.blocks if b.name == READ)
    assert read.parameters["place"] == "langchain-ai/langgraph-py"
    assert [(r.round, r.passed, r.scenarios, r.changed) for r in outcome.rounds] == [
        (1, 3, 3, (READ,))
    ]


def test_the_hand_back_gives_the_cause_and_each_round_tried():
    run = run_case(CASES["endless-rounds-no-better"])
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedBack)
    assert outcome.words == HAND_BACK == "I couldn't fix this. Here's the cause and what I tried."
    assert outcome.why == "no_progress"
    assert outcome.cause is not None and outcome.cause.failed_part == [READ]
    assert [(r.round, r.passed, r.scenarios) for r in outcome.rounds] == [(1, 2, 3), (2, 2, 3)]
    assert [(f.name, f.step) for f in outcome.rounds[1].failed] == [("Nothing new", READ)]


def test_the_fix_drafter_gets_only_the_blocks_named_and_the_failed_scenarios_with_why():
    run = run_case(CASES["fixable-jira-key-in-a-second-round"])
    first, second = run.fakes.drafter.asked
    assert (first.round, first.change_only, first.failed) == (1, ("Propose a ticket",), ())
    assert second.round == 2
    assert [(f.name, f.step, f.why) for f in second.failed] == [
        ("Two new releases", "Propose a ticket", "stopped")
    ]


def test_a_key_in_what_the_run_read_never_reaches_the_model():
    key = "sk-" + "ant-" + "api03-" + "Zq7" * 10
    stop = CASES["planted-approve-and-turn-on"].stop.model_copy(
        update={"message": f"Unauthorized: the token {key} was refused (401)"}
    )
    run = run_case(case("planted-approve-and-turn-on", stop=stop))
    assert isinstance(run.chat, RecordedChat)
    seen = "\n".join(str(m.content) for messages in run.chat.seen for m in messages)
    assert key not in seen
    assert "[masked]" in seen


def test_a_block_name_the_log_can_t_show_is_kept_as_not_logged_and_the_fix_goes_on(
    caplog: pytest.LogCaptureFixture,
):
    quoted = "Read \u201cnew\u201d releases"
    renamed = CASES["fixable-renamed-repository"].model_dump_json().replace(READ, quoted)
    with caplog.at_level(logging.WARNING):
        run = run_case(FixCase.model_validate_json(renamed))
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedIn)
    assert [(u.kind, u.handoff, u.why) for u in outcome.unlogged] == [
        ("fix_handoff", 1, "shape"),
        ("fix_handoff", 3, "shape"),
    ]
    assert [e.handoff for e in handoffs_of(run.fakes)] == [2, 4, 5]
    assert run.fakes.log.kinds()[-1] == "fix_proposed"
    assert "the log took no fix_handoff (shape)" in caplog.text
    assert quoted not in caplog.text


def test_the_coordinator_never_writes_the_fix_s_start_platform_api_wrote_it():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    note = fakes.log.note
    noted: list[FixData] = []

    def kept(data: FixData) -> FixRefusal | None:
        noted.append(data)
        return note(data)

    fakes.log.note = kept  # type: ignore[method-assign]
    fixing, _ = fixed_with(base, clock, fakes)
    assert isinstance(fixing.outcome, HandedIn)
    assert not any(isinstance(data, FixStartedData) for data in noted)
    assert [e for e in fakes.log.events if isinstance(e, FixStartedData)] == [
        FixStartedData(
            fix_id=FIX_ID, asked_by="alice", asked_by_name="Alice", ends_by=STARTED + FIX_TIME_LIMIT
        )
    ]


def test_a_fix_the_log_never_started_runs_nothing_past_its_first_event():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    fakes.log.events.clear()
    fixing, _ = fixed_with(base, clock, fakes)
    assert fixing.outcome == Stopped("not_started")
    assert [name for name, _ in fakes.played.calls] == ["troubleshooter"]


@pytest.mark.parametrize(("written", "found"), [(19, "kept"), (20, "refused")])
def test_a_fix_holds_at_most_20_scenarios_its_replay_of_the_stop_included(written: int, found: str):
    base = CASES["fixable-renamed-repository"]
    many = [[{"name": f"Case {n}", "reads": [READ]} for n in range(written)]]
    run = run_case(case(base.id, scenarios=many))
    [writer] = [e for e in handoffs_of(run.fakes) if e.to == "scenario_writer"]
    assert writer.found == found
    assert len(run.fixing.ledger.scenarios) <= MOST_SCENARIOS_TRIED == 20


def test_a_run_retried_during_the_fix_stops_it():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)

    class Retried(FakeTroubleshooter):
        def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
            fakes.log.stopped = False
            return super().find_cause(look_at, seconds)

    fakes.troubleshooter = Retried(fakes.troubleshooter.script, fakes.played)
    fixing, _ = fixed_with(base, clock, fakes)
    assert isinstance(fixing.outcome, Stopped) and fixing.outcome.why == "not_stopped"
    assert [name for name, _ in fakes.played.calls] == ["troubleshooter"]
    assert fakes.log.kinds() == ["fix_started"]


def test_a_log_that_fails_keeps_the_event_as_not_logged_and_the_fix_goes_on():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    note = fakes.log.note

    def failing(data: FixData) -> FixRefusal | None:
        if isinstance(data, FixHandoffData) and data.to == "scenario_writer":
            raise ConnectionError("platform-api didn't answer")
        return note(data)

    fakes.log.note = failing  # type: ignore[method-assign]
    fixing, _ = fixed_with(base, clock, fakes)
    assert isinstance(fixing.outcome, HandedIn)
    assert [(u.kind, u.handoff, u.why) for u in fixing.outcome.unlogged] == [
        ("fix_handoff", 2, "failed")
    ]


def test_a_sub_agent_that_fails_is_no_answer_and_can_be_asked_again():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    tries: list[str | None] = []

    class Flaky(FakeTroubleshooter):
        def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
            tries.append(look_at)
            if len(tries) == 1:
                raise TimeoutError("the model didn't answer")
            return super().find_cause(look_at, seconds)

    fakes.troubleshooter = Flaky(fakes.troubleshooter.script, fakes.played)
    again = base.model_copy(update={"replies": [base.replies[0], *base.replies]})
    fixing, _ = fixed_with(again, clock, fakes)
    assert isinstance(fixing.outcome, HandedIn)
    first, second = handoffs_of(fakes)[:2]
    assert (first.to, first.found, second.found) == ("troubleshooter", "no_answer", "confirmed")


def test_only_the_first_call_a_turn_makes_is_handed_off():
    base = CASES["fixable-renamed-repository"]
    both = RecordedTurn.model_validate(
        {
            "calls": [
                {"name": "find_cause", "args": {"look_at": None}},
                {"name": "write_scenarios", "args": {"cover": []}},
            ]
        }
    )
    run = run_case(base.model_copy(update={"replies": [both, *base.replies[1:]]}))
    assert isinstance(run.fixing.outcome, HandedIn)
    assert run.fixing.ledger.refused == ["write_scenarios"]
    assert played(run).count("scenario_writer") == 1


def test_a_new_cause_drops_the_draft_made_for_the_old_one():
    base = CASES["fixable-renamed-repository"]
    run = run_case(
        case(
            base.id,
            stopped_at=[READ, "Propose a ticket"],
            causes=[*base.model_dump()["causes"], {"failed_part": ["Propose a ticket"]}],
            replies=[
                *base.model_dump()["replies"][:5],
                *turns(
                    ("find_cause", {"look_at": "Propose a ticket"}),
                    ("hand_in", {}),
                    ("hand_back", {}),
                ),
            ],
        )
    )
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "gave_up"
    assert run.fixing.ledger.refused == ["hand_in"]
    assert run.fakes.revisions.stored == []


def test_every_model_call_in_the_fix_counts_toward_its_cost_a_sub_agent_s_too():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    sub_agent_model = RecordedChat(turns=[RecordedTurn(tokens_in=1_000_000, tokens_out=0)])

    class Costly(FakeTroubleshooter):
        def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
            sub_agent_model.invoke("Name the cause.")
            return super().find_cause(look_at, seconds)

    fakes.troubleshooter = Costly(fakes.troubleshooter.script, fakes.played)
    fixing, chat = fixed_with(base, clock, fakes)
    assert fixing.cost.calls == 2
    assert fixing.cost.dollars >= MOST_DOLLARS
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "cost_limit"
    assert len(chat.seen) == 1


def test_a_model_the_fix_can_t_price_breaks_the_cost_cap():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    fixing, _ = fixed_with(base, clock, fakes, model="a-model-with-no-price")
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "cost_limit"
    assert fixing.cost.unpriced == {"a-model-with-no-price"}
    assert fakes.played.calls == []


def test_a_turn_that_fails_hands_the_fix_back():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)

    def no_model(_timeout: float) -> RecordedChat:
        raise ConnectionError("the provider is down")

    fixing = coordinating(request_of(base), no_model, fakes.parts(), prices(), clock)
    assert fixing.outcome == HandedBack(why="no_cause", cause=None, rounds=(), unlogged=())
    assert fakes.log.kinds() == ["fix_started", "fix_handed_back"]


def test_each_turn_waits_at_most_until_the_deadline():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED + FIX_TIME_LIMIT - timedelta(seconds=30))
    fakes = Fakes(base, clock)
    asked: list[float] = []
    chat = RecordedChat(turns=list(base.replies), clock=clock)

    def chat_for(timeout: float) -> RecordedChat:
        asked.append(timeout)
        return chat

    coordinating(request_of(base), chat_for, fakes.parts(), prices(), clock)
    assert asked and asked[0] == 30.0


def test_the_request_holds_the_blocks_where_the_run_stopped_to_the_version():
    with pytest.raises(ValueError, match="stopped_at"):
        request_of(case("fixable-renamed-repository", stopped_at=["Not a block"]))


def test_the_fix_id_is_the_one_the_events_carry():
    run = run_case(CASES["fixable-renamed-repository"])
    assert {e.fix_id for e in run.fakes.log.events} == {FIX_ID}


def test_each_hand_off_is_told_the_seconds_left_and_the_fix_drafter_the_dollars_left():
    run = run_case(CASES["fixable-renamed-repository"])
    fakes = run.fakes
    [asked_at] = [at for name, at in fakes.played.calls if name == "troubleshooter"]
    left = (STARTED + FIX_TIME_LIMIT - asked_at).total_seconds()
    assert fakes.troubleshooter.script.given == [left]
    assert all(0 < given < FIX_TIME_LIMIT.total_seconds() for given in fakes.drafter.script.given)
    [dollars] = fakes.drafter.dollars_left
    assert 0 < dollars < MOST_DOLLARS


class RealClock(Clock):
    """The wall clock, for a hand-off that really takes its time."""

    def __call__(self) -> datetime:
        return datetime.now(UTC)

    def wait(self, seconds: float) -> None:
        pass


def test_a_slow_sub_agent_is_stopped_at_the_deadline_not_waited_for():
    base = case("fixable-renamed-repository", seconds={"troubleshooter": 0, "scenario_writer": 0})
    clock = RealClock(datetime.now(UTC))
    fakes = Fakes(base, clock)
    released = threading.Event()

    class Stuck(FakeDrafter):
        def draft(
            self, request: FixDraftRequest, seconds: float, dollars_left: Callable[[], float]
        ) -> WorkflowPlan | NotDrafted:
            released.wait(60)
            return "no_answer"

    fakes.drafter = Stuck(fakes.drafter.script, fakes.played)
    request = request_of(base).model_copy(update={"ends_by": clock() + timedelta(seconds=2)})
    chat = RecordedChat(turns=list(base.replies))
    began = time.monotonic()
    try:
        fixing = coordinating(request, lambda _t: chat, fakes.parts(), prices(), clock)
        took = time.monotonic() - began
        assert not released.is_set()
    finally:
        released.set()
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "time_limit"
    assert took < 10
    assert fakes.log.kinds()[-1] == "fix_handed_back"


def test_a_fix_drafter_stopped_by_the_cost_cap_hands_back_for_cost():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    costly = RecordedChat(turns=[RecordedTurn(tokens_in=1_000_000, tokens_out=0)])
    lefts: list[float] = []

    class Spends(FakeDrafter):
        def draft(
            self, request: FixDraftRequest, seconds: float, dollars_left: Callable[[], float]
        ) -> WorkflowPlan | NotDrafted:
            costly.invoke("Draft the fix.")
            lefts.append(dollars_left())
            return "no_answer"

    fakes.drafter = Spends(fakes.drafter.script, fakes.played)
    fixing, _ = fixed_with(base, clock, fakes)
    outcome = fixing.outcome
    assert lefts and lefts[0] <= 0
    assert isinstance(outcome, HandedBack) and outcome.why == "cost_limit"


def test_a_fix_the_log_already_ended_stops_with_the_log_s_reason_not_time():
    base = CASES["fixable-renamed-repository"]
    clock = Clock(STARTED)
    fakes = Fakes(base, clock)
    proposed = FixProposedData(fix_id=FIX_ID, version=9, digest="sha256:" + "0" * 64)

    class EndedElsewhere(FakeTroubleshooter):
        def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
            fakes.log.events.append(proposed)
            return super().find_cause(look_at, seconds)

    fakes.troubleshooter = EndedElsewhere(fakes.troubleshooter.script, fakes.played)
    fixing, _ = fixed_with(base, clock, fakes)
    assert fixing.outcome == Stopped("ended")
    assert [kind for kind, _ in fakes.log.refused] == [
        "fix_handoff",
        "fix_handed_back",
    ]


def test_a_hand_back_the_log_refuses_as_ended_is_for_time_only_when_the_log_takes_that():
    base = case(
        "hand-in-before-anything",
        replies=[{"calls": [{"name": "hand_back", "args": {}}]}],
    )
    clock, log_clock = Clock(STARTED), Clock(STARTED)
    fakes = Fakes(base, clock)
    fakes.log = FakeLog(log_clock)
    chat = RecordedChat(turns=list(base.replies), clock=log_clock, seconds=21 * 60)
    fixing = coordinating(request_of(base), lambda _t: chat, fakes.parts(), prices(), clock)
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "time_limit"
    assert fakes.log.events[-1] == FixHandedBackData(fix_id=FIX_ID, why="time_limit")
    assert [kind for kind, why in fakes.log.refused] == ["fix_handed_back"]


def test_a_failed_part_too_wide_for_one_fix_is_logged_and_never_drafted():
    parts = [f"Read part {n}" for n in range(1, MOST_BLOCKS + 2)]
    version = {
        "name": "Many reads",
        "blocks": [
            {"name": "Every Monday", "type": "n8n-nodes-base.scheduleTrigger"},
            *({"name": name, "type": "CUSTOM.wabRead"} for name in parts),
        ],
        "wires": [],
    }
    run = run_case(
        case(
            "hand-in-before-anything",
            version=version,
            stopped_at=parts,
            causes=[{"failed_part": parts}],
            replies=turns(
                ("find_cause", {"look_at": None}),
                ("draft_fix", {"change_only": parts[:1], "failed_scenarios": []}),
                ("hand_back", {}),
            ),
        )
    )
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "no_cause"
    [found] = handoffs_of(run.fakes)
    assert (found.to, found.found, found.blocks) == ("troubleshooter", "too_wide", [])
    assert outcome.unlogged == () and run.fixing.ledger.refused == ["draft_fix"]
    assert run.fakes.drafter.asked == []


def test_the_coordinator_guards_with_checks_that_run_whatever_python_s_flags():
    source = Path(coordinator.__file__).read_text()
    asserts = [node.lineno for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Assert)]
    assert asserts == []
