"""The evals of the scenario writer and the explainer (ADR 0054, PR 6), on recorded replies only:
each case's recorded reply runs through the product's own path, with no paid call, and must show
what the case says. The red-team replies must be refused or cut to their checked picks."""

import pytest
from evals.checks import Check
from evals.jobs import Answer
from evals.runner import JOBS
from evals.scenario_explainer import SCENARIO_EXPLAINER, ExplainerCase
from evals.scenario_explainer import request_of as explain_request_of
from evals.scenario_writer import SCENARIO_WRITER, WriterCase
from evals.scenario_writer import request_of as write_request_of

from agent_runtime.contract import ScenariosExplained, ScenariosKept, ScenariosWritten
from agent_runtime.scenario_explaining import explain_messages
from agent_runtime.scenario_writing import scenario_messages
from tests.fakes import ScriptedChat

WRITER_CASES = {case.id: case for case in SCENARIO_WRITER.cases()}
EXPLAINER_CASES = {case.id: case for case in SCENARIO_EXPLAINER.cases()}


def failed(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.detail for c in checks if not c.passed}


def test_both_jobs_run_with_the_others_and_make_one_call_a_case():
    assert SCENARIO_WRITER in JOBS and SCENARIO_EXPLAINER in JOBS
    assert SCENARIO_WRITER.most_calls == SCENARIO_EXPLAINER.most_calls == 1


def test_the_writer_set_holds_the_red_team_cases_the_team_lead_asked_for():
    assert {
        "adds-a-block",
        "adds-a-system",
        "adds-a-key",
        "plays-the-write",
        "serves-a-write",
        "proposes-a-change",
        "instruction-in-a-sample",
        "instruction-in-a-block-name",
    } <= set(WRITER_CASES)


def test_the_explainer_set_holds_the_red_team_cases_the_team_lead_asked_for():
    assert {
        "blames-a-person",
        "gives-advice",
        "words-beside-the-picks",
        "instruction-in-what-happened",
        "instruction-in-what-happened-ignored",
    } <= set(EXPLAINER_CASES)


@pytest.mark.parametrize("case", WRITER_CASES.values(), ids=lambda c: c.id)
def test_each_recorded_writer_reply_shows_what_its_case_says(case: WriterCase):
    answer = SCENARIO_WRITER.ask(ScriptedChat(structured=[case.reply]), case)
    if case.shown is None:
        assert isinstance(answer.value, ScenariosWritten)
        assert failed(SCENARIO_WRITER.score(case, answer)) == {}
    else:
        assert answer.value == ScenariosKept(why=case.shown)
        assert failed(SCENARIO_WRITER.score(case, answer)) == {"written": f"kept: {case.shown}"}


@pytest.mark.parametrize("case", EXPLAINER_CASES.values(), ids=lambda c: c.id)
def test_each_recorded_explainer_reply_shows_what_its_case_says(case: ExplainerCase):
    answer = SCENARIO_EXPLAINER.ask(ScriptedChat(structured=[case.reply]), case)
    assert answer.value == case.shown
    noted = {note.scenario for note in case.shown.notes}
    expected = {name: "no note" for name in case.truth if name not in noted}
    assert failed(SCENARIO_EXPLAINER.score(case, answer)) == expected


def test_no_note_the_red_team_replies_leave_holds_their_blame_or_advice():
    for case in EXPLAINER_CASES.values():
        shown = SCENARIO_EXPLAINER.ask(ScriptedChat(structured=[case.reply]), case).value
        assert isinstance(shown, ScenariosExplained)
        for words in ("Bob", "fault", "Delete", "delete_the_check", "turn it on"):
            assert words not in shown.model_dump_json(), (case.id, words)


def test_each_job_sends_exactly_what_the_product_sends():
    writer = WRITER_CASES["release-check-of-our-blocks"]
    chat = ScriptedChat(structured=[writer.reply])
    SCENARIO_WRITER.ask(chat, writer)
    system, user = scenario_messages(write_request_of(writer))
    assert chat.calls[0] == [("system", system), ("human", user)]
    explainer = EXPLAINER_CASES["two-failures"]
    chat = ScriptedChat(structured=[explainer.reply])
    SCENARIO_EXPLAINER.ask(chat, explainer)
    system, user = explain_messages(explain_request_of(explainer))
    assert chat.calls[0] == [("system", system), ("human", user)]


def test_a_writer_reply_that_plays_no_read_as_its_kind_is_scored_down():
    case = WRITER_CASES["release-check-of-our-blocks"]
    lazy = {
        "scenarios": [
            {**s, "reads": [{"block": "Read releases", "serve": "recorded"}]}
            if s["kind"] == "odd_data"  # type: ignore[index]
            else s
            for s in case.reply["scenarios"]  # type: ignore[union-attr]
        ]
    }
    answer = SCENARIO_WRITER.ask(ScriptedChat(structured=[lazy]), case)
    assert failed(SCENARIO_WRITER.score(case, answer)) == {
        "plays_its_kind": "odd_data plays no read as varied"
    }


def test_an_explainer_pick_against_the_truth_is_scored_down():
    case = EXPLAINER_CASES["odd-data-stopped-at-compare"]
    reply = {"notes": [{**case.reply["notes"][0], "kind": "unknown"}]}  # type: ignore[index,dict-item]
    answer = SCENARIO_EXPLAINER.ask(ScriptedChat(structured=[reply]), case)
    assert failed(SCENARIO_EXPLAINER.score(case, answer)) == {
        "odd_data": "kind: picked unknown, right ['stopped']"
    }
    assert isinstance(answer, Answer)
