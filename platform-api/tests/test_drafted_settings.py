"""A drafted workflow's settings and the questions that fill them, all code's (ADR 0051, section 5):
each setting's mark and where its value came from, the Approvers and write keys the drafter never
writes, one question at a time in the ADR's order with choices from the team's own data, typed
answers read by code, and the never-guessed places the class file names."""

from typing import Any

import pytest

from platform_api.builder.drafted_settings import (
    ANY_APPROVER,
    APPROVERS,
    Answered,
    SettingNow,
    Source,
    Unread,
    asking,
    never_guessed,
    next_question,
    place_kinds,
    read_answer,
    settings_of,
    typed_time,
    with_answer,
)
from platform_api.orchestration import DrafterFacts, WorkflowPlan
from platform_api.shared import UserId
from tests.test_drafted_layout import block, release_check, setting, wire

FACTS = DrafterFacts(
    jira_projects=["MOCK", "OPS"],
    confluence_pages=["Team leavers"],
    repositories=["langchain-ai/langgraph", "fastapi/fastapi"],
    channels=["#support", "#eng-housekeeping"],
)
ALICE = UserId("alice")
SLACK_POST = {
    "resource": "message",
    "operation": "post",
    "select": "channel",
    "channelId": {"__rl": True, "mode": "name", "value": "<<channel>>"},
    "text": "A new release is out.",
}


def by_id(settings: tuple[SettingNow, ...]) -> dict[str, SettingNow]:
    return {s.id: s for s in settings}


def plan_with(**changes: Any) -> WorkflowPlan:
    plan = release_check().model_dump()
    for key, value in changes.items():
        plan[key] = value
    return WorkflowPlan.model_validate(plan)


def with_settings(*settings: dict[str, Any]) -> WorkflowPlan:
    plan = release_check().model_dump()
    plan["settings"] = list(settings)
    return WorkflowPlan.model_validate(plan)


def test_the_release_check_has_its_three_settings_and_asks_who_says_yes_to_its_write():
    sources = {"run_time": Source("monday 09:00", "words", ALICE)}
    settings = by_id(settings_of(release_check(), sources))

    assert [s for s in settings] == ["run_time", "repository", "jira_project", APPROVERS]
    assert (settings["run_time"].mark, settings["run_time"].source) == (
        "filled",
        Source("monday 09:00", "words", ALICE),
    )
    approvers = settings[APPROVERS]
    assert (approvers.kind, approvers.mark, approvers.value) == ("approvers", "needed", None)
    assert approvers.block == "Make the ticket"


def test_an_answered_approvers_setting_is_filled_with_who_chose_it():
    sources = {APPROVERS: Source(ANY_APPROVER, "chose", ALICE)}
    approvers = by_id(settings_of(release_check(), sources))[APPROVERS]

    assert (approvers.mark, approvers.value, approvers.source) == (
        "filled",
        ANY_APPROVER,
        Source(ANY_APPROVER, "chose", ALICE),
    )


def test_one_of_n8n_s_own_blocks_that_writes_needs_a_write_key_which_waits_for_a_later_step():
    plan = release_check().model_dump()
    plan["blocks"].append(
        block("Close the issue", "n8n-nodes-base.github", 1.1, resource="issue", operation="edit")
    )
    plan["wires"].append(wire("Make the ticket", "Close the issue"))
    settings = by_id(settings_of(WorkflowPlan.model_validate(plan), {}))

    key = settings["key:Close the issue"]
    assert (key.kind, key.mark, key.block) == ("key", "needed", "Close the issue")
    question = asking(key, FACTS)
    assert question.choices == () and question.typed is None
    assert question.waits is not None and "later step" in question.waits


def test_a_run_time_still_needed_asks_how_often_and_then_the_time():
    no_day = by_id(settings_of(release_check(run_time=None), {}))["run_time"]
    question = asking(no_day, FACTS)

    assert (question.key, question.words) == ("When", "How often should it run?")
    assert [c.label for c in question.choices] == ["Every day", "Weekdays", "Mondays", "Fridays"]
    assert question.typed is None

    monday = by_id(settings_of(release_check(run_time="monday"), {}))["run_time"]
    assert (monday.mark, monday.value) == ("needed", "monday")
    question = asking(monday, FACTS)
    assert question.words == "Mondays, at what time?"
    assert [c.label for c in question.choices] == ["8:00", "9:00", "13:00", "17:00"]
    assert question.typed == "Type a time"


def test_a_run_time_in_words_code_can_t_read_is_still_needed():
    plan = release_check(run_time="the first Monday of each month")
    run_time = by_id(settings_of(plan, {}))["run_time"]

    assert (run_time.mark, run_time.value) == ("needed", None)


def test_the_questions_come_one_at_a_time_in_the_adr_s_order():
    plan = with_settings(
        setting("jira_project", "jira_project", None, "Propose a ticket", "place"),
        setting("repository", "repository", "langchain-ai/langgraph", "Read new releases", "place"),
        setting("run_time", "run_time", None, "Every Monday", "rule"),
    )
    settings = settings_of(plan, {})

    asked = next_question(settings, FACTS)
    assert asked is not None and asked.id == "run_time"
    then = settings_of(
        with_answer(plan, "run_time", "monday 09:00", "filled"),
        {"run_time": Source("monday 09:00", "chose", ALICE)},
    )
    asked = next_question(then, FACTS)
    assert asked is not None and asked.id == "jira_project"
    last = settings_of(
        with_answer(
            with_answer(plan, "run_time", "monday 09:00", "filled"),
            "jira_project",
            "MOCK",
            "filled",
        ),
        {},
    )
    asked = next_question(last, FACTS)
    assert asked is not None and asked.id == APPROVERS
    assert asking(asked, FACTS).words == "Who says yes to “Make the ticket” on each run?"
    assert [c.label for c in asking(asked, FACTS).choices] == [ANY_APPROVER]


def test_a_place_s_choices_come_from_the_team_s_own_data():
    plan = with_settings(setting("jira_project", "jira_project", None, "Propose a ticket", "place"))
    project = by_id(settings_of(plan, {}))["jira_project"]
    question = asking(project, FACTS)

    assert question.words == "Which Jira project should it use?"
    assert [c.value for c in question.choices] == ["MOCK", "OPS"]
    assert question.typed is None


def test_a_channel_with_nothing_the_platform_can_see_waits():
    plan = with_settings(setting("channel", "channel", None, "Read new releases", "place"))
    channel = by_id(settings_of(plan, {}))["channel"]

    question = asking(channel, DrafterFacts())
    assert question.choices == () and question.waits is not None
    assert [c.value for c in asking(channel, FACTS).choices] == ["#support", "#eng-housekeeping"]


@pytest.mark.parametrize(
    ("typed", "read"),
    [
        ("7:45", "07:45"),
        ("09:30", "09:30"),
        ("6pm", "18:00"),
        ("6:30 p.m.", "18:30"),
        ("12am", "00:00"),
        ("9", None),
        ("at nine", None),
        ("25:00", None),
        ("13pm", None),
    ],
)
def test_a_typed_time_is_read_by_code_and_a_bare_hour_is_never_guessed(
    typed: str, read: str | None
):
    assert typed_time(typed) == read


def test_a_choice_or_a_typed_answer_fills_a_setting_and_anything_else_comes_back():
    monday = by_id(settings_of(release_check(run_time="monday"), {}))["run_time"]

    assert read_answer(monday, FACTS, choice="09:00", typed=None) == Answered("monday 09:00", True)
    assert read_answer(monday, FACTS, choice=None, typed="6pm") == Answered("monday 18:00", True)
    assert isinstance(read_answer(monday, FACTS, choice="10:00", typed=None), Unread)
    assert isinstance(read_answer(monday, FACTS, choice=None, typed="9"), Unread)

    no_day = by_id(settings_of(release_check(run_time=None), {}))["run_time"]
    assert read_answer(no_day, FACTS, choice="weekdays", typed=None) == Answered("weekdays", False)

    plan = with_settings(setting("jira_project", "jira_project", None, "Propose a ticket", "place"))
    project = by_id(settings_of(plan, {}))["jira_project"]
    assert read_answer(project, FACTS, choice="OPS", typed=None) == Answered("OPS", True)
    assert isinstance(read_answer(project, FACTS, choice="SECRET", typed=None), Unread)


def test_a_guessed_repository_can_be_changed_to_one_typed_as_owner_and_name():
    plan = with_settings(
        {
            **setting("repository", "repository", "fastapi/fastapi", "Read new releases", "place"),
            "mark": "guessed",
        }
    )
    repository = by_id(settings_of(plan, {}))["repository"]

    assert repository.mark == "guessed"
    assert asking(repository, FACTS).typed == "Type one"
    assert read_answer(repository, FACTS, choice=None, typed="pydantic/pydantic") == Answered(
        "pydantic/pydantic", True
    )
    assert isinstance(read_answer(repository, FACTS, choice=None, typed="not a repo"), Unread)


def test_a_place_the_class_file_names_that_the_drafter_wrote_out_becomes_a_needed_setting():
    plan = release_check().model_dump()
    post = {**SLACK_POST, "channelId": {"__rl": True, "mode": "name", "value": "#random"}}
    plan["blocks"].append(block("Post it", "n8n-nodes-base.slack", 2.3, **post))
    plan["wires"].append(wire("Make the ticket", "Post it"))

    checked = never_guessed(WorkflowPlan.model_validate(plan))

    [added] = [s for s in checked.settings if s.kind == "channel"]
    assert (added.value, added.mark) == (None, "needed")
    [place] = added.fills
    assert (place.block, place.parameter) == ("Post it", "channelId.value")
    [posted] = [b for b in checked.blocks if b.name == "Post it"]
    assert posted.parameters["channelId"]["value"] == f"<<{added.id}>>"


def test_a_place_that_already_holds_a_setting_s_placeholder_is_left_as_it_is():
    plan = release_check().model_dump()
    plan["blocks"].append(block("Post it", "n8n-nodes-base.slack", 2.3, **SLACK_POST))
    plan["wires"].append(wire("Make the ticket", "Post it"))
    plan["settings"].append(setting("channel", "channel", "#support", "Post it", "channelId.value"))
    drafted = WorkflowPlan.model_validate(plan)

    assert never_guessed(drafted) == drafted


def test_each_place_takes_the_kind_the_drafter_gives_it():
    """As the drafter's own classes: a Slack user is a channel a notice posts to, an email's
    recipients are addresses, a schedule's rule is a run time and our places are their own."""
    slack = block("Tell", "n8n-nodes-base.slack", 2.3, **{**SLACK_POST, "select": "user"})
    slack["parameters"]["user"] = {"__rl": True, "mode": "username", "value": "<<channel>>"}
    gmail = block("Mail", "n8n-nodes-base.gmail", 2.1, resource="message", operation="send")
    jira = block("Find", "n8n-nodes-base.jira", 1, resource="issue", operation="getAll")
    plan = release_check().model_dump()
    plan["blocks"] += [slack, gmail, jira]
    blocks = {b.name: b for b in WorkflowPlan.model_validate(plan).blocks}

    assert place_kinds(blocks["Tell"])["user.value"] == "channel"
    assert place_kinds(blocks["Mail"])["sendTo"] == "address"
    assert place_kinds(blocks["Find"])["project"] == "jira_project"
    assert place_kinds(blocks["Every Monday"]) == {"rule": "run_time"}
    assert place_kinds(blocks["Read new releases"]) == {"place": "repository"}
    assert place_kinds(blocks["Propose a ticket"]) == {"place": "jira_project"}
