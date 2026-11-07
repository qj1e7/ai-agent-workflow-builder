"""The word helpers the Planner answer shares: hidden characters, watchlist words, row order."""

import pytest

from agent_runtime.contract import RowKind, RowState, UnderstoodRow
from agent_runtime.planner import (
    MAX_ROWS,
    arrange,
    plain,
    task_form_of,
    visible_words,
    whole_word_of,
)

RELEASE_TASK = "Tell me when LangGraph has a new release"
FOLLOW_UP_TASK = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)


def row(kind: RowKind, text: str, state: RowState = "understood", note: str | None = None):
    return UnderstoodRow(kind=kind, text=text, state=state, note=note)


def test_nul_control_and_zero_width_characters_are_dropped_and_the_spaces_made_plain():
    assert plain("Every\x00 weekday​ at 3pm\x07", 200) == "Every weekday at 3pm"
    assert plain("Bug\ttickets\nin MOCK‮", 200) == "Bug tickets in MOCK"
    assert visible_words("Jira⁠ project MOCK﻿") == "Jira project MOCK"


@pytest.mark.parametrize(
    "mark",
    [
        "͏",
        "︀",
        "️",
        "\U000e0100",
        "\U000e01ef",
        "ㅤ",
        "ᅟ",
        "ᅠ",
        "ﾠ",
        "⠀",
        "᠋",
        "឴",
    ],
)
def test_invisible_marks_never_reach_the_portal(mark: str):
    assert plain(f"Bug tickets{mark} in MOCK", 200) == "Bug tickets in MOCK"


def test_text_is_cut_at_the_limit_with_an_ellipsis():
    assert plain("x" * 300, 200) == "x" * 199 + "…"


@pytest.mark.parametrize(
    ("said", "task", "word"),
    [
        ("Release", RELEASE_TASK, "release"),
        ("releases", RELEASE_TASK, "release"),
        ("vulnerability", "Warn me about vulnerabilities in Log4j", "vulnerabilities"),
        ("version", "Is our FastAPI version behind", "version"),
        ("releases", "Tell me about new Redis releases", "releases"),
        ("upgrade", "Tell me when Redis is upgraded", "upgraded"),
        ("patch", "Tell me when Log4j is patched", "patched"),
        ("vulnerable", "Is Log4j vulnerable", "vulnerable"),
        ("newer version", "Is there a newer version of FastAPI", "version"),
        ("new release", RELEASE_TASK, "release"),
        ("security patches", "Tell me about Log4j security patches", "security patches"),
        ("version or release", "Tell me about each new release of Redis", "release"),
        ("version", "Our versioned docs need the new version of FastAPI", "version"),
        ("versions", "Our versioned docs need the new version of FastAPI", "version"),
        ("release", "The released notes list every new release", "release"),
        ("patch", "A patching window for the new patch of Log4j", "patch"),
        ("release​", RELEASE_TASK, "release"),
    ],
)
def test_the_watchlist_word_is_the_one_the_task_wrote(said: str, task: str, word: str):
    assert task_form_of(task, said) == word


@pytest.mark.parametrize(
    ("said", "task"),
    [
        ("upgrade", RELEASE_TASK),
        ("tickets", FOLLOW_UP_TASK),
        ("bug", FOLLOW_UP_TASK),
        ("a", "Every Monday at 9am, check the tickets"),
        ("LangGraph", RELEASE_TASK),
        (None, RELEASE_TASK),
    ],
)
def test_a_word_outside_the_watchlist_words_the_task_holds_is_none(said: str | None, task: str):
    assert task_form_of(task, said) is None


@pytest.mark.parametrize(
    ("software", "task", "shown"),
    [
        ("Go", "Tell me when Google has a new release", None),
        ("a", "Tell me about the new release", None),
        ("Lang", RELEASE_TASK, None),
        ("go", "Tell me when Go has a new release", "Go"),
        ("langgraph", RELEASE_TASK, "LangGraph"),
        ("Lang​Graph", RELEASE_TASK, "LangGraph"),
    ],
)
def test_the_software_is_a_whole_word_of_the_task(software: str, task: str, shown: str | None):
    assert whole_word_of(task, software) == shown


def test_one_schedule_row_is_kept_and_at_most_eight_rows_keeping_cant_do_parts():
    rows = [
        row("schedule", "Every Monday"),
        row("schedule", "Every Tuesday"),
        row("look_for", "Tickets"),
        *[row("do", f"Create ticket {n}") for n in range(6)],
        row("where", "Jira project MOCK"),
        row("do", "Delete them all", "cant_do", "No tool deletes tickets."),
    ]
    arranged = arrange(rows)
    assert len(arranged) == MAX_ROWS == 8
    assert [r.text for r in arranged if r.kind == "schedule"] == ["Every Monday"]
    assert any(r.state == "cant_do" for r in arranged)


def test_a_part_left_out_is_shown_as_missing_and_the_rows_keep_their_order():
    arranged = arrange([row("where", "Jira project MOCK"), row("do", "Create one ticket")])
    assert [(r.kind, r.state) for r in arranged] == [
        ("schedule", "missing"),
        ("look_for", "missing"),
        ("do", "understood"),
        ("where", "understood"),
    ]
