"""A workflow that can't run is in Needs you only for who has a button for it, in one rule."""

from typing import Any

from platform_api.builder.home import fix_items
from platform_api.builder.models import UseCaseView, fix_of
from platform_api.builder.planner_facts import needs_you_fact
from platform_api.contracts.home_stories import DAY_ONE
from platform_api.contracts.stories import USE_CASE


def case(**change: Any) -> UseCaseView:
    return USE_CASE.model_copy(
        update={"state": "on", "grade": None, "move_refused": None, **change}
    )


def test_a_version_that_needs_a_fix_is_for_everyone_because_explain_opens_for_all():
    for operator in (True, False):
        assert fix_of(case(grade="needs_a_fix"), operator) == "needs_a_fix"


def test_refused_writes_are_for_an_operator_only_who_can_add_the_yes_back():
    assert fix_of(case(grade="writes_refused"), True) == "writes_refused"
    assert fix_of(case(grade="writes_refused"), False) is None


def test_a_workflow_that_could_not_move_has_no_button_so_it_is_not_needs_you():
    for operator in (True, False):
        assert fix_of(case(move_refused="It could not move."), operator) is None


def test_a_safe_workflow_does_not():
    assert fix_of(case(grade="safe"), True) is None
    assert fix_of(case(), True) is None


def test_only_a_workflow_that_is_on_counts():
    assert fix_of(case(state="paused", grade="needs_a_fix"), True) is None
    assert fix_of(case(state="draft", grade="needs_a_fix"), True) is None


def test_home_lists_exactly_the_workflows_the_rule_names_for_that_person():
    on_fix = case(use_case_id="uc_a", name="A", grade="needs_a_fix")
    refused = case(use_case_id="uc_b", name="B", grade="writes_refused")
    fine = case(use_case_id="uc_c", name="C")
    paused = case(use_case_id="uc_d", name="D", state="paused", grade="needs_a_fix")
    views = [on_fix, refused, fine, paused]
    assert [(i.use_case_id, i.why) for i in fix_items(views, True)] == [
        ("uc_a", "needs_a_fix"),
        ("uc_b", "writes_refused"),
    ]
    assert [(i.use_case_id, i.why) for i in fix_items(views, False)] == [("uc_a", "needs_a_fix")]


def test_the_chat_counts_a_fix_row_as_home_does():
    quiet = needs_you_fact(DAY_ONE)
    fix = case(grade="needs_a_fix")
    home = DAY_ONE.model_copy(update={"fixes": fix_items([fix], True)})
    fact = needs_you_fact(home)
    assert fact.fixes == 1
    assert fact.total == quiet.total + 1
    parts = fact.model_dump(exclude={"total"})
    assert sum(parts.values()) == fact.total, f"every part of the total is named: {parts}"
