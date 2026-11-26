"""A request that asks to run only by hand, as "on demand", has no schedule: its schedule row
holds their own words, so the Portal sets it up to run only when someone presses Run now. Only
the words on the allow-list count. Any other words for when it runs are asked, and a schedule
is never guessed (principle 4)."""

import pytest

from agent_runtime.answers import answer_of, parts_of
from agent_runtime.contract import CantAnswer, RequestPart, SetupCardAnswer, UnderstoodRow
from agent_runtime.planner import NOT_SAID
from agent_runtime.reading import (
    DaysRead,
    PlaceRead,
    SearchRead,
    TicketRead,
    render_schedule,
)
from tests.test_answers import read
from tests.test_planner_led import marks, run, shown, tool
from tests.test_release_check_routes import facts
from tests.test_release_check_routes import read as release_read

REST = (
    "find Jira tickets in project MOCK that nobody updated for 14 days, and raise one Jira "
    "ticket in MOCK that lists them"
)
BY_HAND = [
    "Only when I ask",
    "When I run it",
    "Only when I run it",
    "On demand",
    "Run it manually",
    "Only run manually",
    "Only manually",
]


def answered(text: str, schedule: str | None) -> tuple[SetupCardAnswer, list[RequestPart]]:
    """The card and the parts for the stale-ticket request, as the model reads it with
    `schedule` as its schedule."""
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
    answer = answer_of(task, text)
    card = answer.alternative if isinstance(answer, CantAnswer) else answer
    assert isinstance(card, SetupCardAnswer)
    return card, parts_of(task, text, answer)


@pytest.mark.parametrize("said", BY_HAND)
@pytest.mark.parametrize("model", ["said", None, "every day"])
def test_words_on_the_allow_list_are_the_schedule_row_whatever_the_model_read(
    said: str, model: str | None
):
    schedule = said.lower() if model == "said" else model
    card, parts = answered(f"{said}, {REST}", schedule)

    assert card.rows[0] == UnderstoodRow(kind="schedule", text=said, state="understood")
    assert [p.mark for p in parts] == ["will_do"] * len(parts)


@pytest.mark.parametrize("said", ["only when I run it", "on demand", "run it manually"])
def test_the_words_after_the_task_are_its_schedule_too(said: str):
    card, parts = answered(f"{REST[:1].upper()}{REST[1:]}, {said}", None)

    assert card.rows[0] == UnderstoodRow(
        kind="schedule", text=said[:1].upper() + said[1:], state="understood"
    )
    assert [p.mark for p in parts] == ["will_do"] * len(parts)


@pytest.mark.parametrize("said", ["Whenever", "As needed", "Now and then", "When it suits me"])
def test_any_other_words_for_when_it_runs_are_asked_never_guessed(said: str):
    card, _ = answered(f"{said}, {REST}", None)

    assert (card.rows[0].kind, card.rows[0].text, card.rows[0].state) == ("schedule", "", "missing")


@pytest.mark.parametrize(
    "text",
    [
        "Check n8n releases so I don't have to check manually",
        "Check n8n for new releases, I don't want to run it manually",
        "Check n8n for new releases, nobody should run it manually",
        "Check n8n for new releases so I don't have to run it manually",
        "Check n8n for new releases when I'm not on demand",
        "Find the tickets we triaged manually",
        "Manually",
    ],
)
def test_manually_counts_only_for_running_it_and_never_beside_a_no(text: str):
    assert render_schedule(None, text).row == UnderstoodRow(
        kind="schedule", text="", state="missing", note=NOT_SAID
    )


@pytest.mark.parametrize(
    ("words", "schedule", "row"),
    [
        (
            "On demand, and also weekly on Monday at 9am",
            "weekly on Monday at 9am",
            "Weekly on Monday at 9am",
        ),
        ("On demand or weekly", "weekly", "Weekly"),
    ],
)
def test_a_schedule_beside_the_words_wins(words: str, schedule: str, row: str):
    card, parts = answered(f"{words}, {REST}", schedule)

    assert (card.rows[0].text, card.rows[0].state) == (row, "understood")
    assert not any(p.mark == "cant" and "Monday" in p.text for p in parts), "it is never crossed"


@pytest.mark.parametrize(
    "words",
    [
        "On demand, and also weekly on Monday at 9am",
        "On demand or weekly",
        "On demand, or once a month",
    ],
)
def test_a_schedule_beside_the_words_the_model_missed_is_asked(words: str):
    card, _ = answered(f"{words}, {REST}", None)

    assert (card.rows[0].text, card.rows[0].state) == ("", "missing")


@pytest.mark.parametrize(
    ("task", "said"),
    [
        ("Check n8n for new releases on demand", "On demand"),
        ("Check n8n for new releases only when I run it", "Only when I run it"),
        ("Check n8n for new releases, run it manually", "Run it manually"),
    ],
)
@pytest.mark.parametrize("watched", [(), ("n8n",)], ids=["not watched", "watched"])
def test_one_softwares_release_check_run_by_hand_is_its_own_card(
    task: str, said: str, watched: tuple[str, ...]
):
    fields = release_read()
    answer = answer_of(fields, task, facts(*watched))

    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.rows[0] == UnderstoodRow(kind="schedule", text=said, state="understood")
    assert all(p.mark != "cant" for p in parts_of(fields, task, answer)), "nothing is crossed"


WHO_RUNS_IT = [
    ("I'll run it manually", "Run it manually"),
    ("I will run it manually", "Run it manually"),
    ("we’ll just run it manually", "Run it manually"),
    ("I'll only run it manually", "Only run it manually"),
    ("we can run it on demand", "On demand"),
    ("I'd rather run it only when I ask", "Only when I ask"),
]
"""Words before them that only say who presses Run now, which the schedule row holds with its
own words."""


@pytest.mark.parametrize(("words", "said"), WHO_RUNS_IT)
@pytest.mark.parametrize("watched", [(), ("n8n",)], ids=["not watched", "watched"])
@pytest.mark.parametrize("model", [None, "manually"])
def test_who_runs_a_release_check_by_hand_is_never_crossed_beside_its_row(
    words: str, said: str, watched: tuple[str, ...], model: str | None
):
    task = f"Check n8n for new releases, {words}"
    fields = release_read(schedule=model)
    answer = answer_of(fields, task, facts(*watched))

    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.rows[0] == UnderstoodRow(kind="schedule", text=said, state="understood")
    assert all(p.mark != "cant" for p in parts_of(fields, task, answer)), "nothing is crossed"


def test_the_ai_led_watch_tool_shows_who_runs_it_by_hand_uncrossed():
    task = "Check n8n for new releases, I'll run it manually"
    result, _ = run(
        task, tool("watch_software", software="n8n"), read=release_read(), facts=facts()
    )
    answer = shown(result)

    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.rows[0] == UnderstoodRow(
        kind="schedule", text="Run it manually", state="understood"
    )
    assert all(mark != "cant" for _, mark, _ in marks(result)), marks(result)


@pytest.mark.parametrize(("words", "said"), WHO_RUNS_IT)
def test_who_runs_a_task_by_hand_is_part_of_its_schedule_row(words: str, said: str):
    card, parts = answered(f"{REST[:1].upper()}{REST[1:]}. {words[:1].upper()}{words[1:]}.", None)

    assert card.rows[0] == UnderstoodRow(kind="schedule", text=said, state="understood")
    assert [p.mark for p in parts] == ["will_do"] * len(parts)


@pytest.mark.parametrize(
    "text",
    ["Check n8n for new releases, I won't run it manually", "I'll never run it on demand"],
)
def test_who_runs_it_beside_a_no_is_still_no_choice(text: str):
    assert render_schedule(None, text).row == UnderstoodRow(
        kind="schedule", text="", state="missing", note=NOT_SAID
    )


def test_a_schedule_beside_the_words_stays_the_schedule():
    card, _ = answered(f"Every Friday at 16:00 and on demand, {REST}", "every Friday at 16:00")

    assert card.rows[0].text == "Every Friday at 16:00"
