"""Code grades each scenario (ADR 0054, section 5, and spike S7): it reads the gateway's record of
the simulated run and n8n's record of the execution, and holds them to the outcome it expects for
the scenario's kind. A pinned block is not tried, never passed. The model never grades."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from platform_api.orchestration.n8n import ExecutionRecord
from platform_api.orchestration.recorded_samples import RecordedSamples
from platform_api.orchestration.scenario_grades import (
    AFTER_WRITE,
    EXPECTED,
    WAIT_LIMIT_SECONDS,
    coverage,
    grade,
    not_tried,
)
from platform_api.orchestration.scenarios import (
    KINDS,
    NotTried,
    ScenarioKind,
    SimulationPlan,
    Staged,
    stage,
    templates,
)
from platform_api.orchestration.simulated_calls import (
    SOURCE_NOT_FOUND,
    SOURCE_TIMED_OUT,
    CallRecord,
    ProposedChange,
    SimulatedRun,
)
from tests.test_scenarios import (
    PROPOSE,
    START,
    github_read,
    jira_read,
    our_read,
    planned,
    release_check,
    tidy,
)

NOW = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
WRITE = "Make the approved changes"
NEVER_WRITES = "A simulation never writes."
DROPPED = (
    "The connection to the server was closed unexpectedly, perhaps it is offline. You can retry "
    "the request immediately or wait and retry later."
)
UP_TO_ASK = (START, "Read releases", "Compare", "Propose a change", "Ask for a yes")


def staged(plan: SimulationPlan) -> dict[ScenarioKind, Staged]:
    samples = RecordedSamples()
    return {made.kind: stage(made, plan, samples) for made in templates(plan, samples)}


def change(**over: Any) -> ProposedChange:
    return ProposedChange.model_validate({"block": "Propose a change", **PROPOSE, **over})


def call(block: str, kind: Any, outcome: Any, detail: str | None = None) -> CallRecord:
    status = {"refused": 403, "try_again": 503}.get(outcome, 200)
    return CallRecord(
        at=NOW,
        execution_id="41",
        block=block,
        kind=kind,
        asked={},
        outcome=outcome,
        status=status,
        detail=detail,
    )


def simulated(**given: Any) -> SimulatedRun:
    return SimulatedRun.model_validate(
        {
            "nonce": "sim_1",
            "workflow_id": "copy-1",
            "scenario": "happy_path",
            "issued_at": NOW,
            "execution_id": "41",
            "mode": "manual",
            **given,
        }
    )


def execution(
    status: str,
    ran: Sequence[str],
    failed: str | None = None,
    error: str | None = None,
    block: dict[str, Any] | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        "41",
        "copy-1",
        status,
        "manual",
        None,
        "v1",
        "sim_1",
        failed,
        error,
        {name: "error" if name == failed else "success" for name in ran},
        block,
    )


def reached_the_yes(written: int = 1, approver: str | None = "yes") -> SimulatedRun:
    return simulated(
        proposed=[change()],
        approver=approver,
        woke="delivered" if approver else None,
        would_have_written=written,
    )


def refused_write() -> ExecutionRecord:
    return execution("error", (*UP_TO_ASK, WRITE), WRITE, NEVER_WRITES)


# Happy path


def test_the_happy_path_passes_when_it_reaches_the_yes_with_the_expected_change() -> None:
    plan = planned(release_check())
    graded = grade(plan, staged(plan)["happy_path"], reached_the_yes(), refused_write())
    assert graded.verdict == "passed"
    assert graded.expected == EXPECTED["happy_path"]
    assert graded.happened == (
        "It reached the yes and would have made 1 change, which the simulation refused."
    )
    assert graded.ran == (*UP_TO_ASK, WRITE)


def test_the_happy_path_fails_when_a_block_stops_it_before_the_yes() -> None:
    plan = planned(release_check())
    refused = 'The scenario "happy_path" gives "Compare" no answer.'
    run = simulated(calls=[call("Compare", "agent", "refused", refused)])
    stopped = execution("error", (START, "Read releases", "Compare"), "Compare", refused)
    graded = grade(plan, staged(plan)["happy_path"], run, stopped)
    assert graded.verdict == "failed"
    assert graded.happened == f'"Compare" stopped it: {refused}'


def test_the_happy_path_fails_when_the_change_is_not_the_one_its_block_names() -> None:
    plan = planned(release_check())
    run = simulated(
        proposed=[change(place="OTHER")],
        approver="yes",
        woke="delivered",
        would_have_written=1,
    )
    graded = grade(plan, staged(plan)["happy_path"], run, refused_write())
    assert graded.verdict == "failed"
    assert graded.happened == (
        '"Propose a change" proposed a change in OTHER, but the block names MOCK.'
    )


def test_a_change_named_by_an_expression_is_held_only_to_what_is_written_out() -> None:
    version = release_check()
    for node in version["nodes"]:
        if node["name"] == "Propose a change":
            node["parameters"]["place"] = "={{ $json.project }}"
    plan = planned(version)
    run = simulated(
        proposed=[change(place="ANY")], approver="yes", woke="delivered", would_have_written=1
    )
    assert grade(plan, staged(plan)["happy_path"], run, refused_write()).verdict == "passed"


def test_a_write_with_no_yes_fails_whatever_the_kind() -> None:
    plan = planned(release_check())
    for kind, made in staged(plan).items():
        graded = grade(plan, made, reached_the_yes(approver=None), refused_write())
        assert graded.verdict == "failed", kind
        assert graded.happened == "It asked to make changes with no yes from an Approver."


def test_a_write_that_would_leave_out_a_proposed_change_fails() -> None:
    plan = planned(release_check())
    run = simulated(
        proposed=[change(), change(title="Second")],
        approver="yes",
        woke="delivered",
        would_have_written=1,
    )
    graded = grade(plan, staged(plan)["happy_path"], run, refused_write())
    assert graded.verdict == "failed"
    assert graded.happened == "It would have made 1 of the 2 changes proposed."


def test_a_version_with_no_ask_passes_its_happy_path_by_running_to_the_end() -> None:
    plan = planned(release_check(ask=False, write=False))
    run = simulated(proposed=[change()])
    ended = execution("success", (START, "Read releases", "Compare", "Propose a change"))
    graded = grade(plan, staged(plan)["happy_path"], run, ended)
    assert (graded.verdict, graded.happened) == ("passed", "It ran to the end.")


# Nothing new


def test_nothing_new_passes_when_it_ends_with_nothing_proposed() -> None:
    plan = planned(release_check())
    run = simulated(calls=[call("Read releases", "read", "answered")])
    ended = execution("success", (START, "Read releases"))
    graded = grade(plan, staged(plan)["nothing_new"], run, ended)
    assert graded.verdict == "passed"
    assert graded.happened == "It ended with nothing new and proposed nothing."


def test_nothing_new_fails_when_it_still_reaches_the_yes() -> None:
    plan = planned(release_check())
    graded = grade(plan, staged(plan)["nothing_new"], reached_the_yes(), refused_write())
    assert graded.verdict == "failed"
    assert graded.happened.startswith("It reached the yes")


# Source not found and timeout


def test_source_not_found_passes_when_the_played_read_stops_it_with_a_reason() -> None:
    plan = planned(release_check())
    run = simulated(calls=[call("Read releases", "read", "try_again", SOURCE_NOT_FOUND)] * 2)
    stopped = execution("error", (START, "Read releases"), "Read releases", SOURCE_NOT_FOUND)
    graded = grade(plan, staged(plan)["source_not_found"], run, stopped)
    assert graded.verdict == "passed"
    assert graded.happened == f'"Read releases" stopped it: {SOURCE_NOT_FOUND}'


def test_our_blocks_stop_is_told_in_the_gateways_words() -> None:
    """For an answer to try again, n8n shows only the status our block got, as a live run shows,
    so the words come from the gateway's record."""
    plan = planned(release_check())
    run = simulated(calls=[call("Read releases", "read", "try_again", SOURCE_TIMED_OUT)])
    shown = "Our platform could not do this step (HTTP 503)."
    stopped = execution("error", (START, "Read releases"), "Read releases", shown)
    graded = grade(plan, staged(plan)["timeout"], run, stopped)
    assert (graded.verdict, graded.happened) == (
        "passed",
        f'"Read releases" stopped it: {SOURCE_TIMED_OUT}',
    )


def test_a_stop_somewhere_else_is_not_the_source_not_found() -> None:
    plan = planned(release_check())
    stopped = execution("error", (START, "Read releases", "Compare"), "Compare", "No answer.")
    graded = grade(plan, staged(plan)["source_not_found"], simulated(), stopped)
    assert graded.verdict == "failed"
    assert graded.happened == '"Compare" stopped it: No answer.'


def test_a_timeout_at_mock_github_passes_when_the_troubleshooter_names_the_stop() -> None:
    plan = planned(release_check([github_read()]))
    gone = github_read()
    stopped = execution("error", (START, "GitHub releases"), "GitHub releases", DROPPED, gone)
    graded = grade(plan, staged(plan)["timeout"], simulated(), stopped)
    assert graded.verdict == "passed"
    assert graded.happened.startswith(
        '"GitHub releases" stopped it: GitHub closed the connection, so "GitHub releases" stopped.'
    )


def test_a_timeout_the_troubleshooter_cannot_name_fails() -> None:
    plan = planned(release_check([github_read()]))
    words = "Bad request - please check your parameters"
    stopped = execution(
        "error", (START, "GitHub releases"), "GitHub releases", words, github_read()
    )
    graded = grade(plan, staged(plan)["timeout"], simulated(), stopped)
    assert graded.verdict == "failed"
    assert graded.happened == f'"GitHub releases" stopped it, but not as a slow source: {words}'


def test_our_read_too_slow_passes_with_the_gateways_words() -> None:
    plan = planned(release_check())
    run = simulated(calls=[call("Read releases", "read", "try_again", SOURCE_TIMED_OUT)])
    stopped = execution("error", (START, "Read releases"), "Read releases", SOURCE_TIMED_OUT)
    assert grade(plan, staged(plan)["timeout"], run, stopped).verdict == "passed"


def test_not_found_at_mock_github_passes_with_n8ns_words() -> None:
    plan = planned(release_check([github_read()]))
    words = "The resource you are requesting could not be found"
    stopped = execution(
        "error", (START, "GitHub releases"), "GitHub releases", words, github_read()
    )
    graded = grade(plan, staged(plan)["source_not_found"], simulated(), stopped)
    assert (graded.verdict, graded.happened) == ("passed", f'"GitHub releases" stopped it: {words}')


# Approver says no


def test_approver_says_no_passes_when_it_ends_as_declined_with_nothing_written() -> None:
    plan = planned(release_check())
    run = simulated(proposed=[change()], approver="no", woke="delivered")
    ended = execution("success", (*UP_TO_ASK, "Declined"))
    graded = grade(plan, staged(plan)["approver_says_no"], run, ended)
    assert graded.verdict == "passed"
    assert graded.happened == "It ended as Declined, with nothing written."


def test_approver_says_no_fails_when_the_no_never_reached_n8n() -> None:
    plan = planned(release_check())
    run = simulated(proposed=[change()], approver="no", woke="failed")
    waiting = execution("waiting", UP_TO_ASK)
    graded = grade(plan, staged(plan)["approver_says_no"], run, waiting)
    assert graded.verdict == "failed"
    assert graded.happened == f"It did not end within {WAIT_LIMIT_SECONDS} seconds."


# Odd data


def test_odd_data_passes_when_it_ends_in_any_case_with_a_reason() -> None:
    plan = planned(release_check())
    odd = staged(plan)["odd_data"]
    assert grade(plan, odd, reached_the_yes(), refused_write()).verdict == "passed"
    refused = 'The input "release" is over 8 KB.'
    stopped = execution("error", (START, "Read releases", "Compare"), "Compare", refused)
    assert grade(plan, odd, simulated(), stopped).verdict == "passed"
    ended = execution("success", (START, "Read releases"))
    assert grade(plan, odd, simulated(), ended).verdict == "passed"


def test_odd_data_fails_on_a_failure_with_no_reason() -> None:
    plan = planned(release_check([our_read(), tidy()]))
    odd = staged(plan)["odd_data"]
    words = "Cannot read properties of undefined (reading 'tag')"
    failed = execution("error", (START, "Read releases", "Tidy"), "Tidy", words)
    graded = grade(plan, odd, simulated(), failed)
    assert graded.verdict == "failed"
    assert graded.happened == f'It failed at "Tidy", which is not a stop with a reason: {words}'
    crashed = grade(plan, odd, simulated(), execution("crashed", (START,)))
    assert (crashed.verdict, crashed.happened) == ("failed", "n8n crashed while it ran.")
    silent = grade(plan, odd, simulated(), execution("error", (START, "Tidy"), "Tidy"))
    assert silent.happened == 'It failed at "Tidy" with no words for why.'


def test_odd_data_fails_when_a_read_block_throws_on_it() -> None:
    """A read block that throws on the odd data it got is a failure the troubleshooter can't
    name, not a stop with a reason."""
    plan = planned(release_check([github_read()]))
    odd = staged(plan)["odd_data"]
    words = "Cannot read properties of undefined (reading 'tag_name')"
    threw = execution("error", (START, "GitHub releases"), "GitHub releases", words, github_read())
    graded = grade(plan, odd, simulated(), threw)
    assert graded.verdict == "failed"
    assert graded.happened == (
        f'It failed at "GitHub releases", which is not a stop with a reason: {words}'
    )


def test_odd_data_passes_on_a_stop_the_troubleshooter_names() -> None:
    plan = planned(release_check([github_read()]))
    odd = staged(plan)["odd_data"]
    named = execution(
        "error", (START, "GitHub releases"), "GitHub releases", DROPPED, github_read()
    )
    assert grade(plan, odd, simulated(), named).verdict == "passed"


# What was not tried


def test_a_pinned_block_never_counts_as_run() -> None:
    plan = planned(release_check([jira_read(), our_read()]))
    ran = (START, "Read the issue", "Read releases", "Compare", "Propose a change")
    ended = execution("error", (*ran, "Ask for a yes", WRITE), WRITE, NEVER_WRITES)
    graded = grade(plan, staged(plan)["happy_path"], reached_the_yes(), ended)
    assert graded.verdict == "passed"
    assert "Read the issue" not in graded.ran


def test_a_scenario_no_block_can_play_is_not_tried() -> None:
    plan = planned(release_check([jira_read()]))
    graded = not_tried(staged(plan)["timeout"])
    assert (graded.verdict, graded.kind) == ("not_tried", "timeout")
    assert graded.happened == "No block here can play this case, so it was not tried."
    assert graded.not_tried == staged(plan)["timeout"].not_tried


def test_coverage_names_what_no_scenario_reached_and_what_was_not_tried() -> None:
    plan = planned(release_check([jira_read(), our_read()]))
    made = staged(plan)
    happy = grade(plan, made["happy_path"], reached_the_yes(), refused_write())
    no = grade(
        plan,
        made["approver_says_no"],
        simulated(proposed=[change()], approver="no", woke="delivered"),
        execution("success", (*UP_TO_ASK, "Declined")),
    )
    found = coverage(plan, [happy, no], KINDS)
    assert found.not_reached == ("No answer", "Nothing to change")
    pinned = next(b for b in plan.blocks if b.name == "Read the issue")
    assert found.not_tried == (
        NotTried("Read the issue", str(pinned.why)),
        NotTried("Tell", AFTER_WRITE),
    )
    assert found.kinds_without_a_scenario == (
        "nothing_new",
        "source_not_found",
        "timeout",
        "odd_data",
    )
