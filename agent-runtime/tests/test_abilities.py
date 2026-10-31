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
    "text",
    [
        "Posted in Jira project MOCK",
        "I want it in Jira project MOCK",
        "Let's put it in Jira project MOCK",
        "Sent to Jira project MOCK",
        "Written to Jira project MOCK",
        "Summarised in Jira project MOCK",
        "Jira project MOCK and then Jira project SUP",
    ],
)
def test_lead_words_before_a_jira_place_stay_as_the_model_said(text: str):
    assert why_no_tool("where", text) is None


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Posted in Slack", "put results in Slack"),
        ("I want it in Slack", "put results in Slack"),
        ("Let's put it in Teams", "put results in Teams"),
        ("Sent to Slack", "send results to Slack"),
    ],
)
def test_the_same_lead_words_before_a_place_out_of_reach_are_cant_do(text: str, what: str):
    assert why_no_tool("where", text) == cant(what)


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Moved to Jira project MOCK", "move to Jira project MOCK"),
        ("Deleted in Jira project MOCK", "delete in Jira project MOCK"),
        ("I want it closed in Jira project MOCK", "close in Jira project MOCK"),
    ],
)
def test_a_past_form_that_changes_data_before_a_jira_place_is_cant_do_and_named(
    text: str, what: str
):
    assert why_no_tool("where", text) == cant(what)


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Write a summary to Jira project MOCK", None),
        ("Put a summary in Jira project MOCK", None),
        ("Write a summary to", None),
        ("Write a summary to Slack", "write a summary to Slack"),
        ("Write a summary then post it in Teams", "post it in Teams"),
    ],
)
def test_where_it_goes_that_starts_with_an_action_agrees_with_what_it_does(
    text: str, what: str | None
):
    expected = None if what is None else cant(what)
    assert (why_no_tool("where", text), why_no_tool("do", text)) == (expected, expected)


@pytest.mark.parametrize("text", ["goes", "it", "it goes", "It goes", "them", "went"])
def test_a_lone_word_that_names_no_place_names_nothing(text: str):
    assert why_no_tool("where", text) is None


@pytest.mark.parametrize(
    ("kind", "text", "what"),
    [
        ("where", "Publié dans Teams", "put results in publié dans Teams"),
        ("where", "Post it in Publié", "post it in Publié"),
        ("where", "The Zürich team's channel", "put results in the Zürich team's channel"),
        ("where", "El canal de niños", "put results in el canal de niños"),
        ("do", "Post a summary in the 中文 channel", "post a summary in the 中文 channel"),
        ("where", "The தமிழ் channel", "put results in the தமிழ் channel"),
        ("where", "Publié dans Teams", "put results in publié dans Teams"),
    ],
)
def test_letters_outside_ascii_stay_inside_their_word(kind: RowKind, text: str, what: str):
    assert why_no_tool(kind, text) == cant(what)


def test_a_jira_project_named_with_letters_outside_ascii_stays_as_the_model_said():
    assert why_no_tool("where", "The Zürich project") is None


ANOTHER_SYSTEMS_PLACE = [
    "Write a summary for the Slack channel",
    "Write a summary for the team's Teams channel",
    "Write a summary for the Teams channel",
    "Write a summary for the Slack team",
    "Write a summary over Slack",
    "Draft a report for the Confluence page",
    "Write a summary for the Confluence wiki",
    "Make a list for the Confluence page",
    "Make a report for the SharePoint site",
    "Create a ticket for the Slack channel",
    "Create a ticket for the Confluence page",
    "Create a ticket from Slack",
    "Create a ticket from the Teams chat",
    "Write a summary about the Teams chat",
    "Write a report about the Slack channel",
    "Write a summary (Slack)",
    "Write a summary: Teams",
    "Write a summary. Teams",
    "Write a summary for the Slack workspace",
    "Write a summary for the Slack huddle",
    "Write a summary for the Slack app",
    "Write a summary for the Slack webhook",
    "Write a summary for the Slack integration",
    "Write a summary for the Slack folks",
    "Write a summary for the Slack guild",
    "Write a summary for the Confluence space",
    "Write a summary for the Confluence blog",
    "Write a summary for the Confluence template",
    "Write a summary for Confluence readers",
    "Write a summary for the Confluence editors",
    "Write a summary for the Teams meeting",
    "Write a summary for the Teams admins",
    "Write a summary for the Teams tab",
    "Write a summary for the Teams tenant",
    "Write a summary for the Teams channel owner",
    "Write a summary for the SharePoint library",
    "Write a summary for the SharePoint owners",
    "Write a summary for the Gmail account",
    "Write a summary for the Telegram bot",
    "Write a summary for the Notion workspace",
    "Write a summary for the Notion board",
    "Write a summary for the Trello board",
    "Write a summary for the GitHub issue",
    "Write a summary for the GitHub discussion",
    "Write a summary for the GitLab issue",
    "Create a ticket listing them for the Slack bot",
    "Write a summary of the week for the Slack channel readers",
    "Write a summary for Slack's general channel",
    "Write a summary for Slack’s general channel",
    "Create a ticket from the Slack outage",
]


@pytest.mark.parametrize("kind", ["do", "where"])
@pytest.mark.parametrize("text", ANOTHER_SYSTEMS_PLACE)
def test_a_place_source_or_audience_in_another_system_is_cant_do_whatever_the_preposition(
    kind: RowKind, text: str
):
    assert why_no_tool(kind, text) == cant(text[0].lower() + text[1:])


def test_a_place_after_a_comma_is_still_checked():
    text = "Write a summary for the team, in Slack"
    assert why_no_tool("do", text) == cant("write a summary for the team, in Slack")
    assert why_no_tool("where", text) == cant("put results in Slack")


@pytest.mark.parametrize("kind", ["do", "where"])
@pytest.mark.parametrize(
    "text",
    [
        "Write a summary for the team",
        "Write a summary of the GitHub releases",
        "Create a ticket for the Teams outage",
        "Write a summary about the Slack migration",
        "Create one ticket for the GitLab access review",
        "Write a summary (short)",
        "Write a summary of the Teams outage tickets",
        "Create a ticket about the Slack rollout",
        "Create a ticket for the Entra incident",
        "Write a summary of the Slack tickets",
    ],
)
def test_another_system_named_only_as_the_topic_stays_as_the_model_said(kind: RowKind, text: str):
    assert why_no_tool(kind, text) is None


def test_a_possessive_after_a_system_still_names_it_and_teams_needs_a_capital():
    assert why_no_tool("where", "Slack's channel") == cant("put results in Slack's channel")
    assert why_no_tool("look_for", "Users from Entra's directory") == cant("read Entra")
    assert why_no_tool("do", "Write a summary for the teams's lead") is None


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Attached to ticket MOCK-12", "attach to ticket MOCK-12"),
        ("Attached to MOCK-12", "attach to MOCK-12"),
        ("Attached to Jira project MOCK", "attach to Jira project MOCK"),
        ("Copied to MOCK-12", "copy to MOCK-12"),
        ("Forwarded to Jira project MOCK", "forward to Jira project MOCK"),
        ("Exported to Jira project MOCK", "export to Jira project MOCK"),
        ("Uploaded to Jira project MOCK", "upload to Jira project MOCK"),
        ("Posted to MOCK-12", "post to MOCK-12"),
        ("Sent to the ticket", "send to the ticket"),
    ],
)
def test_a_past_form_before_a_ticket_already_there_or_a_write_jira_lacks_is_cant_do(
    text: str, what: str
):
    assert (why_no_tool("where", text), why_no_tool("do", text)) == (cant(what), cant(what))


def test_results_put_in_a_ticket_already_there_are_cant_do_but_reading_it_is_not():
    assert why_no_tool("where", "Summarised in MOCK-12") == cant("summarise in MOCK-12")
    assert why_no_tool("do", "Summarised in MOCK-12") is None


def test_a_past_form_before_a_new_ticket_stays_as_the_model_said():
    assert why_no_tool("where", "Posted in a new ticket in MOCK") is None


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("do", "Create a ticket to"),
        ("do", "Write a summary to"),
        ("schedule", "Every day, write a summary to"),
        ("where", "Posted to"),
        ("where", "I want it sent to"),
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
