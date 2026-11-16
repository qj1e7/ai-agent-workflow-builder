from evals.checks import Check
from evals.explain_wording import EXPLAIN_WORDING, WordingCase, request_of
from evals.jobs import Answer

from agent_runtime.contract import ExplainKept, ExplainReworded
from agent_runtime.explain_wording import (
    ExplainWording,
    explain_guard,
    fact_check,
    wording_messages,
)
from agent_runtime.reply_verifier import Verdict
from tests.fakes import ScriptedChat

CASES = {case.id: case for case in EXPLAIN_WORDING.cases()}
CLEAN = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)
SMOOTHED = (
    "Each day at 8:00 it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
    "It can create Jira tickets in “MOCK”, each after a yes. Nothing else changes."
)


def failed(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.detail for c in checks if not c.passed}


def scored(case: WordingCase, shown: ExplainReworded | ExplainKept) -> dict[str, str]:
    return failed(EXPLAIN_WORDING.score(case, Answer(shown, shown.model_dump_json(), None)))


def test_the_set_is_code_s_in_short_for_each_golden_document():
    assert {"agent-cards", "release-check", "release-notice", "watchlist"} <= set(CASES)
    assert any(c.can_reword for c in CASES.values())
    assert any(not c.can_reword for c in CASES.values())


def test_code_s_own_wording_keeps_to_the_facts_of_every_case():
    for case in CASES.values():
        assert fact_check(case.wording, request_of(case)) is None, case.id


def test_a_case_can_be_reworded_exactly_when_the_guard_lets_code_s_own_wording_through():
    for case in CASES.values():
        assert (explain_guard(case.wording, request_of(case)) is None) == case.can_reword, case.id


def test_the_job_sends_exactly_what_the_product_sends():
    case = CASES["fastapi"]
    chat = ScriptedChat(structured=[ExplainWording(text=SMOOTHED), CLEAN])
    answer = EXPLAIN_WORDING.ask(chat, case)
    system, user = wording_messages(request_of(case))
    assert chat.calls[0] == [("system", system), ("human", user)]
    assert answer.value == ExplainReworded(text=SMOOTHED)
    assert scored(case, ExplainReworded(text=SMOOTHED)) == {}


def test_a_case_that_can_be_reworded_fails_when_code_s_wording_is_kept():
    assert scored(CASES["fastapi"], ExplainKept(why="words")) == {"reworded": "kept: words"}


def test_a_case_no_smoothing_can_pass_scores_code_s_wording_kept():
    case = CASES["release-notice"]
    assert scored(case, ExplainKept(why="claims_unbuilt")) == {}
    assert set(scored(case, ExplainReworded(text=case.wording))) == {"reworded"}


def test_a_shown_smoothing_that_drops_a_fact_or_a_negation_fails():
    case = CASES["fastapi"]
    dropped = SMOOTHED.replace("Each day at 8:00 it reads", "It reads")
    assert set(scored(case, ExplainReworded(text=dropped))) == {"true_to_the_facts"}
    unsaid = SMOOTHED.replace("Nothing else changes.", "Something else changes too.")
    assert set(scored(case, ExplainReworded(text=unsaid))) == {"true_to_the_facts"}
