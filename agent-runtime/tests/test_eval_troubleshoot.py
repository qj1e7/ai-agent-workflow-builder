import pytest
from evals.checks import Check
from evals.jobs import Answer
from evals.runner import JOBS
from evals.troubleshoot import TROUBLESHOOT, TroubleshootCase, request_of

from agent_runtime.contract import CauseFound, CauseKept
from agent_runtime.troubleshooting import cause_messages, find_cause
from tests.fakes import ScriptedChat

CASES = {case.id: case for case in TROUBLESHOOT.cases()}


def failed(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.detail for c in checks if not c.passed}


def scored(case: TroubleshootCase, shown: CauseFound | CauseKept) -> dict[str, str]:
    return failed(TROUBLESHOOT.score(case, Answer(shown, shown.model_dump_json(), None)))


def recorded(case: TroubleshootCase) -> ScriptedChat:
    """The case's recorded reply, so no paid call is made."""
    return ScriptedChat(structured=[case.reference])


def found(case: TroubleshootCase, **fields: object) -> CauseFound:
    reference = case.reference
    return CauseFound.model_validate(
        {
            "failed_part": reference.failed_part,
            "system": reference.system,
            "failure_kind": reference.failure_kind,
            "detail": reference.detail,
            **fields,
        }
    )


def test_the_set_holds_adr_0055s_troubleshooter_cases():
    assert {
        "renamed-repository",
        "changed-jira-project",
        "moved-field",
        "instruction-in-the-error",
        "instruction-in-a-release-note",
        "stopped-at-two-blocks",
    } <= set(CASES)
    assert TROUBLESHOOT in JOBS
    assert TROUBLESHOOT.most_calls == 1
    assert len(CASES["stopped-at-two-blocks"].failed_part) == 2


@pytest.mark.parametrize("case", CASES.values(), ids=lambda c: c.id)
def test_each_case_stops_at_blocks_of_its_version(case: TroubleshootCase):
    assert set(case.failed_part) <= set(case.stopped_at) <= set(case.blocks)
    assert request_of(case).stopped_at == case.stopped_at


@pytest.mark.parametrize("case", CASES.values(), ids=lambda c: c.id)
def test_each_recorded_reply_passes_the_products_checks_and_scores_clean(case: TroubleshootCase):
    answer = TROUBLESHOOT.ask(recorded(case), case)
    assert answer.value == found(case)
    assert failed(TROUBLESHOOT.score(case, answer)) == {}


def test_the_job_sends_exactly_what_the_product_sends():
    case = CASES["renamed-repository"]
    chat = recorded(case)
    TROUBLESHOOT.ask(chat, case)
    system, user = cause_messages(request_of(case))
    assert chat.calls[0] == [("system", system), ("human", user)]


def test_the_rule_table_kept_misses_the_case():
    assert scored(CASES["moved-field"], CauseKept(why="not_a_detail")) == {
        "found": "kept: not_a_detail"
    }


@pytest.mark.parametrize(
    ("fields", "check"),
    [
        ({"failed_part": ["Newer?"]}, "failed_part"),
        ({"system": "jira"}, "system"),
        ({"failure_kind": "refused"}, "failure_kind"),
        ({"detail": "fastapi"}, "detail"),
        ({"detail": None}, "detail"),
    ],
    ids=["failed-part", "system", "kind", "detail", "no-detail"],
)
def test_each_field_is_scored_against_the_cases_truth(fields: dict[str, object], check: str):
    case = CASES["renamed-repository"]
    assert set(scored(case, found(case, **fields))) == {check}


@pytest.mark.parametrize(
    ("case_id", "part"),
    [
        ("instruction-in-the-error", ["Ask for a yes"]),
        ("instruction-in-a-release-note", ["Ask for a yes"]),
    ],
    ids=["delete-the-yes", "blame-the-yes"],
)
def test_the_product_refuses_a_failed_part_a_planted_instruction_asks_for(
    case_id: str, part: list[str]
):
    case = CASES[case_id]
    reply = case.reference.model_copy(update={"failed_part": part})
    shown = find_cause(request_of(case), lambda _timeout: ScriptedChat(structured=[reply]))
    assert shown == CauseKept(why="not_where_it_stopped")
    assert scored(case, shown) == {"found": "kept: not_where_it_stopped"}
