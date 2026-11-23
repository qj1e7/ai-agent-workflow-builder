"""A workflow that can't run is in Needs you for everyone: one rule for the pill and Home's row."""

from typing import Any

from platform_api.builder.home import fix_items
from platform_api.builder.models import UseCaseView, fix_of
from platform_api.contracts.stories import USE_CASE


def case(**change: Any) -> UseCaseView:
    return USE_CASE.model_copy(update={"state": "on", "grade": None, "move_refused": None, **change})


def test_a_version_that_needs_a_fix_or_has_its_writes_refused_needs_the_person():
    assert fix_of(case(grade="needs_a_fix")) == "needs_a_fix"
    assert fix_of(case(grade="writes_refused")) == "writes_refused"


def test_a_workflow_that_could_not_move_to_n8n_needs_the_person():
    assert fix_of(case(move_refused="It could not move.")) == "not_moved"


def test_a_safe_workflow_does_not():
    assert fix_of(case(grade="safe")) is None
    assert fix_of(case()) is None


def test_only_a_workflow_that_is_on_counts():
    assert fix_of(case(state="paused", grade="needs_a_fix")) is None
    assert fix_of(case(state="draft", grade="needs_a_fix")) is None


def test_home_lists_exactly_the_workflows_the_rule_names():
    on_fix = case(use_case_id="uc_a", name="A", grade="needs_a_fix")
    refused = case(use_case_id="uc_b", name="B", grade="writes_refused")
    fine = case(use_case_id="uc_c", name="C")
    paused = case(use_case_id="uc_d", name="D", state="paused", grade="needs_a_fix")
    items = fix_items([on_fix, refused, fine, paused])
    assert [(i.use_case_id, i.use_case_name, i.why) for i in items] == [
        ("uc_a", "A", "needs_a_fix"),
        ("uc_b", "B", "writes_refused"),
    ]
