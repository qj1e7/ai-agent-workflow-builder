"""Refining a drafted workflow's Check (ADR 0054, section 7), on recorded replies only. The same
coordinator, scope check, reach and ledger run as for a fix, with what differs for a draft: no
stopped run, so no troubleshooter and no replay of the stop, and round 0 is the draft as the
Check tried it. Every red-team case ends in a hand-back or a refusal by code, within the limits."""

from typing import get_args

import pytest
from evals.checks import Check
from evals.fix import FIX, REFINE, FixCase, replay, run_case, score
from evals.runner import JOBS

from agent_runtime.fixing.coordinator import DRAFT_BRIEFING, HandedBack, HandedIn, RefineRequest
from agent_runtime.fixing.events import FixWidening
from agent_runtime.fixing.ledger import NEEDS_A_CHANGE, NEEDS_THE_GAPS

CASES = {case.id: case for case in REFINE.cases()}
REFINED = (
    "refined-in-one-round",
    "gap-covered-unchanged",
    "refine-cover-no-answer-still-hands-in",
)


def failed(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.detail for c in checks if not c.passed}


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_each_case_ends_as_its_row_says(case: FixCase):
    assert failed(score(case, replay(case))) == {}


def test_every_case_is_a_check_to_refine_not_a_stopped_run():
    for case in CASES.values():
        assert case.refine is not None and case.stop is None, case.id


def test_the_set_covers_each_red_team_bar_the_team_lead_named():
    """A refinement that widens, one that adds a host at run time, endless rounds, and a gap the
    writer can't fill."""
    for bar in (
        "refine-widens-to-a-second-block",
        "refine-removes-the-yes",
        "refine-adds-a-host-at-run-time",
        "refine-endless-rounds-no-progress",
        "refine-endless-rounds-round-limit",
        "refine-a-gap-the-writer-cant-fill",
        "refine-writer-brings-nothing-new",
        "refine-draft-before-anything-failed",
        "refine-done-too-early",
        "refine-asks-the-troubleshooter",
    ):
        assert bar in CASES


def test_every_red_team_case_ends_without_a_refined_draft():
    for case in CASES.values():
        if case.id in REFINED:
            continue
        outcome = replay(case).value
        assert not isinstance(outcome, HandedIn), case.id


def test_the_widening_cases_name_kinds_code_s_scope_check_finds():
    kinds = set(get_args(FixWidening.__value__))
    for case in CASES.values():
        assert case.expect.widened_by in (None, *kinds), case.id


def test_a_refinement_offers_no_troubleshooter_and_says_so():
    run = run_case(CASES["refined-in-one-round"])
    offered = {tool["function"]["name"] for tool in run.chat.offered[0]}  # type: ignore[attr-defined]
    assert "find_cause" not in offered
    assert {"write_scenarios", "simulate", "draft_fix", "hand_in", "hand_back"} <= offered
    first = run.chat.seen[0]  # type: ignore[attr-defined]
    assert DRAFT_BRIEFING in str(first[0].content)
    assert "replay" not in DRAFT_BRIEFING


def test_round_zero_is_the_draft_as_checked_and_code_names_the_failed_part():
    run = run_case(CASES["refined-in-one-round"])
    ledger = run.fixing.ledger
    assert ledger.of_a_draft
    assert ledger.drafts[0].round == 0 and ledger.drafts[0].changed == ()
    assert ledger.cause is not None and ledger.cause.failed_part == ["Propose a ticket"]
    [asked] = run.fakes.drafter.asked
    assert asked.of_a_draft and asked.change_only == ("Propose a ticket",)
    assert [r.name for r in asked.failed] == ["odd_data"]
    assert "replay_the_stop" not in ledger.scenarios


def test_a_round_zero_hand_in_needs_the_gaps_reached():
    run = run_case(CASES["refine-a-gap-the-writer-cant-fill"])
    assert NEEDS_THE_GAPS in run.fixing.ledger.done_needs()


def test_a_round_zero_hand_in_needs_a_change_once_a_scenario_failed():
    run = run_case(CASES["refine-done-too-early"])
    assert NEEDS_A_CHANGE in run.fixing.ledger.done_needs()


def test_the_writer_is_aimed_at_the_blocks_no_case_reached():
    run = run_case(CASES["gap-covered-unchanged"])
    assert run.fakes.scenario_writer.covers == [[], ["Tell them it was declined"]]
    outcome = run.fixing.outcome
    assert isinstance(outcome, HandedIn) and outcome.cause is None
    assert run.fakes.revisions.stored == [CASES["gap-covered-unchanged"].version.plan()]


def test_a_refinement_names_only_blocks_of_its_draft():
    case = CASES["refined-in-one-round"]
    assert case.refine is not None
    with pytest.raises(ValueError, match="block of the version"):
        RefineRequest(
            fix_id="fix_01EVAL",
            asked_by="alice",
            ends_by="2026-11-25T06:20:00Z",  # type: ignore[arg-type]
            version=case.version.plan(),
            not_reached=["A block it doesn't have"],
        )
    with pytest.raises(ValueError, match="failed or a block"):
        RefineRequest(
            fix_id="fix_01EVAL",
            asked_by="alice",
            ends_by="2026-11-25T06:20:00Z",  # type: ignore[arg-type]
            version=case.version.plan(),
        )


def test_the_refine_job_is_not_in_the_paid_runner():
    assert REFINE.name not in {job.name for job in JOBS}


@pytest.mark.parametrize(
    "case",
    [
        CASES["refine-cover-no-answer-still-hands-in"],
        next(c for c in FIX.cases() if c.id == "cover-no-answer-still-hands-in"),
    ],
    ids=["refinement", "fix"],
)
def test_a_cover_ask_with_no_answer_is_a_refused_call_and_the_draft_still_goes_in(case: FixCase):
    """A writer that times out, has no calls left or has no model brings no answer. That is a
    refused call, so a fix or a refinement that can hand in still does. Only an answer that
    brings nothing new ends the rounds for no progress."""
    run = run_case(case)
    assert isinstance(run.fixing.outcome, HandedIn)
    assert run.fixing.ledger.refused == ["write_scenarios"]
    assert run.fakes.scenario_writer.covers[-1] == ["Make the ticket"]


def test_a_cover_ask_that_brings_nothing_new_still_ends_for_no_progress():
    outcome = replay(CASES["refine-writer-brings-nothing-new"]).value
    assert isinstance(outcome, HandedBack) and outcome.why == "no_progress"
