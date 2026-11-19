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
    NOT_EXACT,
    NOT_HELD,
    ONE_DAY,
    ONE_TIME,
    READ_FROM,
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


@pytest.mark.parametrize("said", ["Every Friday at 16:00", "Every Friday at 4pm"])
def test_one_time_beside_other_numbers_is_no_range(said: str):
    row = carols_row(said, said)
    assert row.state == "understood"


UNHELD = [
    (
        "Every other Friday at 9am",
        ["Every Friday", "Every 2 weeks on Friday at 9am", "Every other Friday at 9am"],
    ),
    ("Every 2 weeks on Friday at 9am", ["Every Friday"]),
    ("Every second Tuesday at 3pm", ["Every Tuesday"]),
    ("Fortnightly on Friday at 9am", ["Every Friday at 9am"]),
    ("On the first Monday of the month at 10am", ["Monthly", "Monthly on Monday at 10am"]),
    ("On the last Friday of each month at 4pm", ["Every Friday at 4pm"]),
    ("On the 1st of every month at 9am", ["Monthly at 9am"]),
    ("Every quarter at 9am", ["Quarterly"]),
    (
        "Every 3rd Friday at 9am",
        ["Every Friday at 9am", "Every third Friday at 9am", "Monthly on Friday at 9am"],
    ),
    ("Alternate Fridays at 9am", ["Every Friday at 9am", "Every other Friday at 9am"]),
    ("On alternate Fridays at 9am", ["Every Friday at 9am"]),
    ("Twice a week at 9am", ["Every Monday at 9am", "Twice a week at 9am", "Every day at 9am"]),
    ("On weekends at 9am", ["Every Saturday at 9am", "Every day at 9am"]),
    ("Every weekday except Friday at 9am", ["Every weekday at 9am"]),
    ("Every 30 minutes", ["Every day", "Every 30 minutes"]),
    ("Every 15 mins", ["Every day"]),
    ("Once a month on Friday at 9am", ["Monthly on Friday at 9am", "Every Friday at 9am"]),
    ("Once a month at 9am", ["Monthly at 9am", "Every day at 9am"]),
    ("Bi-weekly on Friday at 9am", ["Every Friday at 9am", "Biweekly on Friday at 9am"]),
    ("Every couple of weeks on Friday at 9am", ["Every Friday at 9am"]),
    ("Every few days at 9am", ["Every day at 9am"]),
    ("Every working day at 9am", ["Every weekday at 9am"]),
    ("Every Friday fortnightly at 9am", ["Every Friday at 9am"]),
    ("Every other week on Friday at 9am", ["Every Friday at 9am"]),
    ("At the end of each month at 5pm", ["Monthly at 5pm", "Every Friday at 5pm"]),
    ("On the last working day of the month at 5pm", ["Every Friday at 5pm"]),
    ("Every hour", ["Hourly", "Every day"]),
    ("Three times a day", ["Every day"]),
    ("Every other Friday before 5pm", ["Every Friday"]),
    ("Monday to Wednesday at 9am", ["Every weekday at 9am", "Every Monday at 9am"]),
    ("Tuesday through Thursday at 9am", ["Every Tuesday through Thursday at 9am"]),
    ("Saturday to Sunday at 9am", ["Every Saturday to Sunday at 9am", "Every Saturday at 9am"]),
    ("Mon-Wed at 9am", ["Every Monday at 9am"]),
]


@pytest.mark.parametrize(
    ("said", "model"), [(said, model) for said, models in UNHELD for model in models]
)
def test_a_schedule_it_cant_hold_is_asked_and_its_whole_phrase_crossed(said: str, model: str):
    """The schedule holds one or more days, every day, every weekday or once a week, and one
    time. Any other word, as "other", "3rd", "once a month", "alternate", "bi-weekly", "except"
    or "minutes", is a schedule it can't hold. The card asks, never filling a day or time, and
    crosses the whole phrase. Before, "every weekday except Friday" filled "Every Friday", and
    "alternate Fridays" showed as understood."""
    row, parts = carols_card(model, said)
    assert (row.text, row.state, row.note) == ("", "missing", NOT_HELD.format(said))
    assert [(p.text, p.reason) for p in parts if p.mark == "cant"] == [(said, "how_often")]


@pytest.mark.parametrize(
    "said",
    [
        "Every Friday at 16:00",
        "Every weekday at 3pm",
        "Each Monday at 09:30",
        "Every Friday morning at 9",
        "Every Monday at 9am",
        "Daily at 8.30am",
        "Every day at 8.30am",
        "Monday to Friday at 9am",
        "Once a week on Friday at 9am",
    ],
)
def test_a_schedule_it_holds_stays_their_own_words_with_nothing_crossed(said: str):
    row, parts = carols_card("Every Friday", said)
    assert (row.text, row.state) == (said, "understood")
    assert [p for p in parts if p.mark == "cant"] == []


@pytest.mark.parametrize("words", ["Monday to Wednesday at 9am", "Saturday to Sunday at 9am"])
def test_a_new_schedule_reads_no_day_from_a_range_other_than_the_weekdays(words: str):
    """Before, any range was read as every weekday. A schedule it can't hold is asked whole, so
    its time is not read either."""
    assert said_schedule(words) == (None, None)
    assert said_schedule("Monday to Friday at 9am") == ("weekdays", "09:00")


def test_a_count_before_the_schedule_is_never_part_of_it():
    """Carol's request, reordered. Before, "days every Friday at 16:00" was crossed as a
    schedule it can't hold."""
    text = (
        "Find Jira tickets in project MOCK that nobody updated for 14 days every Friday at 16:00 "
        "and raise one Jira ticket in MOCK that lists them"
    )
    task = read(
        name="Stale MOCK ticket list",
        schedule="Every Friday at 16:00",
        search=SearchRead(
            project="MOCK",
            updated=DaysRead(how="before", days=14),
            said="Jira tickets in project MOCK that nobody updated for 14 days",
        ),
        ticket=TicketRead(creates=True, says="list", said="lists them"),
        place=PlaceRead(project="MOCK", said="raise one Jira ticket in MOCK"),
    )
    answer = answer_of(task, text)
    card = answer.alternative if isinstance(answer, CantAnswer) else answer
    assert isinstance(card, SetupCardAnswer)
    assert (card.rows[0].text, card.rows[0].state) == ("Every Friday at 16:00", "understood")
    assert not any(p.reason == "how_often" for p in parts_of(task, text, answer))


@pytest.mark.parametrize(
    ("said", "model", "vague"),
    [
        ("Every day at 9am or so", "Every day at 9am", "or so"),
        ("Every Friday at 16:00-ish", "Every Friday at 16:00", "16:00-ish"),
        ("Every Friday roughly at 4pm", "Every Friday at 4pm", "roughly"),
        ("Every Friday at the end of the day", "Every Friday at 5pm", "the end of the day"),
        ("Every Friday at EOD", "Every Friday at 5pm", "EOD"),
    ],
)
def test_a_time_that_is_not_exact_is_asked_and_the_day_stays(said: str, model: str, vague: str):
    """Before, "Every day at 9am or so" said it couldn't run things every day at 9am."""
    row, parts = carols_card(model, said)
    day = "Every day" if said.startswith("Every day") else "Every Friday"
    assert (row.text, row.state, row.note) == (day, "missing", NOT_EXACT.format(vague))
    assert not any(p.reason == "how_often" for p in parts)


@pytest.mark.parametrize(
    ("said", "model"),
    [
        ("Every Friday at 4pm before the weekly meeting", "Every Friday at 4pm"),
        ("Every Monday first thing at 9am", "Every Monday at 9am"),
    ],
)
def test_words_beside_a_schedule_it_holds_never_blame_how_often(said: str, model: str):
    row, parts = carols_card(model, said)
    assert row.state == "understood" and row.note is None
    assert not any(p.reason == "how_often" for p in parts)


@pytest.mark.parametrize(
    ("said", "model"),
    [
        ("At 9am every Friday", "Every Friday at 9am"),
        ("Fridays at 9am", "Every Friday at 9am"),
        ("Each Tuesday at 10:30", "Every Tuesday at 10:30"),
        ("Weekly on Monday at 9am", "Every Monday at 9am"),
        ("Every week on Monday at 9am", "Every Monday at 9am"),
        ("Once a week on Monday at 9am", "Every Monday at 9am"),
        ("Daily", "Every day"),
    ],
)
def test_their_own_schedule_is_shown_whatever_the_model_wrote(said: str, model: str):
    """Before, the row was the model's words with "Your words didn't say it", which the final
    check repeated, though their words said it."""
    row = carols_row(model, said)
    assert (row.text, row.state, row.note) == (said, "understood", None)


# A day or a time in a later clause


@pytest.mark.parametrize(
    ("said", "model", "reason", "choices"),
    [
        (
            "Every Friday at 9am, actually make it Monday",
            "Every Monday at 9am",
            ONE_DAY,
            ["Friday", "Monday"],
        ),
        (
            "Every Friday at 9am actually Monday",
            "Every Monday at 9am",
            ONE_DAY,
            ["Friday", "Monday"],
        ),
        (
            "Every Friday at 9am, sorry, I mean Thursday",
            "Every Thursday at 9am",
            ONE_DAY,
            ["Friday", "Thursday"],
        ),
        ("Every Friday at 9am, no wait, 10am", "Every Friday at 10am", ONE_TIME, ["9am", "10am"]),
        (
            "Every Friday at 9am, actually make it Monday",
            "Every Friday at 9am",
            ONE_DAY,
            ["Friday", "Monday"],
        ),
        ("Every Friday at 9am then Monday", "Every Friday at 9am", ONE_DAY, ["Friday", "Monday"]),
        (
            "Every Friday at 9am, and also on Mondays",
            "Every Friday at 9am",
            ONE_DAY,
            ["Friday", "Monday"],
        ),
    ],
)
def test_a_later_day_or_time_is_asked_with_both_and_the_first_is_never_understood(
    said: str, model: str, reason: str, choices: list[str]
):
    """Before, the row was the first schedule, understood, so the final check said "as you
    asked" for the day or time they took back, and "then Monday" went without a word."""
    row, parts = carols_card(model, said)
    quoted = " and ".join(f'"{choice}"' for choice in choices)
    assert (row.text, row.state, row.note) == ("", "missing", reason.format(quoted))
    clash = "one_day" if reason == ONE_DAY else "one_time"
    assert [p.choices for p in parts if p.reason == clash] == [choices]


@pytest.mark.parametrize(
    "said",
    [
        "Mon-Fri at 9am",
        "Mon to Fri at 9am",
        "Mon - Fri at 9am",
        "Daily at 9am, except weekends",
        "Every day at 9am except weekends",
        "Every day at 9am except Saturdays and Sundays",
    ],
)
def test_weekdays_written_another_way_are_every_weekday(said: str):
    """Before, each was asked as a schedule it can't hold, and "Daily at 9am" was crossed with
    "I can't run things daily at 9am yet"."""
    row, parts = carols_card("Every weekday at 9am", said)
    assert (row.text, row.state, row.note) == (
        "Every weekday at 9am",
        "understood",
        READ_FROM.format(said),
    )
    assert [p for p in parts if p.mark == "cant"] == []
    assert said_schedule(said) == ("weekdays", "09:00")


@pytest.mark.parametrize("model", ["Every Friday", "Every Friday at 5pm"])
def test_a_bound_in_words_with_its_time_is_asked_never_dropped(model: str):
    """Before, "by the end of the day at 5pm" went without a word."""
    row = carols_row(model, "Every Friday by the end of the day at 5pm")
    note = NOT_A_RUN_TIME.format("by the end of the day at 5pm")
    assert (row.text, row.state, row.note) == ("Every Friday", "missing", note)


@pytest.mark.parametrize(
    ("said", "model", "shown"),
    [
        ("Every Friday. Run it at 9am", "Every Friday at 9am", "Every Friday at 9am"),
        ("Every Friday. Run it at 9am", "Every Friday", "Every Friday at 9am"),
        ("Mon-Fri. Run it at 9am", "Every weekday at 9am", "Every weekday at 9am"),
    ],
)
def test_a_time_in_its_own_sentence_stays_on_the_row(said: str, model: str, shown: str):
    """Before, "Run it at 9am" was crossed as a part it can't do, and the card asked the time."""
    row, parts = carols_card(model, said)
    assert (row.text, row.state) == (shown, "understood")
    assert [p for p in parts if p.mark == "cant"] == []


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Every Friday at 9am or so", ("friday", None)),
        ("Every Friday at 9am roughly", ("friday", None)),
        ("Every Friday at 16:00-ish", ("friday", None)),
        ("every other Friday at 9am", (None, None)),
        ("once a month on Friday at 9am", (None, None)),
    ],
)
def test_a_new_schedule_never_takes_a_time_that_is_not_exact_or_a_schedule_it_cant_hold(
    words: str, read: tuple[str | None, str | None]
):
    """Before, each read 09:00 or 16:00, and "every other Friday" read Friday."""
    assert said_schedule(words) == read


@pytest.mark.parametrize(
    "said",
    [
        "Every other Friday " * 15,
        "Every Monday Tuesday Wednesday Thursday Friday Saturday Sunday at "
        + " ".join(f"{hour}am" for hour in range(1, 12))
        + " "
        + " ".join(f"{hour}pm" for hour in range(1, 12)),
    ],
)
def test_a_long_schedule_phrase_is_asked_with_a_note_that_fits(said: str):
    """Before, the note quoted too many words for its limit, and the request failed."""
    row = carols_row("Every Friday", said.strip())
    assert row.state == "missing" and row.note is not None and len(row.note) <= 300


@pytest.mark.parametrize(
    ("said", "shown"),
    [
        ("Monday to Fri at 9am", "Every weekday at 9am"),
        ("Mon–Fri at 9am", "Every weekday at 9am"),
        ("every Mon at 09:00", "Every Monday at 09:00"),
        ("Every Tue at 10am", "Every Tuesday at 10am"),
    ],
)
def test_short_day_names_and_a_dash_read_as_the_whole_day(said: str, shown: str):
    """Before, "Monday to Fri" read as Monday, "Mon–Fri" was crossed, and "every Mon" was
    crossed as a part it can't do."""
    row, parts = carols_card("Every weekday at 9am", said)
    assert (row.text, row.state, row.note) == (shown, "understood", READ_FROM.format(said))
    assert [p for p in parts if p.mark == "cant"] == []


@pytest.mark.parametrize(
    ("said", "crossed"),
    [
        ("Mon-Fri and Sat at 9am", None),
        ("Mon-Fri at 9am, also Sat", None),
        ("Daily at 9am, except weekends and holidays", "except weekends and holidays"),
        ("Every day at 9am but skip Fridays", "skip Fridays"),
        ("Every weekday at 9am, never on Mondays", "never on Mondays"),
    ],
)
def test_weekdays_beside_another_day_or_a_day_left_out_are_asked(said: str, crossed: str | None):
    """Before, "Mon-Fri and Sat" showed every weekday as understood, "skip Fridays" ran every
    day, and "Daily at 9am" was crossed as a schedule it can't run."""
    row, parts = carols_card("Every weekday at 9am", said)
    assert (row.text, row.state) == ("", "missing")
    if crossed is not None:
        assert [(p.text, p.reason) for p in parts if p.mark == "cant"] == [(crossed, "how_often")]


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("make it Mon-Fri at 9am, also Sat", (None, None)),
        ("make it Mon-Fri and Sat at 9am", (None, None)),
        ("make it daily at 9am except weekends and holidays", (None, None)),
        ("make it daily except weekends, holidays", (None, None)),
        ("make it daily except weekends, and holidays", (None, None)),
        ("skip Fridays", (None, None)),
        ("don't run it on Mondays any more", (None, None)),
        ("run it on Tue at 10am", ("tuesday", "10:00")),
        ("make it Monday to Fri", ("weekdays", None)),
        ("make it daily at 9am, except weekends", ("weekdays", "09:00")),
    ],
)
def test_a_new_schedule_reads_short_days_and_never_a_day_left_out(
    words: str, read: tuple[str | None, str | None]
):
    assert said_schedule(words) == read


def card_for(text: str, schedule: str) -> tuple[UnderstoodRow, list[RequestPart]]:
    """The schedule row and the parts for a request that finds tickets in MOCK and raises one
    ticket that lists them, with the model reading the schedule as `schedule`."""
    task = read(
        name="Ticket list",
        schedule=schedule,
        search=SearchRead(project="MOCK", said="tickets in MOCK"),
        ticket=TicketRead(creates=True, says="list", said="raise one ticket that lists them"),
    )
    answer = answer_of(task, text)
    card = answer.alternative if isinstance(answer, CantAnswer) else answer
    assert isinstance(card, SetupCardAnswer)
    row = next(r for r in card.rows if r.kind == "schedule")
    return row, parts_of(task, text, answer)


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("Check tickets in WED at 4pm and raise one ticket that lists them", "Wednesday"),
        ("Check the SAT tickets at 9am and raise one ticket that lists them", "Saturday"),
        ("Check tickets in project MON at 9am and raise one ticket that lists them", "Monday"),
    ],
)
def test_a_project_key_that_looks_like_a_short_day_is_never_read_as_the_day(text: str, day: str):
    """Before, "in WED at 4pm" showed "In Wednesday at 4pm" understood, and "the SAT tickets"
    ran on Saturdays "as you asked"."""
    row, _ = card_for(text, "Every day at 9am")
    assert day not in row.text and row.state != "understood"
    assert said_schedule(text)[0] is None


@pytest.mark.parametrize(
    ("filter_words", "schedule"),
    [
        ("that are not on Monday's board", "Every Friday at 9am"),
        ("titled Pause on Monday", "Every Friday at 9am"),
        ("besides Monday's", "Every Friday at 9am"),
        ("we skip on Mondays", "Every Friday at 9am"),
        ("that stop on Monday", "Every Friday at 9am"),
        ("for staff not on holiday", "Every Friday at 9am"),
        ("except Friday's hotfixes", "Every Monday at 9am"),
        ("that are not weekend work", "Every day at 9am"),
    ],
)
def test_a_day_left_out_in_a_filter_never_makes_the_schedule_asked(
    filter_words: str, schedule: str
):
    """Before, each made the row missing and crossed the filter as a schedule it can't hold."""
    text = f"{schedule}, list tickets in MOCK {filter_words} and raise one ticket that lists them"
    row, parts = card_for(text, schedule)
    assert (row.text, row.state) == (schedule, "understood")
    assert not any(p.reason == "how_often" for p in parts)


@pytest.mark.parametrize(
    "text",
    [
        "Every day at 9am, but not holidays, list tickets in MOCK",
        "Every day at 9am though not on Fridays, list tickets in MOCK",
    ],
)
def test_a_day_left_out_beside_the_schedule_is_asked_on_the_card(text: str):
    text = f"{text} and raise one ticket that lists them"
    row, parts = card_for(text, "Every day at 9am")
    assert row.state == "missing"
    assert any(p.reason == "how_often" for p in parts)


@pytest.mark.parametrize(
    "words",
    [
        "drop Fridays",
        "remove Fridays",
        "cut Fridays",
        "take out Fridays",
        "leave out Fridays",
        "minus Fridays",
        "Fridays excluded",
        "Fridays off",
        "Friday is off",
        "not on Friday's",
        "ditch Fridays",
        "Fridays are cancelled",
        "nothing on Fridays",
        "drop every Friday",
        "skip Friday's",
        "except Friday's",
        "unless it's a Friday",
        "make it daily, Fridays off",
    ],
)
def test_a_new_schedule_never_reads_a_day_it_isn_t_told_to_run_on(words: str):
    """Before, each read Friday as the day it runs, so a schedule change moved it to Fridays."""
    assert said_schedule(words) == (None, None)


@pytest.mark.parametrize(
    ("words", "read_"),
    [
        ("run it on Fridays", ("friday", None)),
        ("make it Friday", ("friday", None)),
        ("Fridays instead", ("friday", None)),
        ("weekdays only", ("weekdays", None)),
        ("make it Fridays at 10am", ("friday", "10:00")),
        ("make it daily at 9am, except weekends", ("weekdays", "09:00")),
    ],
)
def test_a_new_schedule_still_reads_a_day_it_is_told_to_run_on(
    words: str, read_: tuple[str | None, str | None]
):
    assert said_schedule(words) == read_


@pytest.mark.parametrize(
    ("words", "read_"),
    [
        ("set the due date to Friday at 5pm", (None, None)),
        ("the deadline is Friday at 5pm", (None, None)),
        ("raise it for 5pm deadlines", (None, None)),
        ("set the start date to Monday 9am", (None, None)),
        ("set the due date to Friday and run it at 10am", (None, "10:00")),
    ],
)
def test_a_new_schedule_never_reads_a_ticket_s_due_date_or_deadline(
    words: str, read_: tuple[str | None, str | None]
):
    """Before, "set the due date to Friday at 5pm" moved the workflow to Fridays at 17:00."""
    assert said_schedule(words) == read_


@pytest.mark.parametrize(
    ("words", "read_"),
    [
        ("Check every Friday at 9am", ("friday", "09:00")),
        ("Check langgraph Fridays at 9am", ("friday", "09:00")),
        ("make it Thursday, deadline Friday", ("thursday", None)),
        ("run it Fridays, due date Monday", ("friday", None)),
        ("Remind #ops of the deadline at 9am on Fridays", ("friday", "09:00")),
        ("Check SLAs on Mondays at 9am", ("monday", "09:00")),
        ("make the release check drop every Friday", (None, None)),
        ("make the release check cancel every Friday", (None, None)),
    ],
)
def test_a_new_schedule_reads_a_day_with_its_time_and_never_one_a_verb_drops(
    words: str, read_: tuple[str | None, str | None]
):
    """At acdcef14, "Check every Friday at 9am" read nothing, a ticket's date across a comma hid
    the schedule's day, and "drop every Friday" after a workflow's name read Friday."""
    assert said_schedule(words) == read_


@pytest.mark.parametrize(
    ("said", "schedule"),
    [
        ("Check every Friday at 9am", "Every Friday at 9am"),
        ("Check langgraph Fridays at 9am", "Every Friday at 9am"),
        ("Find stale tickets in MOCK Fridays at 9am", "Every Friday at 9am"),
    ],
)
def test_a_day_with_its_run_time_after_a_task_word_is_never_crossed_on_the_card(
    said: str, schedule: str
):
    """At acdcef14, the card crossed "Check every Friday at 9am" and "MOCK Fridays at 9am" as
    schedules it can't hold, the task's verb and project with them."""
    row, parts = card_for(
        f"{said}, list tickets in MOCK and raise one ticket that lists them", schedule
    )
    assert row.state != "missing"
    assert not any(p.reason == "how_often" for p in parts)


@pytest.mark.parametrize(
    ("said", "schedule", "shown"),
    [
        ("Check every Monday", "Every Monday", "Every Monday"),
        ("Check langgraph Mondays", "Every Monday", "Mondays"),
    ],
)
def test_every_day_or_a_plural_day_after_a_task_word_keeps_the_day_on_the_card(
    said: str, schedule: str, shown: str
):
    """At acdcef14, the card crossed "Check every Monday" and "langgraph Mondays" as schedules
    it can't hold, and asked the day."""
    row, parts = card_for(
        f"{said}, list tickets in MOCK and raise one ticket that lists them", schedule
    )
    assert (row.text, row.state) == (shown, "understood")
    assert not any(p.reason == "how_often" for p in parts)
    assert said_schedule(said) == ("monday", None)


@pytest.mark.parametrize(
    ("said", "crossed"),
    [
        ("Every day at 9am unless it's a Friday", "unless it's a Friday"),
        ("Every day at 9am except Friday's", "except Friday's"),
        ("Every day at 9am, skip Friday's", "skip Friday's"),
        ("Every day at 9am, Fridays excluded", "Fridays excluded"),
        ("Every day at 9am, Friday excluded", "Friday excluded"),
        ("Every day at 9am, minus Friday", "minus Friday"),
        ("Every day at 9am, Fridays off", "Fridays off"),
        ("Every day at 9am, drop Fridays", "drop Fridays"),
    ],
)
def test_a_day_the_schedule_s_words_don_t_say_to_run_on_is_asked_on_the_card(
    said: str, crossed: str
):
    """Before, "unless it's a Friday" and "except Friday's" showed "Every day at 9am" as
    understood, and "Fridays off" asked whether to run every day or on Fridays."""
    row, parts = card_for(
        f"{said}, list tickets in MOCK and raise one ticket that lists them", "Every day at 9am"
    )
    assert (row.text, row.state) == ("", "missing")
    assert row.note == NOT_HELD.format(crossed)
    assert [(p.text, p.reason) for p in parts if p.mark == "cant"] == [(crossed, "how_often")]
