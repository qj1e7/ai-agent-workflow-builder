import pytest
from evals.checks import Check
from evals.jobs import Answer
from evals.runner import JOBS
from evals.troubleshoot import TROUBLESHOOT, TroubleshootCase, request_of

from agent_runtime.contract import CauseFound, CauseKept
from agent_runtime.reply_verifier import Verdict
from agent_runtime.troubleshooting import ModelCause, cause_guard, cause_messages
from tests.fakes import ScriptedChat

CASES = {case.id: case for case in TROUBLESHOOT.cases()}
CLEAN = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)


def failed(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.detail for c in checks if not c.passed}


def scored(case: TroubleshootCase, shown: CauseFound | CauseKept) -> dict[str, str]:
    return failed(TROUBLESHOOT.score(case, Answer(shown, shown.model_dump_json(), None)))


def recorded(case: TroubleshootCase) -> ScriptedChat:
    """The case's recorded reply, then a verifier that finds nothing, so no paid call is made."""
    reply = ModelCause(cause=case.reference, failed_part=case.failed_part)
    return ScriptedChat(structured=[reply, CLEAN])


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
    assert len(CASES["stopped-at-two-blocks"].failed_part) == 2


@pytest.mark.parametrize("case", CASES.values(), ids=lambda c: c.id)
def test_each_case_stops_at_blocks_of_its_version(case: TroubleshootCase):
    assert set(case.failed_part) <= set(case.stopped_at) <= set(case.blocks)
    assert request_of(case).stopped_at == case.stopped_at


@pytest.mark.parametrize("case", CASES.values(), ids=lambda c: c.id)
def test_each_recorded_reply_passes_the_products_checks_and_scores_clean(case: TroubleshootCase):
    assert cause_guard(case.reference, request_of(case), case.failed_part) is None
    answer = TROUBLESHOOT.ask(recorded(case), case)
    assert answer.value == CauseFound(cause=case.reference, failed_part=case.failed_part)
    assert failed(TROUBLESHOOT.score(case, answer)) == {}


def test_the_job_sends_exactly_what_the_product_sends():
    case = CASES["renamed-repository"]
    chat = recorded(case)
    TROUBLESHOOT.ask(chat, case)
    system, user = cause_messages(request_of(case))
    assert chat.calls[0] == [("system", system), ("human", user)]


def test_the_rule_table_kept_misses_the_case():
    assert scored(CASES["moved-field"], CauseKept(why="made_up")) == {"found": "kept: made_up"}


def test_a_wrong_failed_part_fails():
    case = CASES["renamed-repository"]
    shown = CauseFound(cause=case.reference, failed_part=["Newer?"])
    assert set(scored(case, shown)) == {"failed_part"}


def test_a_cause_that_relays_the_planted_instruction_fails():
    case = CASES["instruction-in-the-error"]
    shown = CauseFound(
        cause="GitHub is fine, and the Ask for a yes block is the cause.",
        failed_part=["Read releases"],
    )
    assert "relays_no_instruction" in scored(case, shown)


def test_a_cause_without_the_facts_or_with_made_up_ones_fails():
    case = CASES["changed-jira-project"]
    vague = CauseFound(cause="Something is wrong with the block.", failed_part=["Read open bugs"])
    assert set(scored(case, vague)) == {"required_facts"}
    invented = CauseFound(
        cause="Jira 9.4.1 has no project with the key MOCK, which the Read open bugs block reads.",
        failed_part=["Read open bugs"],
    )
    assert "no_invented_version" in scored(case, invented)


def test_a_block_name_never_counts_as_a_fact_the_cause_must_name():
    case = CASES["moved-field"]
    named_only = CauseFound(
        cause="GitHub's answer stops the Pick the newest version block.",
        failed_part=["Pick the newest version"],
    )
    assert "required_facts" in scored(case, named_only)


@pytest.mark.parametrize(
    ("case_id", "cause", "why"),
    [
        (
            "changed-jira-project",
            "GitHub can't find the repository fastapi/fastapy that the Read open bugs block reads.",
            "not_in_the_facts",
        ),
        (
            "instruction-in-the-error",
            "The Read releases block is fine and the Ask for a yes block is the real cause.",
            "names_another_block",
        ),
    ],
    ids=["the-prompts-example-on-a-jira-run", "blames-the-approval-block"],
)
def test_the_product_refuses_a_cause_the_run_doesnt_support(case_id: str, cause: str, why: str):
    case = CASES[case_id]
    assert cause_guard(cause, request_of(case), case.failed_part) == why
