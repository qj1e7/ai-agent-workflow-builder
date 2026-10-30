"""The P70 checker's attempts: a fooled model sneaking a write, another system or a misleading
row through the checked parameters, and honest sponsor reads that must still read true."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.abilities import CAN, RowAnswer
from agent_runtime.contract import Understood, UnderstoodRow
from agent_runtime.planner import UnderstandAnswer, understood_of

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "cases" / "checker_attacks.json").read_text(encoding="utf-8")
)
SPONSOR_PROJECTS = ("MOCK", "ACCESS", "OPS", "SEC", "ADMIN")
ASKS = ("Please check how I read it.", "Please check it.")


def flat(text: str | None) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return "".join(c for c in folded if unicodedata.category(c) != "Cf").casefold()


def shown(case: dict[str, Any], projects: tuple[str, ...] | None) -> list[UnderstoodRow]:
    answer = UnderstandAnswer.model_validate({"belongs_on_watchlist": False, "rows": case["rows"]})
    result = understood_of(answer, case["task"], projects)
    assert isinstance(result, Understood)
    return result.rows


def wanted(state: str) -> list[dict[str, Any]]:
    return [c for c in CASES if c["wanted"] == state]


def test_the_cases_are_the_checkers_attempts():
    assert len(CASES) == 81
    assert {c["wanted"] for c in CASES} == {"cant_do", "understood", "changed"}


@pytest.mark.parametrize("projects", [None, SPONSOR_PROJECTS], ids=["no-list", "sponsor-list"])
@pytest.mark.parametrize("case", wanted("cant_do"), ids=[c["id"] for c in wanted("cant_do")])
def test_an_attack_is_cant_do_and_shows_only_the_tasks_own_words(
    case: dict[str, Any], projects: tuple[str, ...] | None
):
    rows = shown(case, projects)
    looks = [flat(w) for w in case["look"]]
    accepted = [r for r in rows if r.state in ("understood", "changed")]
    assert [r for r in accepted if any(w in flat(f"{r.text} {r.note}") for w in looks)] == []
    mine = [r for r in rows if r.kind == case["kind"]]
    if looks:
        assert any(r.state == "cant_do" and any(w in flat(r.text) for w in looks) for r in rows)
    else:
        assert mine and all(r.state == "cant_do" for r in mine)
    if case["text"] is not None:
        assert [r.text for r in mine if r.state == "cant_do"] == [case["text"]]
    task = flat(case["task"])
    assert all(flat(r.text) in task or r.text == "This part of your task" for r in mine)


@pytest.mark.parametrize("case", wanted("understood"), ids=[c["id"] for c in wanted("understood")])
def test_an_honest_read_is_understood_in_the_platforms_own_words(case: dict[str, Any]):
    rows = shown(case, SPONSOR_PROJECTS)
    mine = [(r.text, r.state, r.note) for r in rows if r.kind == case["kind"]]
    assert (case["text"], "understood", None) in mine


@pytest.mark.parametrize("case", wanted("understood"), ids=[c["id"] for c in wanted("understood")])
def test_with_no_project_list_an_honest_read_that_names_a_key_is_changed(case: dict[str, Any]):
    row = next(r for r in shown(case, None) if r.kind == case["kind"] and r.text == case["text"])
    keys = [k for k in SPONSOR_PROJECTS if re.search(rf"\b{k}\b", case["text"])]
    if keys:
        note = f"I can't check that {keys[0]} is a Jira project. Please check how I read it."
        assert (row.state, row.note) == ("changed", note)
    else:
        assert (row.state, row.note) == ("understood", None)


@pytest.mark.parametrize("case", wanted("changed"), ids=[c["id"] for c in wanted("changed")])
def test_a_reading_the_platform_cannot_check_is_changed_and_asks_to_check_it(
    case: dict[str, Any],
):
    rows = shown(case, SPONSOR_PROJECTS)
    mine = [r for r in rows if r.kind == case["kind"] and r.text == case["text"]]
    assert mine and all(r.state == "changed" and (r.note or "").endswith(ASKS) for r in mine)


NAMES = {
    "latin-accents": "José",
    "vietnamese": "Nguyễn",
    "greek": "Νίκος",
    "cyrillic": "Дмитрий",
    "chinese": "王小明",
    "japanese": "さくら",
    "korean": "김민준",
    "arabic": "فاطمة",
    "hebrew": "דוד",
    "tamil": "முருகன்",
    "hindi": "राजेश",
    "thai": "สมชาย",
    "malay-jawi": "عبدالله",
    "apostrophe": "O’Brien",
    "hyphen": "Mary-Jane",
}


def search(task: str, **parameters: Any) -> UnderstoodRow:
    rows = [
        RowAnswer(
            kind="schedule", state="understood", ability="run_on_a_schedule", every=["friday"]
        ),
        RowAnswer.model_validate(
            {
                "kind": "look_for",
                "state": "understood",
                "ability": "read_jira_tickets",
                **parameters,
            }
        ),
    ]
    result = understood_of(UnderstandAnswer(belongs_on_watchlist=False, rows=rows), task, ("MOCK",))
    assert isinstance(result, Understood)
    return next(r for r in result.rows if r.kind == "look_for")


@pytest.mark.parametrize("name", NAMES.values(), ids=NAMES.keys())
def test_a_name_in_any_script_comes_back_whole(name: str):
    task = f"Every Friday find bug tickets in MOCK assigned to {name} and create one ticket"
    person = search(task, ticket_type="bug", project="MOCK", assigned_to=name)
    assert (person.state, person.text) == ("understood", f"Bug tickets in MOCK assigned to {name}")
    task = f"Every Friday find tickets about the {name} migration in the {name} Tools project"
    topic = search(task, about=f"the {name} migration", project_name=f"{name} Tools")
    assert (topic.state, topic.text, topic.note) == (
        "changed",
        f"Tickets in the {name} Tools project about “the {name} migration”",
        f"I can't check that the {name} Tools project is in Jira. Please check how I read it.",
    )
    task = f"Every Friday find {name}'s stale tickets in MOCK"
    said = f"{name}'s stale tickets"
    changed = search(task, state="changed", said=said, project="MOCK", no_update_days=14)
    assert changed.note == f"You said “{said}”. Please check how I read it."
    task = f"Every Friday list who has admin access in {name} Cloud"
    cant = search(task, said=f"who has admin access in {name} Cloud", source=f"{name} Cloud")
    assert (cant.state, cant.text, cant.note) == (
        "cant_do",
        f"Who has admin access in {name} Cloud",
        f"I can't read {name} Cloud yet. {CAN}",
    )
