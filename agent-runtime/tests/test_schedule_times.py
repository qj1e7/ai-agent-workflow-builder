"""A time the person writes stays on the schedule row, on the 24-hour clock too, so the card
never asks for it again. A row that lost a time someone wrote is never marked understood: the
card asks for the time and never guesses one. Two times, or a range of times, are asked for,
never read as one (principle 4)."""

import pytest

from agent_runtime.answers import answer_of, parts_of
from agent_runtime.contract import CantAnswer, RequestPart, SetupCardAnswer, UnderstoodRow
from agent_runtime.reading import (
    NO_TIME_READ,
    NOT_A_RUN_TIME,
    ONE_TIME,
    DaysRead,
    PlaceRead,
    SearchRead,
    TicketRead,
    said_schedule,
    time_ranges,
)
from tests.test_answers import read

CAROL = (
    "Every Friday at 16:00, find Jira tickets in project MOCK that nobody updated for 14 days, "
    "and raise one Jira ticket in MOCK that lists them"
)


def carols_card(schedule: str, said: str) -> tuple[UnderstoodRow, list[RequestPart]]:
    """The schedule row and the parts for Carol's request with their schedule written as said,
    when the model reads the schedule as schedule."""
    task = read(
        name="Stale MOCK ticket list",
        schedule=schedule,
        search=SearchRead(
            project="MOCK",
            updated=DaysRead(how="before", days=14),
            said="Jira tickets in project MOCK that nobody updated for 14 days",
        ),
        ticket=TicketRead(creates=True, says="list", said="lists them"),
        place=PlaceRead(project="MOCK", said="raise one Jira ticket in MOCK"),
    )
    text = CAROL.replace("Every Friday at 16:00", said)
    answer = answer_of(task, text)
    card = answer.alternative if isinstance(answer, CantAnswer) else answer
    assert isinstance(card, SetupCardAnswer)
    return card.rows[0], parts_of(task, text, answer)


def carols_row(schedule: str, said: str) -> UnderstoodRow:
    return carols_card(schedule, said)[0]


def test_carols_24_hour_time_stays_on_her_schedule_row():
    row = carols_row("Every Friday at 16:00", "Every Friday at 16:00")
    assert (row.kind, row.text, row.state) == ("schedule", "Every Friday at 16:00", "understood")


@pytest.mark.parametrize("at", ["16:00", "00:00", "0:30", "23:59", "7:05", "4pm", "9.30am"])
def test_a_time_the_clock_reads_stays_on_the_row(at: str):
    said = f"Every Friday at {at}"
    row = carols_row(said, said)
    assert (row.text, row.state) == (said, "understood")


@pytest.mark.parametrize("at", ["24:00", "25:00", "7:5", "1600", "16.00", "nine"])
def test_a_time_the_clock_cant_read_is_asked_for_and_her_day_stays(at: str):
    """A dotted time is asked, as an edit asks "at 9.30": it could be morning or evening."""
    said = f"Every Friday at {at}"
    row = carols_row(said, said)
    assert (row.text, row.state, row.note) == ("Every Friday", "missing", NO_TIME_READ)


@pytest.mark.parametrize(
    "model",
    ["Every Friday 8.30am", "Every Friday 9.15am", "Every Friday at 8.30am", "Every Friday 8:30am"],
)
def test_a_dotted_time_they_never_said_is_never_shown_and_their_own_stays(model: str):
    """The model's "8.30am" against her "9.30am" was checked only as "30am", so the card took
    08:30 as their time. Then the card asked for a time, with a note that said their words had
    none."""
    row = carols_row(model, "Every Friday 9.30am")
    assert (row.text, row.state, row.note) == ("Every Friday 9.30am", "understood", None)


def test_her_own_dotted_time_with_no_at_stays_on_the_row():
    row = carols_row("Every Friday 9.30am", "Every Friday 9.30am")
    assert (row.text, row.state) == ("Every Friday 9.30am", "understood")


def test_a_row_that_lost_its_time_never_keeps_a_dangling_at():
    """The words "16h00" are a part the Planner did not follow, crossed on the card."""
    row = carols_row("Every Friday at 16h00", "Every Friday at 16h00")
    assert (row.text, row.state, row.note) == ("Every Friday", "missing", NO_TIME_READ)


def test_a_day_the_model_guessed_never_stays_on_a_row_that_lost_its_time():
    task = read(schedule="Every Monday at", search=SearchRead(said="tickets"))
    answer = answer_of(task, "Each week at 24:00, list tickets")
    assert isinstance(answer, SetupCardAnswer)
    assert (answer.rows[0].text, answer.rows[0].state) == ("", "missing")


@pytest.mark.parametrize(
    ("words", "at"),
    [
        ("Fridays at 16:00", "16:00"),
        ("Fridays at 0:00", "00:00"),
        ("Fridays at 4pm", "16:00"),
        ("Fridays at 16.00", None),
        ("Fridays at 24:00", None),
        ("Fridays at 7:5", None),
    ],
)
def test_a_new_schedule_reads_only_a_real_24_hour_time(words: str, at: str | None):
    """Before, "24:00" was read as a time, which the schedule's own check then refused."""
    assert said_schedule(words) == ("friday", at)


def test_a_card_that_asks_its_time_and_its_days_is_still_offered():
    """The schedule asks only its time, so it is still a part the card holds beside a search
    that asks how many days, and the email part's cross offers the card."""
    task = "Every Friday at 24:00, email me the list of stale tickets in MOCK"
    fields = read(
        name="Stale ticket list",
        schedule="Every Friday at 24:00",
        search=SearchRead(project="MOCK", said="stale tickets in MOCK"),
    )
    answer = answer_of(fields, task)
    assert isinstance(answer, CantAnswer) and isinstance(answer.alternative, SetupCardAnswer)
    assert [(p.mark, p.reason) for p in parts_of(fields, task, answer)] == [
        ("will_do", None),
        ("cant", "cant_do"),
        ("question", "how_many_days"),
    ]


@pytest.mark.parametrize(
    ("said", "model"),
    [
        ("Every Friday at 16:00", "Every Friday"),
        ("Every Friday at 16:00", "Every Friday at"),
        ("Every Friday at 16:00", "Every Friday at 4pm"),
        ("Every Friday at 16:00", "Every Friday at 17:00"),
        ("Every Friday at 16:00", "Every Friday at 16.00"),
        ("Every Friday at 4pm", "Every Friday"),
        ("Every Friday at noon", "Every Friday"),
        ("Every Friday at 9", "Every Friday"),
        ("At 16:00 every Friday", "Every Friday"),
    ],
)
def test_a_time_the_model_drops_or_changes_is_read_from_their_words(said: str, model: str):
    """Code reads their time, so the card never says it couldn't read one, or that their words
    had none. A time the model wrote in its place is never shown."""
    row = carols_row(model, said)
    assert (row.text, row.state, row.note) == (said, "understood", None)


def test_their_time_never_stands_beside_a_day_the_model_guessed():
    """Their own words come back whole, so the card asks which day, never Monday."""
    task = read(schedule="Every Monday", search=SearchRead(said="tickets"))
    answer = answer_of(task, "Each week at 16:00, list tickets")
    assert isinstance(answer, SetupCardAnswer)
    assert (answer.rows[0].text, answer.rows[0].state) == ("Each week at 16:00", "understood")


@pytest.mark.parametrize(
    "model", ["Every Monday at 9am", "Every Monday", "Every Monday at 16:00", "Fridays at 9am"]
)
def test_a_day_or_time_the_model_contradicts_never_mixes_with_theirs(model: str):
    """Before, "Every Monday at 16:00" came back, which the Portal set as asked for."""
    row = carols_row(model, "Every Friday at 16:00")
    assert (row.text, row.state, row.note) == ("Every Friday at 16:00", "understood", None)


@pytest.mark.parametrize(
    "model", ["Every Friday morning", "Every Friday at 4pm and 5pm", "Every Friday at 4pm or so"]
)
def test_the_models_extra_words_never_garble_their_time(model: str):
    """Before, these came back as a note that their words had no time, "Every Friday and at
    4pm", or "Every Friday at 4pm or"."""
    row = carols_row(model, "Every Friday at 4pm")
    assert (row.text, row.state, row.note) == ("Every Friday at 4pm", "understood", None)


@pytest.mark.parametrize(
    ("said", "model", "bound"),
    [
        ("Every Friday before 5pm", "Every Friday at 4pm", "before 5pm"),
        ("Every Friday before 5pm", "Every Friday", "before 5pm"),
        ("Every Friday by 5pm", "Every Friday", "by 5pm"),
        ("Every Friday by 5pm", "Every Friday 5pm", "by 5pm"),
        ("Every Friday after 9am", "Every Friday at 10am", "after 9am"),
        ("Every Friday around 4pm", "Every Friday at 4pm", "around 4pm"),
        ("Every Friday until 17:00", "Every Friday", "until 17:00"),
    ],
)
def test_a_bound_on_the_time_is_never_taken_as_the_time_it_runs(said: str, model: str, bound: str):
    """A run at 5pm is not before 5pm, so the card asks the time and says why. Before, the row
    was "Every Friday 5pm", which the Portal set as asked for."""
    row = carols_row(model, said)
    assert (row.text, row.state, row.note) == (
        "Every Friday",
        "missing",
        NOT_A_RUN_TIME.format(bound),
    )


@pytest.mark.parametrize("words", ["Fridays before 5pm", "Fridays by 5pm", "Fridays after 9am"])
def test_a_new_schedule_never_takes_a_bound_as_its_time(words: str):
    assert said_schedule(words) == ("friday", None)


@pytest.mark.parametrize(
    ("said", "model"),
    [
        ("Every Friday 16.00", "Every Friday at 4pm"),
        ("Every Friday at 9.30", "Every Friday at 9:30am"),
    ],
)
def test_a_time_code_cant_read_says_so_when_the_model_writes_another(said: str, model: str):
    """Before, the note said their words had no time."""
    row = carols_row(model, said)
    assert (row.text, row.state, row.note) == ("Every Friday", "missing", NO_TIME_READ)


@pytest.mark.parametrize(
    "words",
    [
        "between 10 and 14 days",
        "from 10 to 14 days",
        "between 2 and 3 approvers",
        "at 9am - 20 tickets max",
        "at 9am to 3 managers",
        "between 30 and 40",
    ],
)
def test_counts_are_no_range_of_times(words: str):
    assert time_ranges(words) == []


def test_a_day_count_beside_the_schedule_is_never_asked_as_a_time():
    """Before, "10 and 14" was offered as two times."""
    task = read(
        name="Idle tickets",
        schedule="Every Friday",
        search=SearchRead(project="MOCK", said="tickets in MOCK idle between 10 and 14 days"),
    )
    text = "Find tickets in MOCK idle between 10 and 14 days every Friday"
    answer = answer_of(task, text)
    assert not any(p.reason == "one_time" for p in parts_of(task, text, answer))
    assert said_schedule("Every Friday at 9am - 20 tickets max") == ("friday", "09:00")
    assert said_schedule("Every Friday between 10 and 14 days") == ("friday", None)
    row, parts = carols_card("Every Friday at 9am", "Every Friday at 9am - 20 tickets max -")
    assert (row.text, row.state) == ("Every Friday at 9am", "understood")
    assert not any(p.reason == "one_time" for p in parts)


RANGES = [
    ("Every Friday between 16:00 and 17:00", "Every Friday at 16:00", ("16:00", "17:00")),
    ("Every Friday between 16:00 and 17:00", "Every Friday 16:00", ("16:00", "17:00")),
    ("Every Friday between 16:00 and 17:00", "Every Friday", ("16:00", "17:00")),
    (
        "Every Friday between 16:00 and 17:00",
        "Every Friday between 16:00 and 17:00",
        ("16:00", "17:00"),
    ),
    ("Every Friday from 16:00 to 17:00", "Every Friday at 16:00", ("16:00", "17:00")),
    ("Every Friday 16:00-17:00", "Every Friday at 16:00", ("16:00", "17:00")),
    ("Every Friday at 16:00 until 17:00", "Every Friday at 16:00", ("16:00", "17:00")),
    ("Every Friday at 16:00 till 17:00", "Every Friday at 16:00", ("16:00", "17:00")),
    ("Every Friday between 4pm and 5pm", "Every Friday at 4pm", ("4pm", "5pm")),
    ("Every Friday 9am-5pm", "Every Friday at 9am", ("9am", "5pm")),
    ("Every Friday from 4 to 5pm", "Every Friday at 5pm", ("4", "5pm")),
    ("Every Friday at 4-5pm", "Every Friday at 5pm", ("4", "5pm")),
]


@pytest.mark.parametrize(("said", "model", "choices"), RANGES)
def test_two_times_or_a_range_are_asked_for_never_read_as_one(
    said: str, model: str, choices: tuple[str, str]
):
    """The schedule runs at one time, so the card asks which, with their two times as the
    choices, and neither is picked for them. No part of their words is left unmarked."""
    row, parts = carols_card(model, said)
    assert (row.text, row.state) == ("", "missing")
    assert row.note == ONE_TIME.format(" and ".join(f'"{c}"' for c in choices))
    assert [(p.reason, p.choices) for p in parts if p.mark == "cant"] == [
        ("one_time", list(choices))
    ]


@pytest.mark.parametrize(
    "words",
    [
        "Fridays between 16:00 and 17:00",
        "Fridays at 16:00 till 17:00",
        "Fridays 9am-5pm",
        "Fridays from 4 to 5pm",
        "Fridays at 4-5pm",
    ],
)
def test_a_new_schedule_never_reads_a_range_as_one_time(words: str):
    """An edit or a drafted setting asks for the time instead of taking the range's end."""
    assert said_schedule(words) == (None, None)


@pytest.mark.parametrize(
    "said", ["Every Friday at 16:00", "Every Friday at 4pm", "Every 2 weeks on Friday at 9am"]
)
def test_one_time_beside_other_numbers_is_no_range(said: str):
    row = carols_row(said, said)
    assert row.state == "understood"
