"""A workflow reads Needs you for a person exactly when that person's Home has a row for it."""

from types import SimpleNamespace
from typing import Any, cast

from platform_api.orchestration.person_runs import PersonRuns, workflows_needing_you
from platform_api.shared import UseCaseId


def row(use_case_id: str) -> Any:
    return SimpleNamespace(run=SimpleNamespace(use_case_id=UseCaseId(use_case_id)))


def runs(
    asks: tuple[str, ...] = (),
    waiting: tuple[str, ...] = (),
    stopped: tuple[str, ...] = (),
    declined: tuple[str, ...] = (),
    questions: tuple[str, ...] = (),
) -> PersonRuns:
    return PersonRuns(
        tuple(row(u) for u in asks),
        tuple(row(u) for u in waiting),
        tuple(row(u) for u in stopped),
        tuple(row(u) for u in declined),
        tuple(row(u) for u in questions),
    )


def test_every_row_home_lists_for_a_workflow_makes_it_need_you():
    found = workflows_needing_you(
        runs(asks=("a",), stopped=("s",), declined=("d",), questions=("q",))
    )
    assert found == {"a": "approval", "s": "stopped", "d": "declined", "q": "question"}


def test_a_workflow_waiting_on_someone_else_is_not_needs_you():
    assert workflows_needing_you(runs(waiting=("w",))) == {}


def test_one_reason_per_workflow_with_the_yes_first():
    found = workflows_needing_you(runs(asks=("x",), stopped=("x",), declined=("x",)))
    assert found == {"x": "approval"}
    assert workflows_needing_you(runs(stopped=("x",), declined=("x",), questions=("x",))) == {
        "x": "stopped"
    }


def test_the_set_equals_the_use_cases_in_home_lists():
    person = runs(
        asks=("a",), stopped=("s", "p"), declined=("d",), questions=("q",), waiting=("w",)
    )
    home = {
        r.run.use_case_id
        for r in (*person.asks, *person.stopped, *person.declined, *person.questions)
    }
    assert set(cast(dict[str, str], workflows_needing_you(person))) == home
