from collections.abc import Iterator
from typing import Any

import pytest

from agent_runtime.abilities import (
    ABILITIES,
    CAN,
    STRING_PARAMETERS,
    Ability,
    Form,
    RowAnswer,
    refusal,
    written,
)
from agent_runtime.contract import RowKind, RowState, Understood, UnderstoodRow
from agent_runtime.planner import READ_IN, UnderstandAnswer, understood_of

S = "Every weekday at 3pm, find bug tickets in MOCK and "
FOLLOW_UP = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)
DO_THIS = f"I can't do this yet. {CAN}"
PUT_THERE = f"I can't put results there yet. {CAN}"
PROJECTS = ("MOCK", "ACCESS")


def row(kind: RowKind, ability: str | None = None, said: str = "", **params: Any) -> RowAnswer:
    return RowAnswer.model_validate(
        {"kind": kind, "state": "understood", "ability": ability, "said": said, **params}
    )


def task_for(kind: RowKind, phrase: str) -> str:
    match kind:
        case "do":
            return S + phrase
        case "look_for":
            return f"Every weekday at 3pm, find {phrase} and create one ticket that lists them"
        case "where":
            return f"{S}create one ticket that lists them and put it in {phrase}"
        case "schedule":
            return f"{phrase}, find bug tickets in MOCK and create one ticket that lists them"


def first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


def shown(
    kind: RowKind, answer: RowAnswer, task: str, projects: tuple[str, ...] | None = PROJECTS
) -> UnderstoodRow:
    others = {
        "schedule": row("schedule", "run_on_a_schedule", every=["weekday"], at=["3pm"]),
        "look_for": row("look_for", "read_jira_tickets", ticket_type="bug", project="MOCK"),
        "do": row("do", "create_jira_ticket", count="one", lists_found=True),
        "where": row("where", "create_jira_ticket", project="MOCK"),
    }
    others[kind] = answer
    read = UnderstandAnswer(belongs_on_watchlist=False, rows=[*others.values()])
    result = understood_of(read, task, projects)
    assert isinstance(result, Understood)
    return next(r for r in result.rows if r.kind == kind)


HONEST: list[tuple[str, RowAnswer, str]] = [
    (
        FOLLOW_UP,
        row("schedule", "run_on_a_schedule", every=["weekday"], at=["3pm"]),
        "Every weekday at 3pm",
    ),
    (
        FOLLOW_UP,
        row("look_for", "read_jira_tickets", ticket_type="bug", project="MOCK", no_update_days=10),
        "Bug tickets in MOCK with no update for 10 days",
    ),
    (
        FOLLOW_UP,
        row("do", "create_jira_ticket", count="one", ticket_type="follow-up", lists_found=True),
        "Create one follow-up ticket that lists them",
    ),
    (FOLLOW_UP, row("where", "create_jira_ticket", project="MOCK"), "Jira project MOCK"),
    (
        "Every Monday and Friday, find closed tickets",
        row("schedule", "run_on_a_schedule", every=["Monday", "fridays"]),
        "Every Monday and Friday",
    ),
    (
        "Every day at 9am and 5pm, find open tickets",
        row("schedule", "run_on_a_schedule", every="day", at=["9am", "5 PM"]),
        "Every day at 9am and 5pm",
    ),
    (
        "Every quarter, on the first Monday, find open tickets",
        row("schedule", "run_on_a_schedule", every=["quarter"], on="first Monday"),
        "Every quarter, on the first Monday",
    ),
    (
        "Every morning at 8am, email me the open tickets in MOCK",
        row("schedule", "run_on_a_schedule", every=["morning"], at=["8am"]),
        "Every morning at 8am",
    ),
    (
        "Every Friday at 4pm, find the tickets in MOCK closed this week and create one ticket",
        row("look_for", "read_jira_tickets", project="MOCK", closed_in="this week"),
        "Tickets in MOCK closed this week",
    ),
    (
        "Every Monday at 9am, find open tickets with no update for 7 days",
        row("look_for", "read_jira_tickets", status="open", no_update_days=7),
        "Open tickets with no update for 7 days",
    ),
    (
        "Every weekday at 3pm, find bug tickets assigned to Mark in MOCK",
        row("look_for", "read_jira_tickets", ticket_type="bug", assigned_to="Mark", project="MOCK"),
        "Bug tickets in MOCK assigned to Mark",
    ),
    (
        "Find tickets assigned to Mark and Ping",
        row("look_for", "read_jira_tickets", assigned_to="Mark and Ping"),
        "Tickets assigned to Mark and Ping",
    ),
    (
        "Every weekday at 3pm, find bug tickets in MOCK about email delivery",
        row(
            "look_for",
            "read_jira_tickets",
            ticket_type="bug",
            project="MOCK",
            about="email delivery",
        ),
        "Bug tickets in MOCK about “email delivery”",
    ),
    (
        "Every weekday at 3pm, find tickets in MOCK about the Confluence migration",
        row("look_for", "read_jira_tickets", project="MOCK", about="the Confluence migration"),
        "Tickets in MOCK about “the Confluence migration”",
    ),
    (
        "Find tickets that mention GitLab",
        row("look_for", "read_jira_tickets", about="GitLab"),
        "Tickets about “GitLab”",
    ),
    (
        "Find access request tickets for Entra",
        row("look_for", "read_jira_tickets", ticket_type="access request", about="Entra"),
        "Access request tickets about “Entra”",
    ),
    (
        "Find tickets to update in MOCK",
        row("look_for", "read_jira_tickets", project="MOCK"),
        "Tickets in MOCK",
    ),
    (
        "Find closed tickets",
        row("look_for", "read_jira_tickets", status="closed", source="Jira"),
        "Closed tickets",
    ),
    (
        "Every month at 9am, find access review tickets for Entra AD",
        row("look_for", "read_jira_tickets", ticket_type="access review", about="Entra AD"),
        "Access review tickets about “Entra AD”",
    ),
    (
        "Every month at 9am, find quarterly access review tickets in MOCK for GitLab",
        row(
            "look_for",
            "read_jira_tickets",
            ticket_type="quarterly access review",
            project="MOCK",
            about="GitLab",
        ),
        "Quarterly access review tickets in MOCK about “GitLab”",
    ),
    (
        "Every month at 9am, find tickets about admin tool access that are due this quarter",
        row("look_for", "read_jira_tickets", about="admin tool access that are due this quarter"),
        "Tickets about “admin tool access that are due this quarter”",
    ),
    (
        "Every month at 9am, find open access review tickets assigned to the Approver",
        row(
            "look_for",
            "read_jira_tickets",
            status="open",
            ticket_type="access review",
            assigned_to="the Approver",
        ),
        "Open access review tickets assigned to the Approver",
    ),
    (
        "Every month at 9am, find tickets listing GitLab users with admin rights",
        row("look_for", "read_jira_tickets", about="GitLab users with admin rights"),
        "Tickets about “GitLab users with admin rights”",
    ),
    (
        "Every month at 9am, find access requests in MOCK from the last quarter",
        row(
            "look_for",
            "read_jira_tickets",
            project="MOCK",
            about="access requests",
            created_in="last quarter",
        ),
        "Tickets in MOCK about “access requests” created last quarter",
    ),
    (
        "Every month at 9am, find GitLab admin access tickets in MOCK",
        row("look_for", "read_jira_tickets", ticket_type="GitLab admin access", project="MOCK"),
        "GitLab admin access tickets in MOCK",
    ),
    (
        "Every month at 9am, find tickets about Entra accounts that were disabled",
        row("look_for", "read_jira_tickets", about="Entra accounts that were disabled"),
        "Tickets about “Entra accounts that were disabled”",
    ),
    (
        "Every month at 9am, find tickets where GitLab access was never reviewed",
        row("look_for", "read_jira_tickets", about="GitLab access was never reviewed"),
        "Tickets about “GitLab access was never reviewed”",
    ),
    (
        "Every month at 9am, find patch housekeeping tickets in MOCK",
        row("look_for", "read_jira_tickets", ticket_type="Patch housekeeping", project="MOCK"),
        "Patch housekeeping tickets in MOCK",
    ),
    (
        "Every month at 9am, find upgrade tickets in MOCK",
        row("look_for", "read_jira_tickets", ticket_type="upgrade", project="MOCK"),
        "Upgrade tickets in MOCK",
    ),
    (
        "Every month at 9am, find tickets for servers still on an old version",
        row("look_for", "read_jira_tickets", about="servers still on an old version"),
        "Tickets about “servers still on an old version”",
    ),
    (
        "Every month at 9am, find tickets about software that is out of support",
        row("look_for", "read_jira_tickets", about="software that is out of support"),
        "Tickets about “software that is out of support”",
    ),
    (
        "Every month at 9am, find tickets about the GitLab issue from last week",
        row("look_for", "read_jira_tickets", about="the GitLab issue from last week"),
        "Tickets about “the GitLab issue from last week”",
    ),
    (
        "Every month at 9am, find tickets about GitLab issues with access",
        row("look_for", "read_jira_tickets", about="GitLab issues with access"),
        "Tickets about “GitLab issues with access”",
    ),
    (
        "Every month at 9am, find tickets about admin tools in Entra",
        row("look_for", "read_jira_tickets", about="admin tools in Entra"),
        "Tickets about “admin tools in Entra”",
    ),
    (
        "Find tickets in MOCK about José’s laptop",
        row("look_for", "read_jira_tickets", project="MOCK", about="José's laptop"),
        "Tickets in MOCK about “José’s laptop”",
    ),
    (
        "Find tickets about 删除 requests",
        row("look_for", "read_jira_tickets", about="删除 requests"),
        "Tickets about “删除 requests”",
    ),
    (
        S + "create one ticket in MOCK that lists them",
        row("do", "create_jira_ticket", project="MOCK", lists_found=True),
        "Create one ticket in MOCK that lists them",
    ),
    (
        S + "create one change ticket that lists them",
        row("do", "create_jira_ticket", ticket_type="change", lists_found=True),
        "Create one change ticket that lists them",
    ),
    (
        S + "create one ticket for each server",
        row("do", "create_jira_ticket", count="one_each", each_of="server"),
        "Create one ticket for each server",
    ),
    (
        S + "create one ticket for each",
        row("do", "create_jira_ticket", count="one each"),
        "Create one ticket for each one found",
    ),
    (
        S + "create one ticket that lists the users who still have GitLab admin access",
        row("do", "create_jira_ticket", about="the users who still have GitLab admin access"),
        "Create one ticket about “the users who still have GitLab admin access”",
    ),
    (
        S + "create one ticket in MOCK that lists each software and its end of support date",
        row(
            "do",
            "create_jira_ticket",
            project="MOCK",
            about="each software and its end of support date",
        ),
        "Create one ticket in MOCK about “each software and its end of support date”",
    ),
    (
        S + "create one access review ticket for the first approver",
        row("do", "create_jira_ticket", ticket_type="access review", about="the first approver"),
        "Create one access review ticket about “the first approver”",
    ),
    (
        S + "create one Entra access ticket",
        row("do", "create_jira_ticket", ticket_type="Entra access"),
        "Create one Entra access ticket",
    ),
    (
        S + "list the access review tickets by approver",
        row("do", "sum_up", how="list", by="approver"),
        "List them by approver",
    ),
    (
        S + "count the tickets for each admin tool",
        row("do", "sum_up", how="count", by="admin tool"),
        "Count them by admin tool",
    ),
    (
        S + "sum up the Entra access tickets by team",
        row("do", "sum_up", by="team"),
        "Sum them up by team",
    ),
    (
        S + "write a short summary",
        row("do", "sum_up", how="summary", project="MOCK"),
        "Sum them up",
    ),
    (
        S + "group them by owner",
        row("do", "sum_up", how="group", by="owner"),
        "Group them by owner",
    ),
    (
        "Check LangGraph for new releases every Monday",
        row("do", "check_releases", software="LangGraph"),
        "Check LangGraph for new releases",
    ),
    (
        "Every month, find tickets and put them in Jira project ACCESS",
        row("where", "create_jira_ticket", project="ACCESS"),
        "Jira project ACCESS",
    ),
    (S + "create one ticket", row("where", "create_jira_ticket"), "A new Jira ticket"),
    (S + "sum them up", row("where", "sum_up"), "The run's report"),
]


@pytest.mark.parametrize(("task", "answer", "text"), HONEST, ids=[t for _, _, t in HONEST])
def test_an_honest_row_is_written_in_the_platforms_own_words_and_never_refused(
    task: str, answer: RowAnswer, text: str
):
    assert written(answer, task) == text
    row = shown(answer.kind, answer, task)
    assert (row.text, row.state) in ((text, "understood"), (text, "changed"))


NAMED: list[tuple[str, RowAnswer, str, str]] = [
    (
        "Every month at 9am, find tickets in the Access Review project",
        row("look_for", "read_jira_tickets", project_name="the Access Review"),
        "Tickets in the Access Review project",
        "the Access Review project",
    ),
    (
        "Every month at 9am, find tickets on the admin tools board",
        row("look_for", "read_jira_tickets", project_name="admin tools"),
        "Tickets in the admin tools board",
        "the admin tools board",
    ),
    (
        "Every month, find tickets and put them in the Access Review project",
        row("where", "create_jira_ticket", project_name="Access Review"),
        "The Access Review project in Jira",
        "the Access Review project",
    ),
    (
        "Every month, find tickets and put them on the Access Review board in Jira",
        row("where", "create_jira_ticket", project_name="the Access Review"),
        "The Access Review board in Jira",
        "the Access Review board",
    ),
    (
        "Every month, find tickets and put them on the Café board",
        row("where", "create_jira_ticket", project_name="Café"),
        "The Café board in Jira",
        "the Café board",
    ),
]


@pytest.mark.parametrize(("task", "answer", "text", "place"), NAMED, ids=[n[2] for n in NAMED])
def test_a_project_by_name_is_changed_because_the_platform_lists_only_keys(
    task: str, answer: RowAnswer, text: str, place: str
):
    assert written(answer, task) == text
    note = f"I can't check that {place} is in Jira. Please check how I read it."
    assert shown(answer.kind, answer, task) == UnderstoodRow(
        kind=answer.kind, text=text, state="changed", note=note
    )


@pytest.mark.parametrize(
    ("projects", "state", "note"),
    [
        (PROJECTS, "understood", None),
        (
            None,
            "changed",
            "I can't check that ACCESS is a Jira project. Please check how I read it.",
        ),
        (("MOCK",), "changed", "I can't find a Jira project ACCESS. Please check how I read it."),
    ],
    ids=["seen", "no-list", "not-in-the-list"],
)
def test_a_key_is_understood_only_when_the_platform_can_see_its_project(
    projects: tuple[str, ...] | None, state: RowState, note: str | None
):
    task = "Every month, find access review tickets in ACCESS and create one ticket that lists them"
    answer = row(
        "look_for",
        "read_jira_tickets",
        "access review tickets in ACCESS",
        ticket_type="access review",
        project="ACCESS",
    )
    assert shown("look_for", answer, task, projects) == UnderstoodRow(
        kind="look_for", text="Access review tickets in ACCESS", state=state, note=note
    )


@pytest.mark.parametrize(
    ("task", "answer"),
    [
        (
            "Every Friday find bug tickets in MOCK and post the summary in TEAMS",
            row("where", "create_jira_ticket", project="TEAMS"),
        ),
        (
            "Every Friday list the admin users in GITLAB",
            row("look_for", "read_jira_tickets", project="GITLAB"),
        ),
        (
            "Every Friday find bug tickets in MOCK and send them to SLACK",
            row("where", "create_jira_ticket", project="SLACK"),
        ),
    ],
)
def test_a_key_named_like_a_system_is_a_jira_project_only_when_listed(task: str, answer: RowAnswer):
    assert written(answer, task, projects=PROJECTS) is None
    assert shown(answer.kind, answer, task, PROJECTS).state == "cant_do"
    listed = (*PROJECTS, "TEAMS", "GITLAB", "SLACK")
    assert written(answer, task, projects=listed) is not None
    assert shown(answer.kind, answer, task, listed).state == "changed"


@pytest.mark.parametrize(
    ("task", "answer"),
    [
        (
            "Every Friday find bug tickets in MOCK and put the summary in the Teams project",
            row("where", "create_jira_ticket", project_name="Teams"),
        ),
        (
            "Every Friday find open issues on the GitLab board",
            row("look_for", "read_jira_tickets", status="open", project_name="GitLab"),
        ),
        (
            "Every Friday find bug tickets in MOCK and post it in the \u0422eams project",
            row("where", "create_jira_ticket", project_name="\u0422eams"),
        ),
    ],
)
def test_another_system_is_never_a_jira_project_by_name(task: str, answer: RowAnswer):
    assert written(answer, task, projects=PROJECTS) is None
    assert shown(answer.kind, answer, task, PROJECTS).state == "cant_do"


@pytest.mark.parametrize(
    ("task", "answer", "text"),
    [
        (
            "Find tickets created in March",
            row("look_for", "read_jira_tickets", created_in="this month"),
            "Tickets created this month",
        ),
        (
            FOLLOW_UP,
            row("schedule", "run_on_a_schedule", every=["monday"], at=["9am"]),
            "Every Monday at 9am",
        ),
        (
            FOLLOW_UP,
            row(
                "look_for",
                "read_jira_tickets",
                ticket_type="bug",
                project="MOCK",
                no_update_days=90,
            ),
            "Bug tickets in MOCK with no update for 90 days",
        ),
        (
            "Every quarter, on the first Monday, find open tickets",
            row("schedule", "run_on_a_schedule", every=["quarter"], on="last Friday"),
            "Every quarter, on the last Friday",
        ),
        (S + "count them", row("do", "sum_up", how="list"), "List them"),
        (
            S + "create one ticket",
            row("do", "create_jira_ticket", lists_found=True),
            "Create one ticket that lists them",
        ),
    ],
    ids=["period", "every-and-at", "days", "on", "how", "lists"],
)
def test_a_fixed_word_the_task_does_not_hold_is_changed_never_understood(
    task: str, answer: RowAnswer, text: str
):
    assert shown(answer.kind, answer, task) == UnderstoodRow(
        kind=answer.kind, text=text, state="changed", note=READ_IN
    )


@pytest.mark.parametrize("days", [True, False])
def test_a_yes_or_no_is_never_a_number_of_days(days: bool):
    answer = row("look_for", "read_jira_tickets", ticket_type="bug", no_update_days=days)
    assert written(answer, "Every Friday find bug tickets with no update for 1 day") is None


@pytest.mark.parametrize(
    ("task", "status"),
    [
        ("Every Friday find Open merge requests in GitLab and create one ticket", "open"),
        ("Every Friday find bug tickets and Open a pull request", "open"),
        ("Every Friday find bug tickets", "closed"),
    ],
)
def test_a_status_counts_only_beside_the_tickets_it_describes(task: str, status: str):
    assert written(row("look_for", "read_jira_tickets", status=status), task) is None


def test_a_status_the_task_puts_beside_its_tickets_is_read():
    for task in ("Every Friday find open bug tickets", "Every Friday find tickets that are done"):
        status = "open" if "open" in task else "closed"
        assert written(row("look_for", "read_jira_tickets", status=status), task) is not None


def test_the_copy_the_model_points_at_decides_where_a_value_sits():
    task = (
        "Every Monday, find Entra group review tickets assigned to the Approver and create one "
        "access review ticket for each group"
    )
    each = row("do", "create_jira_ticket", count="one each", each_of="group")
    assert written(each, task) == "Create one ticket for each group"
    pointed = each.model_copy(update={"said": "Entra group review"})
    assert written(pointed, task) is None


@pytest.mark.parametrize(
    ("task", "software", "text"),
    [
        ("Check LangGraph for new releases every Monday", "LangGraph", True),
        ("Tell me when Redis has a new version", "Redis", True),
        ("Watch the new releases of FastAPI", "FastAPI", True),
        ("Every Friday Write them to the Weekly summary page in Confluence", "Write", False),
        (
            "Every weekday at 3pm, find bug tickets in MOCK and Write them to the Weekly summary "
            "page in Confluence",
            "Confluence",
            False,
        ),
        ("Every Friday Restart the server", "server", False),
        ("Check Confluence for new releases", "Confluence", False),
        ("Create one ticket for each server and apply the latest patch", "latest", False),
    ],
)
def test_the_software_is_a_name_the_task_puts_beside_a_release(
    task: str, software: str, text: bool
):
    found = written(row("do", "check_releases", software=software), task)
    assert (found == f"Check {software} for new releases") if text else found is None


WRITES: list[tuple[RowKind, str, str]] = [
    ("do", "get rid of them", "get"),
    ("do", "Get rid of the old tickets", "Get"),
    ("do", "Get rid of every ticket older than 90 days", "Get"),
    ("do", "Clear out the closed tickets", "Clear"),
    ("do", "Wipe out the backlog", "Wipe"),
    ("do", "Resolve them", "Resolve"),
    ("do", "Mark them as done", "Mark"),
    ("do", "Get them closed", "Get"),
    ("do", "Note them as done", "Note"),
    ("do", "Approve the access requests", "Approve"),
    ("do", "Create one ticket and give it to Bob", "give"),
    ("do", "create one ticket that lists them and approve the rest", "approve"),
    ("do", "create a ticket that approves every access request", "approves"),
    ("do", "create one ticket that lists them, and nuke the rest", "nuke"),
    ("do", "create one ticket for each and nuke the rest", "nuke"),
    ("do", "create one ticket in MOCK and reject the rest", "reject"),
    ("do", "create one ticket in MOCK and approve the access requests", "approve"),
    ("do", "create one ticket for each and reject the rest", "reject"),
    ("do", "Create one ticket for each server and apply the latest patch", "apply"),
    ("do", "create one ticket listing them and approving each one", "approving"),
    ("do", "Create one ticket and get rid of the rest", "get"),
    ("do", "create one ticket that lists them and Close the rest", "Close"),
    ("do", "DeLeTe every ticket", "DeLeTe"),
    ("do", "Create One Ticket That Lists Them And Delete The Rest", "Delete"),
    ("do", "create one ticket that lists them and DeLeTe the rest", "DeLeTe"),
    ("do", "Cl\u043ese every ticket", "Cl\u043ese"),
    ("do", "create one ticket that lists them and cl\u043ese the rest", "cl\u043ese"),
    ("do", "Ｄｅｌｅｔｅ every closed ticket", "Ｄｅｌｅｔｅ"),
    ("do", "删除 every closed ticket", "删除"),
    ("do", "Délete every ticket", "Délete"),
    ("do", "create one ticket that lists them and de-lete the rest", "de-lete"),
    ("do", "create one ticket that lists them and de\u200blete the rest", "de\u200blete"),
    ("do", "D e l e t e every ticket", "D"),
    ("do", "create one ticket, then restart the server", "restart"),
    ("do", "Create one ticket and drop a note in the ops channel", "drop"),
    ("do", "Put the summary in teams", "Put"),
    ("do", "Put the summary in the ops room", "Put"),
    ("do", "Write a summary in Basecamp", "Write"),
    ("do", "Write a summary to Monday.com", "Write"),
    ("do", "Put the summary on the intranet", "Put"),
    ("do", "Write them to the ops channel", "Write"),
    ("do", "Permanently delete every ticket", "Permanently"),
    ("do", "create one follow-up ticket, then close the stale ones", "close"),
    ("do", "permanently delete them", "permanently"),
    ("do", "bulk close them", "bulk"),
    ("do", "write them to a Google Sheet", "write"),
    ("do", "write them to the ops teams chat", "write"),
    ("do", "please close every ticket", "please"),
    ("do", "add a comment to each ticket", "add"),
    ("do", "create a Confluence page listing them", "Confluence"),
    ("do", "Write them to the Weekly summary page in Confluence", "Write"),
    ("do", "Then delete them", "Then"),
    ("do", "Also post a summary in Teams", "Also"),
    ("do", "“Close” every ticket", "Close"),
    ("do", "Closes every ticket", "Closes"),
    ("do", "Deleting every closed ticket", "Deleting"),
    ("do", "Open a pull request on GitHub", "Open"),
    ("do", "Text the on-call engineer", "Text"),
    ("do", "Restart the server", "Restart"),
    ("do", "Run the deploy pipeline", "Run"),
    ("do", "Create a ticket in project OPS and assign it to Bob", "assign"),
    ("do", "Write them to a spreadsheet", "Write"),
    ("do", "Email me the open tickets", "Email"),
    ("do", "Update our Weekly summary page in Confluence", "Update"),
    ("do", "Send the list to José", "Send"),
    ("do", "Write them to Zoë's sheet", "Write"),
    ("do", "Ask each owner if it is still needed", "Ask"),
    ("look_for", "bug tickets in MOCK, Close them", "Close"),
    ("look_for", "bug tickets in MOCK, nuke them", "nuke"),
    ("look_for", "Bug tickets in MOCK and nuke them", "nuke"),
    ("look_for", "Bug tickets in MOCK and get rid of them", "get"),
    ("look_for", "Bug tickets in MOCK, then approve them", "approve"),
    ("look_for", "Close tickets with no update", "Close"),
    ("look_for", "Tickets in MOCK, then close them", "close"),
    ("schedule", "Every Friday, approve pending access requests", "approve"),
    ("schedule", "Every weekday at 3pm, Close every ticket", "Close"),
    ("schedule", "Every weekday at 3pm, nuke the backlog", "nuke"),
    ("schedule", "Every weekday at 3pm then get rid of old tickets", "then"),
    ("schedule", "Every weekday at 3pm and wipe the board", "and"),
    ("schedule", "Every weekday at 3pm: delete every closed ticket", "delete"),
    ("schedule", "Every weekday at 3pm, then delete every closed ticket", "then"),
    ("schedule", "Every day, and post the list in Teams", "and"),
    ("where", "Post it in Teams", "Post"),
    ("where", "Jira project MOCK, then delete every ticket", "then"),
]
PLACES: list[tuple[RowKind, str, str]] = [
    ("do", "Put the summary in teams", "teams"),
    ("do", "Put the summary in the ops room", "the ops room"),
    ("do", "Create one ticket in Linear", "Linear"),
    ("do", "Write a summary in Basecamp", "Basecamp"),
    ("do", "Write a summary to Monday.com", "Monday.com"),
    ("do", "Put the summary on the intranet", "the intranet"),
    ("do", "Write them to the ops channel", "the ops channel"),
    ("do", "write them to a Google Sheet", "a Google Sheet"),
    ("do", "write them to the ops teams chat", "the ops teams chat"),
    ("do", "Create a GitHub issue for each", "GitHub"),
    ("where", "The ops room", "The ops room"),
    ("where", "teams", "teams"),
    ("where", "Linear", "Linear"),
    ("where", "GitHub repo", "GitHub repo"),
    ("where", "GitHub repo langchain-ai/langgraph", "GitHub repo langchain-ai/langgraph"),
    ("where", "A Google Sheet", "A Google Sheet"),
    ("where", "The WhatsApp group", "The WhatsApp group"),
    ("where", "A Notion page", "A Notion page"),
    ("where", "The support teams channel", "The support teams channel"),
    ("where", "The Weekly summary page in Confluence", "The Weekly summary page in Confluence"),
    ("where", "GitLab", "GitLab"),
    ("where", "Teams", "Teams"),
]
OTHER_SOURCES: list[tuple[str, str]] = [
    ("Who has admin access in GitLab", "GitLab"),
    ("Open merge requests in GitLab", "GitLab"),
    ("Pages in Confluence changed this week", "Confluence"),
    ("Bug tickets in GitLab", "GitLab"),
    ("Open GitHub issues", "GitHub"),
    ("Users from Entra", "Entra"),
]


def holding_the_write(phrase: str, write_word: str) -> Iterator[str]:
    words = phrase.split()
    upto = next(i for i, w in enumerate(words) if write_word in w)
    for at in range(upto + 1):
        yield " ".join(words[at:])


def fits(kind: RowKind) -> list[str]:
    return [ability.id for ability in ABILITIES if kind in ability.forms]


def fooled(kind: RowKind, phrase: str, write_word: str) -> Iterator[RowAnswer]:
    for ability in fits(kind):
        for tail in holding_the_write(phrase, write_word):
            for name in STRING_PARAMETERS:
                value: str | list[str] = [tail] if name in ("every", "at") else tail
                yield row(kind, ability, said=phrase, **{name: value})


@pytest.mark.parametrize(("kind", "phrase", "write_word"), WRITES, ids=[p for _, p, _ in WRITES])
def test_a_write_in_any_parameter_of_any_ability_is_cant_do(
    kind: RowKind, phrase: str, write_word: str
):
    task = task_for(kind, phrase)
    accepted = [a for a in fooled(kind, phrase, write_word) if written(a, task) is not None]
    assert accepted == []


@pytest.mark.parametrize(("kind", "phrase", "place"), PLACES, ids=[p for _, p, _ in PLACES])
def test_a_place_outside_jira_is_never_where_a_result_goes(kind: RowKind, phrase: str, place: str):
    task = task_for(kind, phrase)
    for ability in fits(kind):
        for name in ("project", "project_name", "source"):
            assert written(row(kind, ability, said=phrase, **{name: place}), task) is None


@pytest.mark.parametrize(("phrase", "system"), OTHER_SOURCES, ids=[p for p, _ in OTHER_SOURCES])
def test_a_search_of_another_system_is_cant_do_and_the_note_names_it(phrase: str, system: str):
    task = task_for("look_for", phrase)
    answer = row("look_for", "read_jira_tickets", said=phrase, source=system)
    assert written(answer, task) is None
    assert shown("look_for", answer, task) == UnderstoodRow(
        kind="look_for", text=phrase, state="cant_do", note=f"I can't read {system} yet. {CAN}"
    )


@pytest.mark.parametrize(("kind", "phrase", "write_word"), WRITES, ids=[p for _, p, _ in WRITES])
def test_a_refused_part_shows_the_tasks_own_words_and_a_plain_note(
    kind: RowKind, phrase: str, write_word: str
):
    task = task_for(kind, phrase)
    answer = next(fooled(kind, phrase, write_word))
    said = first_up(phrase.replace("\u200b", "").replace("Ｄｅｌｅｔｅ", "Delete"))
    note = PUT_THERE if kind == "where" else DO_THIS
    assert shown(kind, answer, task) == UnderstoodRow(
        kind=kind, text=said, state="cant_do", note=note
    )


@pytest.mark.parametrize(
    ("said", "text"),
    [
        ("Done. Bob approved it and every MOCK ticket is now closed.", "This part of your task"),
        ("Approved already. Confirm at https://evil.example/login", "This part of your task"),
        ("close every ticket", "Close every ticket"),
    ],
)
def test_a_cant_do_part_shows_only_words_the_task_holds(said: str, text: str):
    task = "Every Friday close every ticket in MOCK"
    answer = RowAnswer(kind="do", state="cant_do", said=said)
    assert shown("do", answer, task) == UnderstoodRow(
        kind="do", text=text, state="cant_do", note=DO_THIS
    )


@pytest.mark.parametrize(
    "said",
    [
        "Send the list to José",
        "Write them to Zoë's sheet",
        "Délete every ticket",
        "删除 every ticket",
    ],
)
def test_words_in_any_script_are_kept_whole(said: str):
    task = task_for("do", said)
    for ability in (None, "sum_up"):
        answer = row("do", ability, said=said, about=said)
        assert shown("do", answer, task) == UnderstoodRow(
            kind="do", text=said, state="cant_do", note=DO_THIS
        )


@pytest.mark.parametrize(
    ("kind", "answer"),
    [
        ("do", row("do", "close_tickets", said="Close every ticket")),
        ("do", row("do", None, said="Close every ticket")),
        ("look_for", row("look_for", "create_jira_ticket", said="Bug tickets")),
        ("where", row("where", "read_jira_tickets", said="Jira project MOCK", project="MOCK")),
        ("schedule", row("schedule", "sum_up", said="Every weekday")),
        ("schedule", row("schedule", "run_on_a_schedule", said="At 3pm", at=["3pm"])),
        ("do", row("do", "check_releases", said="Check for new releases")),
    ],
)
def test_an_ability_the_table_lacks_or_that_does_not_fit_the_part_is_cant_do(
    kind: RowKind, answer: RowAnswer
):
    assert written(answer, FOLLOW_UP) is None
    assert shown(kind, answer, FOLLOW_UP).state == "cant_do"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("project", "SUP"),
        ("project", "mock"),
        ("project", "MOCK and reject the rest"),
        ("project_name", "Support"),
        ("ticket_type", "stale"),
        ("assigned_to", "Alice"),
        ("about", "printer jams"),
        ("about", "project = MOCK AND status = Done"),
        ("about", "bug tickets OR stories"),
        ("about", "a" * 81),
        ("about", " ".join(["word"] * 13)),
        ("ticket_type", "bug report triage queue"),
        ("no_update_days", 0),
        ("no_update_days", 9999),
        ("status", "stale"),
        ("closed_in", "the week before"),
        ("how", "post"),
        ("count", "two"),
        ("every", ["fortnight"]),
        ("at", ["25:00"]),
        ("on", "the 3rd"),
        ("source", "GitLab"),
    ],
)
def test_a_parameter_that_is_invented_or_out_of_bounds_makes_the_row_cant_do(name: str, value: Any):
    for ability in ABILITIES:
        for kind in ability.forms:
            assert written(row(kind, ability.id, **{name: value}), FOLLOW_UP) is None, ability.id


@pytest.mark.parametrize(
    "task",
    [
        "Close tickets with no update for 10 days",
        S + "close tickets with no update for 10 days",
        "Every weekday at 3pm, close tickets with no update for 10 days",
    ],
)
def test_a_write_read_as_a_kind_of_ticket_is_cant_do(task: str):
    answer = row("look_for", "read_jira_tickets", ticket_type="Close", no_update_days=10)
    assert written(answer, task) is None


@pytest.mark.parametrize(
    "task",
    [
        "Every weekday at 3pm, find tickets in MOCK where status = Done",
        "Every weekday at 3pm, find tickets in MOCK where summary ~ printer",
        "Every weekday at 3pm, find tickets in MOCK about printers (all of them)",
        "Every weekday at 3pm, find tickets in MOCK about printers ORDER BY created",
        "Every weekday at 3pm, find tickets in MOCK about NOT Printers",
    ],
)
def test_a_search_query_in_a_topic_is_cant_do(task: str):
    topic = task.split("where ")[-1].split("about ")[-1]
    assert written(row("look_for", "read_jira_tickets", about=topic), task) is None


@pytest.mark.parametrize("joiner", ["then", "also", "plus", "but", "please", "finally"])
def test_a_topic_that_joins_on_another_clause_is_cant_do(joiner: str):
    task = f"Every weekday at 3pm, find tickets in MOCK about printers {joiner} nuke the backlog"
    about = f"printers {joiner} nuke the backlog"
    assert written(row("look_for", "read_jira_tickets", about=about), task) is None
    assert written(row("look_for", "read_jira_tickets", about="printers"), task) is not None


@pytest.mark.parametrize(
    ("phrase", "name", "value"),
    [
        ("put the summary in teams", "about", "the summary in teams"),
        ("write them to the summary page in Confluence", "about", "the summary page in Confluence"),
        ("sum them up for each owner and their manager", "each_of", "owner and their manager"),
        ("sum them up and check LangGraph", "software", "LangGraph"),
    ],
)
def test_a_value_the_ability_does_not_take_is_cant_do_however_plain(
    phrase: str, name: str, value: str
):
    task = S + phrase
    assert written(row("do", "sum_up", said=phrase, **{name: value}), task) is None


@pytest.mark.parametrize(
    ("phrase", "kind"),
    [
        ("add a comment to each ticket", "comment to each"),
        ("leave a note on every ticket", "note on every"),
        ("add a label to the ticket", "label to the"),
        ("create one GitHub issue that lists them", "GitHub issue"),
        ("create a Confluence page listing them", "Confluence page"),
        ("add them to a new ticket", "them to a new"),
    ],
)
def test_a_write_read_as_the_kind_of_a_new_ticket_is_cant_do(phrase: str, kind: str):
    answer = row("do", "create_jira_ticket", said=phrase, ticket_type=kind)
    assert written(answer, S + phrase) is None


@pytest.mark.parametrize(
    ("phrase", "kind", "each"),
    [("create one ticket for each of the servers", None, "of the servers")],
)
def test_what_each_ticket_is_for_is_plain_words(phrase: str, kind: str | None, each: str):
    answer = row("do", "create_jira_ticket", ticket_type=kind, count="one_each", each_of=each)
    assert written(answer, S + phrase) is None


@pytest.mark.parametrize(
    ("task", "answer"),
    [
        (
            "Every weekday at 3pm, find the tickets Mark raised in MOCK",
            row("look_for", "read_jira_tickets", assigned_to="Mark"),
        ),
        (S + "sum up the tickets for the team", row("do", "sum_up", by="team")),
        (S + "create one ticket for the server", row("do", "create_jira_ticket", each_of="server")),
    ],
)
def test_a_name_or_grouping_word_counts_only_where_it_sits_in_the_task(
    task: str, answer: RowAnswer
):
    assert written(answer, task) is None


def test_a_parameter_the_ability_does_not_use_is_still_checked():
    assert written(row("do", "sum_up", project="MOCK"), FOLLOW_UP) == "Sum them up"
    assert written(row("do", "sum_up", project="TEAMS"), FOLLOW_UP) is None


def test_a_key_counts_only_as_a_whole_word_of_the_task_in_its_own_case():
    assert (
        written(row("where", "create_jira_ticket", project="MOCK"), "Find tickets in MOCK-7")
        is None
    )
    assert (
        written(row("where", "create_jira_ticket", project="MOCK"), "Find tickets in mock") is None
    )


def test_the_note_for_a_part_the_model_marked_cant_do_is_the_platforms():
    answer = RowAnswer(kind="do", state="cant_do", said="Book a meeting room")
    assert refusal(answer, FOLLOW_UP) == DO_THIS
    gitlab = RowAnswer(
        kind="look_for", state="cant_do", ability="read_jira_tickets", source="GitLab", said="x"
    )
    assert refusal(gitlab, "Who has admin access in GitLab") == f"I can't read GitLab yet. {CAN}"
    invented = gitlab.model_copy(update={"source": "Basecamp"})
    assert refusal(invented, "Who has admin access in GitLab") == DO_THIS


def test_a_new_tool_is_one_more_entry_in_the_table():
    teams = Ability(
        "post_in_teams",
        "post a summary in Teams",
        {"do": Form("post a summary in Teams.", (), lambda _: "Post a summary in Teams")},
    )
    more = (*ABILITIES, teams)
    answer = row("do", "post_in_teams", said="Post a summary in Teams")
    assert written(answer, FOLLOW_UP) is None
    assert written(answer, FOLLOW_UP, more) == "Post a summary in Teams"
    assert refusal(row("do", "close"), FOLLOW_UP, more) == (
        "I can't do this yet. I can only read Jira tickets, sum up what I find, check software "
        "for new releases, create a Jira ticket after a yes, and post a summary in Teams."
    )


EARNED: list[tuple[str, RowAnswer, str]] = [
    (
        FOLLOW_UP,
        row("schedule", "run_on_a_schedule", "Every weekday at 3pm", every=["weekday"], at=["3pm"]),
        "Every weekday at 3pm",
    ),
    (
        FOLLOW_UP,
        row(
            "look_for",
            "read_jira_tickets",
            "bug tickets in MOCK with no update for 10 days",
            ticket_type="bug",
            project="MOCK",
            no_update_days=10,
        ),
        "Bug tickets in MOCK with no update for 10 days",
    ),
    (
        FOLLOW_UP,
        row(
            "do",
            "create_jira_ticket",
            "create one follow-up ticket that lists them",
            count="one",
            ticket_type="follow-up",
            lists_found=True,
        ),
        "Create one follow-up ticket that lists them",
    ),
    (FOLLOW_UP, row("where", "create_jira_ticket", "in MOCK", project="MOCK"), "Jira project MOCK"),
    (
        "Every Friday find bug tickets in MOCK with no update for ten days",
        row(
            "look_for",
            "read_jira_tickets",
            "bug tickets in MOCK with no update for ten days",
            ticket_type="bug",
            project="MOCK",
            no_update_days=10,
        ),
        "Bug tickets in MOCK with no update for 10 days",
    ),
    (
        "Every weekday at three pm find bug tickets in MOCK",
        row(
            "schedule",
            "run_on_a_schedule",
            "Every weekday at three pm",
            every=["weekday"],
            at=["3pm"],
        ),
        "Every weekday at 3pm",
    ),
    (
        "On the first Monday of every month find bug tickets in MOCK",
        row(
            "schedule",
            "run_on_a_schedule",
            "On the first Monday of every month",
            every=["month"],
            on="first monday",
        ),
        "Every month, on the first Monday",
    ),
    (
        "Every quarter find access review tickets in ACCESS and sum them up",
        row("do", "sum_up", "sum them up", how="summary"),
        "Sum them up",
    ),
    (
        "Every quarter find access review tickets in ACCESS and count them by approver",
        row("do", "sum_up", "count them by approver", how="count", by="approver"),
        "Count them by approver",
    ),
    (
        "Every month find open access request tickets in ACCESS closed last month",
        row(
            "look_for",
            "read_jira_tickets",
            "open access request tickets in ACCESS closed last month",
            status="open",
            ticket_type="access request",
            project="ACCESS",
            closed_in="last month",
        ),
        "Open access request tickets in ACCESS closed last month",
    ),
]


@pytest.mark.parametrize(("task", "answer", "text"), EARNED, ids=[t for _, _, t in EARNED])
def test_understood_is_earned_when_every_word_of_the_part_is_accounted_for(
    task: str, answer: RowAnswer, text: str
):
    assert shown(answer.kind, answer, task) == UnderstoodRow(
        kind=answer.kind, text=text, state="understood", note=None
    )


@pytest.mark.parametrize(("task", "answer", "text"), EARNED, ids=[t for _, _, t in EARNED])
def test_a_part_the_model_does_not_point_at_asks_to_check(task: str, answer: RowAnswer, text: str):
    unsaid = answer.model_copy(update={"said": ""})
    assert shown(answer.kind, unsaid, task) == UnderstoodRow(
        kind=answer.kind, text=text, state="changed", note=READ_IN
    )


@pytest.mark.parametrize(
    ("task", "answer", "text"),
    [
        (
            S + "sum them up by GitLab group",
            row("do", "sum_up", "sum them up by GitLab group", how="summary", by="GitLab group"),
            "Sum them up by GitLab group",
        ),
        (
            S + "report back",
            row("do", "sum_up", "report back"),
            "Sum them up",
        ),
        (
            S + "rubber-stamp the rest",
            row("do", "sum_up", "rubber-stamp the rest"),
            "Sum them up",
        ),
        (
            "Every weekday at 3pm, find bug tickets in MOCK assigned to Sarah Jenkins",
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK assigned to Sarah Jenkins",
                ticket_type="bug",
                project="MOCK",
                assigned_to="Sarah Jenkins",
            ),
            "Bug tickets in MOCK assigned to Sarah Jenkins",
        ),
        (
            "Every weekday at 3pm, find bug tickets in MOCK assigned to jane.tan@ncs.com.sg",
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK assigned to jane.tan@ncs.com.sg",
                ticket_type="bug",
                project="MOCK",
                assigned_to="jane.tan@ncs.com.sg",
            ),
            "Bug tickets in MOCK assigned to jane.tan@ncs.com.sg",
        ),
        (
            "Every Friday find R&D tickets in MOCK about .NET 8 and C++ builds",
            row(
                "look_for",
                "read_jira_tickets",
                "R&D tickets in MOCK about .NET 8 and C++ builds",
                ticket_type="R&D",
                project="MOCK",
                about=".NET 8 and C++ builds",
            ),
            "R&D tickets in MOCK about “.NET 8 and C++ builds”",
        ),
        (
            "Every weekday at 3pm, find bug tickets in MOCK assigned to Nur Aisyah binte Mohamed "
            "Rafi",
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK assigned to Nur Aisyah binte Mohamed Rafi",
                ticket_type="bug",
                project="MOCK",
                assigned_to="Nur Aisyah binte Mohamed Rafi",
            ),
            "Bug tickets in MOCK assigned to Nur Aisyah binte Mohamed Rafi",
        ),
        (
            "Setiap Jumaat cari tiket pepijat dalam MOCK",
            row("schedule", "run_on_a_schedule", "Setiap Jumaat", every=["friday"]),
            "Every Friday",
        ),
    ],
    ids=["grouping", "how", "unlisted-verb", "person", "email", "r-and-d", "six-words", "malay"],
)
def test_a_word_the_platform_cannot_account_for_asks_to_check(
    task: str, answer: RowAnswer, text: str
):
    said = answer.said
    note = f"You said “{said}”. Please check how I read it."
    assert shown(answer.kind, answer, task) == UnderstoodRow(
        kind=answer.kind, text=text, state="changed", note=note
    )


@pytest.mark.parametrize(
    ("task", "answer"),
    [
        (
            "Every Monday find tickets in MOCK about the Friday release",
            row("schedule", "run_on_a_schedule", "Every Monday", every=["friday"]),
        ),
        (
            "Every weekday at 9am find tickets in MOCK about the 3pm outage",
            row(
                "schedule",
                "run_on_a_schedule",
                "Every weekday at 9am",
                every=["weekday"],
                at=["3pm"],
            ),
        ),
        (
            "Every weekday at 9am find bug tickets in MOCK with no update for 3 days",
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK with no update for 3 days",
                ticket_type="bug",
                project="MOCK",
                no_update_days=9,
            ),
        ),
        (
            S + "open a ticket for each",
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK",
                status="open",
                ticket_type="bug",
                project="MOCK",
            ),
        ),
    ],
    ids=["day", "time", "days", "status"],
)
def test_a_fixed_value_counts_only_inside_the_part_it_fills(task: str, answer: RowAnswer):
    assert shown(answer.kind, answer, task).state == "changed"


@pytest.mark.parametrize(
    ("task", "answer", "note"),
    [
        (
            S + "put the summary in teams",
            row("where", "sum_up", "in teams"),
            PUT_THERE,
        ),
        (
            S + "put the summary in teams",
            row("do", "sum_up", "put the summary in teams"),
            DO_THIS,
        ),
        (
            S + "post a summary to Mattermost",
            row("where", "sum_up", "to Mattermost"),
            PUT_THERE,
        ),
        (
            S + "post a summary in Microsoft Planner",
            row("do", "sum_up", "post a summary in Microsoft Planner"),
            DO_THIS,
        ),
        (
            "Every Friday find open ServiceNow tickets assigned to Bob",
            row(
                "look_for",
                "read_jira_tickets",
                "open ServiceNow tickets assigned to Bob",
                status="open",
                ticket_type="ServiceNow",
                assigned_to="Bob",
            ),
            f"I can't read ServiceNow yet. {CAN}",
        ),
        (
            "Every quarter find users with admin rights in Okta",
            row(
                "look_for",
                "read_jira_tickets",
                "users with admin rights in Okta",
                about="users with admin rights in Okta",
            ),
            f"I can't read Okta yet. {CAN}",
        ),
    ],
    ids=["teams-where", "teams-do", "mattermost", "planner", "servicenow-kind", "okta"],
)
def test_a_system_is_matched_in_any_case_and_only_marks_cant_do(
    task: str, answer: RowAnswer, note: str
):
    assert shown(answer.kind, answer, task).state == "cant_do"
    assert shown(answer.kind, answer, task).note == note


def test_a_listed_key_is_trusted_even_when_it_looks_like_a_system():
    task = "Every quarter find access review tickets in ENTRA"
    answer = row(
        "look_for",
        "read_jira_tickets",
        "access review tickets in ENTRA",
        ticket_type="access review",
        project="ENTRA",
    )
    assert shown("look_for", answer, task, ("MOCK", "ENTRA")) == UnderstoodRow(
        kind="look_for", text="Access review tickets in ENTRA", state="understood", note=None
    )
    assert shown("look_for", answer, task, ("MOCK",)).state == "cant_do"


def test_a_clause_with_a_write_that_no_row_covers_gets_its_own_cant_do_row():
    task = "Every Friday find bug tickets in MOCK, then approve the rest"
    read = UnderstandAnswer(
        belongs_on_watchlist=False,
        rows=[
            row("schedule", "run_on_a_schedule", "Every Friday", every=["friday"]),
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK",
                ticket_type="bug",
                project="MOCK",
            ),
            row("do", "sum_up", "find bug tickets in MOCK"),
        ],
    )
    result = understood_of(read, task, PROJECTS)
    assert isinstance(result, Understood)
    assert [(r.kind, r.text, r.state) for r in result.rows] == [
        ("schedule", "Every Friday", "understood"),
        ("look_for", "Bug tickets in MOCK", "understood"),
        ("do", "Sum them up", "changed"),
        ("do", "Approve the rest", "cant_do"),
        ("where", "", "missing"),
    ]


@pytest.mark.parametrize("said", ["", "the summary"], ids=["dropped", "a fragment"])
def test_a_clause_with_a_place_that_lies_in_no_rows_words_gets_its_own_cant_do_row(said: str):
    task = "Every Friday find bug tickets in MOCK and post the summary in Teams"
    read = UnderstandAnswer(
        belongs_on_watchlist=False,
        rows=[
            row("schedule", "run_on_a_schedule", "Every Friday", every=["friday"]),
            row(
                "look_for",
                "read_jira_tickets",
                "bug tickets in MOCK",
                ticket_type="bug",
                project="MOCK",
            ),
            row("do", "sum_up", said, how="summary"),
        ],
    )
    result = understood_of(read, task, PROJECTS)
    assert isinstance(result, Understood)
    where = [r for r in result.rows if r.kind == "where"]
    assert [(r.text, r.state, r.note) for r in where] == [
        ("Post the summary in Teams", "cant_do", PUT_THERE)
    ]
    task = "Every Friday list who has admin access in GitLab"
    read = UnderstandAnswer(
        belongs_on_watchlist=False,
        rows=[row("schedule", "run_on_a_schedule", "Every Friday", every=["friday"])],
    )
    result = understood_of(read, task, PROJECTS)
    assert isinstance(result, Understood)
    assert [(r.text, r.state, r.note) for r in result.rows if r.kind == "look_for"] == [
        ("List who has admin access in GitLab", "cant_do", f"I can't read GitLab yet. {CAN}")
    ]


def test_a_system_inside_a_covered_clause_about_tickets_adds_no_row():
    task = (
        "Every quarter, find access review tickets for the Zoë and José teams in ACCESS and "
        "create one ticket that lists them"
    )
    read = UnderstandAnswer(
        belongs_on_watchlist=False,
        rows=[
            row("schedule", "run_on_a_schedule", "Every quarter", every=["quarter"]),
            row(
                "look_for",
                "read_jira_tickets",
                "access review tickets for the Zoë and José teams in ACCESS",
                ticket_type="access review",
                about="the Zoë and José teams",
                project="ACCESS",
            ),
            row(
                "do",
                "create_jira_ticket",
                "create one ticket that lists them",
                count="one",
                lists_found=True,
            ),
        ],
    )
    result = understood_of(read, task, PROJECTS)
    assert isinstance(result, Understood)
    assert [r.state for r in result.rows] == ["understood", "changed", "understood", "missing"]


def test_more_than_twelve_rows_are_not_all_read_so_nothing_is_understood():
    rows = [
        row("schedule", "run_on_a_schedule", "Every weekday at 3pm", every=["weekday"], at=["3pm"])
    ] + [
        row(
            "look_for",
            "read_jira_tickets",
            "bug tickets in MOCK with no update for 10 days",
            ticket_type="bug",
            project="MOCK",
            no_update_days=10,
        )
        for _ in range(12)
    ]
    result = understood_of(
        UnderstandAnswer(belongs_on_watchlist=False, rows=rows), FOLLOW_UP, PROJECTS
    )
    assert isinstance(result, Understood)
    assert len(result.rows) <= 8
    assert {r.state for r in result.rows if r.kind in ("schedule", "look_for")} == {"changed"}


def test_a_cant_do_note_names_only_a_listed_system():
    task = "Every Friday list who has admin access in José Cloud"
    answer = row(
        "look_for", "read_jira_tickets", "who has admin access in José Cloud", source="José Cloud"
    )
    assert shown("look_for", answer, task).note == DO_THIS
    answer = row("look_for", "read_jira_tickets", "who has admin access in Okta", source="Okta")
    task = "Every Friday list who has admin access in Okta"
    assert shown("look_for", answer, task).note == f"I can't read Okta yet. {CAN}"
