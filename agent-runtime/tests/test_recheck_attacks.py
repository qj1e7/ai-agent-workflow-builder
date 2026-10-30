"""The PR #70 recheck's fresh attempts: writes the word lists lack, other languages, look-alike
letters, split letters, prefixes, other systems, fixed values from the wrong clause, and honest
reads the earlier rules refused. "Understood" is earned, so none of these is understood, and no
honest read is can't do."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.abilities import CAN, RowAnswer
from agent_runtime.contract import Understood, UnderstoodRow
from agent_runtime.planner import (
    CHECK,
    OWN_WORDS_UNKNOWN,
    READ_IN,
    UnderstandAnswer,
    understood_of,
)

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "cases" / "recheck_attacks.json").read_text(encoding="utf-8")
)
DO_THIS = f"I can't do this yet. {CAN}"


def wanted(state: str) -> list[dict[str, Any]]:
    return [c for c in CASES if c["wanted"] == state]


def shown(case: dict[str, Any], projects: list[str] | None) -> UnderstoodRow:
    answer = RowAnswer.model_validate(case["row"])
    read = UnderstandAnswer(belongs_on_watchlist=False, rows=[answer])
    result = understood_of(read, case["task"], projects)
    assert isinstance(result, Understood)
    return next(r for r in result.rows if r.kind == answer.kind)


def asks_to_check(row: UnderstoodRow) -> bool:
    return row.state == "changed" and (row.note == READ_IN or (row.note or "").endswith(CHECK))


def test_the_cases_are_the_rechecks_fresh_attempts():
    assert len(CASES) == 101
    assert {c["wanted"] for c in CASES} == {"cant_do", "honest", "judge"}


@pytest.mark.parametrize("with_list", [True, False], ids=["list", "no-list"])
@pytest.mark.parametrize("case", wanted("cant_do"), ids=[c["id"] for c in wanted("cant_do")])
def test_a_write_or_another_system_is_never_understood(case: dict[str, Any], with_list: bool):
    row = shown(case, case["projects"] if with_list else None)
    assert row.state == "cant_do" or asks_to_check(row), (row.state, row.text, row.note)


@pytest.mark.parametrize("case", wanted("honest"), ids=[c["id"] for c in wanted("honest")])
def test_an_honest_read_is_understood_or_asks_to_check_never_cant_do(case: dict[str, Any]):
    row = shown(case, case["projects"])
    assert row.state == "understood" or asks_to_check(row), (row.state, row.text, row.note)
    if case["text"] is not None:
        assert row.text == case["text"]


@pytest.mark.parametrize("case", wanted("judge"), ids=[c["id"] for c in wanted("judge")])
def test_a_fixed_value_from_the_wrong_clause_is_never_understood(case: dict[str, Any]):
    row = shown(case, case["projects"])
    assert row.state != "understood", (row.text, row.note)


def test_a_cant_do_note_never_repeats_an_order_as_a_system():
    case = next(c for c in CASES if c["id"] == "j02-source-is-an-order")
    assert shown(case, case["projects"]).note == DO_THIS


def test_a_cant_do_row_shows_only_the_tasks_own_words():
    case = next(c for c in CASES if c["id"] == "j03-said-not-in-task")
    assert shown(case, case["projects"]).text == OWN_WORDS_UNKNOWN
