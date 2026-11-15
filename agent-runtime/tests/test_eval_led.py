import json

import pytest
from evals.budget import dollars_for
from evals.reply import REPLY_LED, SPIKE_LED
from evals.runner import AI_LED, jobs_chosen, run_case

from tests.fakes import ScriptedChat, asks, call
from tests.test_planner_led import CLEAN
from tests.test_questions import reading

PRICE = {"input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0}


def reply_case(case_id: str):
    return next(c for c in REPLY_LED.cases() if c.id == case_id)


def spike_case(case_id: str):
    return next(c for c in SPIKE_LED.cases() if c.id == case_id)


def test_ai_led_mode_runs_the_planners_jobs_on_the_ai_led_planner() -> None:
    names = "answer,anything,reply,spike,red_team"
    rules = jobs_chosen({"EVAL_JOBS": names})
    led = jobs_chosen({"EVAL_JOBS": names, "EVAL_PLANNER_MODE": "ai_led"})

    assert [j.name for j in led] == [j.name for j in rules]
    twins = {j.name: j is AI_LED.get(j.name) for j in led}
    assert twins == {
        "answer": True,
        "anything": True,
        "reply": True,
        "spike": True,
        "red_team": False,
    }
    with pytest.raises(ValueError, match="EVAL_PLANNER_MODE"):
        jobs_chosen({"EVAL_PLANNER_MODE": "free"})


def test_the_team_leads_sentence_scores_as_asking_which_software() -> None:
    chat = ScriptedChat(
        script=[asks(call("ask_which_software", {"word": "software"}, "c1"))],
        structured=[reading("none")],
    )

    outcome = run_case(chat, SPIKE_LED, spike_case("add-01"), {})

    assert outcome.passed, [c for c in outcome.checks if not c.passed]
    assert {c.name for c in outcome.checks} >= {"right_kind", "asks_for_the_detail"}
    assert outcome.answer.startswith("[which_software]")


def test_the_answer_to_which_software_scores_as_the_right_action() -> None:
    chat = ScriptedChat(
        script=[asks(call("watch_software", {"software": "LangGraph"}, "c1"))],
        structured=[reading("none")],
    )

    outcome = run_case(chat, SPIKE_LED, spike_case("follow-01"), {})

    assert outcome.passed, [c for c in outcome.checks if not c.passed]
    assert "right_action" in {c.name for c in outcome.checks}


def test_a_fallback_is_a_failed_check_with_why() -> None:
    bad = {"form": "answer", "text": "I set up the workflow."}
    chat = ScriptedChat(
        script=[asks(call("reply", bad, "c1")), asks(call("reply", bad, "c2"))],
        structured=[reading(), CLEAN],
    )

    outcome = run_case(chat, SPIKE_LED, spike_case("chat-01"), {})

    failed = {c.name: c.detail for c in outcome.checks if not c.passed}
    assert "claims_done" in json.dumps(failed["led_answer_shown"])


def test_cached_input_is_priced_at_the_caches_share() -> None:
    fresh = dollars_for(10_000, 100, 0, 0, PRICE)
    cached = dollars_for(10_000, 100, 8_000, 0, PRICE)
    written = dollars_for(10_000, 100, 0, 8_000, PRICE)

    assert fresh == pytest.approx(0.021)
    assert cached == pytest.approx((2_000 + 800) * 2e-6 + 100 * 1e-5)
    assert written == pytest.approx((2_000 + 10_000) * 2e-6 + 100 * 1e-5)


def test_the_judge_reads_the_marks_the_answer_carries() -> None:
    chat = ScriptedChat(
        script=[asks(call("show", {"what": "how_to_start"}, "c1"))],
        structured=[reading()],
    )

    outcome = run_case(chat, REPLY_LED, reply_case("how_to-17"), {})

    assert outcome.answer.startswith("[how_to_start] How to start:")
