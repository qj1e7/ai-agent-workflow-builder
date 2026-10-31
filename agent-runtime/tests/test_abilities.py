import pytest

from agent_runtime.abilities import ABILITIES, Ability, why_not, words
from agent_runtime.contract import RowKind
from agent_runtime.planner import why_no_tool

CAN = (
    "I can only read Jira tickets, sum up what I find, check software for new releases, and "
    "create a Jira ticket after a yes."
)


def cant(what: str) -> str:
    return f"I can't {what} yet. {CAN}"


@pytest.mark.parametrize(
    ("kind", "text", "what"),
    [
        ("do", "Permanently delete every ticket", "permanently delete every ticket"),
        ("do", "Create one follow-up ticket, then close the stale ones", "close the stale ones"),
        ("do", "Create a ticket, then close every ticket", "close every ticket"),
        ("do", "Permanently delete them", "permanently delete them"),
        ("do", "Permanently delete every closed ticket", "permanently delete every closed ticket"),
        ("do", "Bulk close them", "bulk close them"),
        (
            "do",
            "Create one GitHub issue that lists them",
            "create one GitHub issue that lists them",
        ),
        ("do", "Create a GitHub issue for each", "create a GitHub issue for each"),
        ("do", "Write them to a Google Sheet", "write them to a Google Sheet"),
        ("do", "Write them to the ops teams chat", "write them to the ops teams chat"),
        ("do", "Write them to a spreadsheet", "write them to a spreadsheet"),
        ("do", "Closes every ticket", "close every ticket"),
        ("do", "Deleting every closed ticket", "delete every closed ticket"),
        ("do", "Open a pull request on GitHub", "open a pull request on GitHub"),
        ("do", "Text the on-call engineer", "text the on-call engineer"),
        ("do", "Restart the server", "restart the server"),
        ("do", "Run the deploy pipeline", "run the deploy pipeline"),
        ("do", "Create a ticket and assign it to Bob", "assign it to Bob"),
        ("do", "Create a ticket in project OPS and assign it to Bob", "assign it to Bob"),
        (
            "do",
            "Write them to the Weekly summary page in Confluence",
            "write them to the Weekly summary page in Confluence",
        ),
        ("do", "Create a Confluence page listing them", "create a Confluence page listing them"),
        ("do", "Add a comment to each ticket", "add a comment to each ticket"),
        ("do", "Please close every ticket", "close every ticket"),
        ("do", "Then delete them", "delete them"),
        ("do", "Also post a summary in Teams", "post a summary in Teams"),
        ("do", '"Close" every ticket', "close every ticket"),
        ("do", "“Close” every ticket", "close every ticket"),
        ("do", "Create one ticket that lists them, CLOSE the rest", "close the rest"),
        ("do", "Create one ticket + close the rest", "close the rest"),
        ("do", "Create one ticket (and close the rest)", "close the rest"),
        ("do", "Create one ticket and cc the team", "create one ticket and cc the team"),
        ("do", "Ensure every ticket is closed", "ensure every ticket is closed"),
        (
            "schedule",
            "Every weekday at 3pm, then delete every closed ticket",
            "delete every closed ticket",
        ),
        ("schedule", "Every day, and post the list in Teams", "post the list in Teams"),
    ],
)
def test_a_write_the_platform_cannot_do_is_cant_do_and_the_note_names_it(
    kind: RowKind, text: str, what: str
):
    assert why_no_tool(kind, text) == cant(what)


@pytest.mark.parametrize(
    ("text", "place"),
    [
        ("GitHub repo", "GitHub repo"),
        ("GitHub repo langchain-ai/langgraph", "GitHub repo langchain-ai/langgraph"),
        ("A Google Sheet", "a Google Sheet"),
        ("The WhatsApp group", "the WhatsApp group"),
        ("A Notion page", "a Notion page"),
        ("The support teams channel", "the support teams channel"),
        ("The Weekly summary page in Confluence", "the Weekly summary page in Confluence"),
        ("GitLab", "GitLab"),
        ("In Teams", "Teams"),
        ("Jira project MOCK and Teams", "Teams"),
    ],
)
def test_a_place_that_is_not_a_jira_project_is_cant_do(text: str, place: str):
    assert why_no_tool("where", text) == cant(f"put results in {place}")


@pytest.mark.parametrize(
    ("text", "what"),
    [("Post it in Teams", "post it in Teams"), ("Send it to Bob", "send it to Bob")],
)
def test_a_place_that_says_a_write_is_cant_do(text: str, what: str):
    assert why_no_tool("where", text) == cant(what)


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("let the team know in microsoft teams", "let the team know in microsoft teams"),
        ("Let the team know in Microsoft Teams", "let the team know in Microsoft Teams"),
        ("Jira project MOCK, then let the team know", "let the team know"),
        ("Jira project MOCK and post it in Teams", "post it in Teams"),
        ("Make sure the team sees it in Teams", "make sure the team sees it in Teams"),
        ("Write a summary to Slack", "write a summary to Slack"),
        ("Write it to Slack", "send results to Slack"),
        ("To the boss", "send results to the boss"),
        ("Somewhere the team can see it", "put results somewhere the team can see it"),
    ],
)
def test_where_it_goes_that_says_an_action_or_a_person_reads_as_plain_english(text: str, what: str):
    assert why_no_tool("where", text) == cant(what)


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Let's post it in Teams", "post it in Teams"),
        ("Go to Slack", "send results to Slack"),
        ("It goes to Slack", "send results to Slack"),
        ("Written to Slack", "send results to Slack"),
        ("Posted in Teams", "put results in Teams"),
        ("Shared with the team", "share with the team"),
        ("I want it in Teams", "put results in Teams"),
        ("We let the team know in Teams", "let the team know in Teams"),
    ],
)
def test_where_it_goes_reads_as_plain_english_after_a_subject_a_placing_verb_or_a_past_form(
    text: str, what: str
):
    assert why_no_tool("where", text) == cant(what)


@pytest.mark.parametrize(
    "text", ["Jira project MOCK, and then", "in", "in the", "To the", "Jira project MOCK, to"]
)
def test_where_it_goes_with_no_place_after_a_jira_place_or_a_bare_preposition_names_nothing(
    text: str,
):
    assert why_no_tool("where", text) is None


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("do", "Create a ticket to"),
        ("do", "Write a summary to"),
        ("schedule", "Every day, write a summary to"),
    ],
)
def test_a_trailing_to_names_no_place_and_never_stops_the_check(kind: RowKind, text: str):
    assert why_no_tool(kind, text) is None


@pytest.mark.parametrize(
    ("text", "system"),
    [
        ("Who has admin access in GitLab", "GitLab"),
        ("Open merge requests in GitLab", "GitLab"),
        ("Pages in Confluence changed this week", "Confluence"),
        ("Bug tickets in GitLab", "GitLab"),
        ("Open GitHub issues", "GitHub"),
        ("Users from Entra", "Entra"),
    ],
)
def test_a_search_of_another_system_is_cant_do(text: str, system: str):
    assert why_no_tool("look_for", text) == cant(f"read {system}")


def test_a_search_that_starts_with_a_write_is_cant_do():
    assert why_no_tool("look_for", "Close tickets with no update") == cant(
        "close tickets with no update"
    )
    assert why_no_tool("look_for", "Tickets in MOCK, then close them") == cant("close them")


@pytest.mark.parametrize(
    "text",
    [
        "Bug tickets assigned to Mark",
        "Bug tickets assigned to Mark in MOCK",
        "Tickets assigned to Ping",
        "Tickets assigned to Mark and Ping",
        "Tickets to update",
        "Bug tickets about email delivery",
        "Bug tickets in MOCK about email delivery",
        "Tickets about the Confluence migration",
        "Tickets in MOCK about the Confluence migration",
        "Tickets that mention GitLab",
        "Access request tickets for Entra",
        "Entra access request tickets in MOCK",
        "GitLab access request tickets",
        "Bug tickets in MOCK with no update for 10 days",
        "Tickets with no update for 10 days",
        "Tickets without an update this week",
        "Tickets with the label urgent",
        "Tickets raised by the support teams",
        "Closed tickets",
        "Tickets closed this week",
        "Open tickets in MOCK",
        "Stale tickets, read as no update for 14 days",
        "Jira tickets the team closed this week",
        "Tickets in the Support project",
        "Tickets created in March",
    ],
)
def test_a_search_of_jira_tickets_stays_as_the_model_said(text: str):
    assert why_no_tool("look_for", text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Create one follow-up ticket that lists them",
        "Create one ticket that sums them up",
        "Create one ticket that lists them",
        "Create one ticket in MOCK that lists them",
        "Create one change ticket that lists them",
        "Create one ticket listing the closed ones",
        "Create one ticket that lists them and their owners",
        "Create a ticket to track them",
        "Create ticket 3",
        "Create one Entra access ticket",
        "Raise one ticket in Jira project SUP",
        "Log a bug in MOCK",
        "Add them to a new ticket",
        "Propose one ticket for an Approver to check",
        "Write a short summary",
        "Write an update for the team",
        "A short summary",
        "One follow-up ticket that lists them",
        "Sum them up",
        "Sum up the Jira tickets our team closed this week",
        "List them by owner",
        "Count them",
        "Group them by owner",
        "Check LangGraph for new releases",
        "Check the GitHub releases of LangGraph",
        "Create one ticket for Mark",
        "Generate one ticket that lists them",
        "Create one ticket in OPS",
    ],
)
def test_a_read_or_a_new_jira_ticket_stays_as_the_model_said(text: str):
    assert why_no_tool("do", text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Jira project MOCK",
        "MOCK",
        "A new ticket in Jira project SUP",
        "The MOCK project",
        "The Support project in Jira",
        "In Jira",
        "A new Jira ticket",
        "The agent's Jira project",
        "Create it in MOCK",
    ],
)
def test_a_jira_project_or_the_default_place_stays_as_the_model_said(text: str):
    assert why_no_tool("where", text) is None


@pytest.mark.parametrize(
    "text", ["Every weekday at 3pm", "Every Monday and Friday", "Every day at 9am and 5pm"]
)
def test_a_schedule_with_no_action_stays_as_the_model_said(text: str):
    assert why_no_tool("schedule", text) is None


def test_a_new_tool_is_one_more_line_in_the_table():
    teams = Ability(
        "post a message in Teams",
        words("post"),
        makes=words("message summary"),
        reaches=frozenset({"teams"}),
    )
    more = (*ABILITIES, teams)
    assert why_not("do", "Post a summary in Teams") is not None
    assert why_not("do", "Post a summary in Teams", more) is None
    assert why_not("where", "Teams", more) is None
    assert why_not("do", "Delete them", more) == (
        "I can't delete them yet. I can only read Jira tickets, sum up what I find, check "
        "software for new releases, create a Jira ticket after a yes, and post a message in "
        "Teams."
    )
