"""The adapter against Jira's own answers, kept in contracts/fixtures/jira/ (ADR 0035).

The fixtures follow Atlassian's REST reference for Data Center v2 and Cloud v3, with made-up
values. The practice Jira must answer in the same shape, so the adapter can't tell them apart.
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from platform_api.db import Database
from platform_api.orchestration.jira import (
    PRACTICE_SITE,
    IssueSearch,
    JiraFlavor,
    JiraRefused,
    JiraWriteConnector,
    NewIssue,
)
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from tests.practice import BASE, PracticeKit
from tests.support import FIXTURES

pytestmark = pytest.mark.anyio

SGT = timezone(timedelta(hours=8))
HOUR = timedelta(hours=1)
NOTES = "Release notes: https://github.com/langchain-ai/langgraph/releases"
BASES = {"datacenter": "https://jira.example.com", "cloud": "https://example.atlassian.net"}


def fixture(flavor: JiraFlavor, name: str) -> Any:
    return json.loads((FIXTURES / "jira" / flavor / name).read_text())


def jira_answering(
    flavor: JiraFlavor, answers: dict[tuple[str, str], tuple[int, str]], seen: list[httpx.Request]
) -> JiraRestAdapter:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for (method, ending), (status, name) in answers.items():
            if request.method == method and request.url.path.endswith(ending):
                body = fixture(flavor, name) if name else None
                return (
                    httpx.Response(status, json=body)
                    if body is not None
                    else httpx.Response(status)
                )
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    auth = JiraAuth.of(flavor, "token-1", "bot@example.com")
    return JiraRestAdapter(BASES[flavor], flavor, auth, client)


async def test_a_data_center_issue_reads_as_plain_text_and_to_do():
    seen: list[httpx.Request] = []
    jira = jira_answering("datacenter", {("GET", "/issue/OPS-7"): (200, "issue.json")}, seen)
    issue = await jira.get_issue("OPS-7")
    assert issue is not None
    assert (issue.key, issue.project, issue.status, issue.done_at) == (
        "OPS-7",
        "OPS",
        "To Do",
        None,
    )
    assert issue.body == f"LangGraph has 2 new releases.\n{NOTES}"
    assert issue.created_at == datetime(2026, 11, 3, 10, 20, 31, 123000, SGT)
    assert issue.labels == ("wab-run_01JB8-prp_01JB9-0",)
    assert (issue.issue_type, issue.assignee) == ("Task", "Dana Lim")
    assert issue.updated_at == datetime(2026, 11, 3, 10, 20, 31, 123000, SGT)
    assert seen[0].url.path == "/rest/api/2/issue/OPS-7"
    assert seen[0].headers["authorization"] == "Bearer token-1"


async def test_a_cloud_issue_reads_its_document_and_its_done_day():
    seen: list[httpx.Request] = []
    jira = jira_answering("cloud", {("GET", "/issue/OPS-7"): (200, "issue.json")}, seen)
    issue = await jira.get_issue("OPS-7")
    assert issue is not None
    assert (
        issue.body
        == f"LangGraph has 2 new releases.\n{NOTES}\n\nRaised by the AI Workflow Builder."
    )
    assert (issue.status, issue.done_at) == ("Done", datetime(2026, 11, 5, 16, 12, tzinfo=SGT))
    assert issue.updated_at == datetime(2026, 11, 5, 16, 12, tzinfo=SGT)
    assert issue.updated_at != issue.created_at
    assert (issue.issue_type, issue.assignee) == ("Task", "Dana Lim")
    assert seen[0].url.path == "/rest/api/3/issue/OPS-7"
    assert seen[0].headers["authorization"].startswith("Basic ")


async def test_a_search_reads_a_body_written_by_hand_and_a_done_with_no_resolution():
    seen: list[httpx.Request] = []
    dc = jira_answering("datacenter", {("GET", "/search"): (200, "search.json")}, seen)
    found = (await dc.search(IssueSearch(("OPS",), ("langgraph", "backup"), "Done"))).issues
    assert [(i.key, i.status) for i in found] == [("OPS-7", "To Do"), ("OPS-5", "Done")]
    assert found[1].body.startswith("*Written by hand*")
    jql = seen[0].url.params["jql"]
    assert jql == (
        'project in ("OPS") AND (text ~ "langgraph" OR text ~ "backup") '
        "AND statusCategory = Done ORDER BY created DESC"
    )
    cloud = jira_answering("cloud", {("GET", "/search/jql"): (200, "search-jql.json")}, seen)
    [_, redis] = (await cloud.search(IssueSearch(("OPS",)))).issues
    assert seen[1].url.path == "/rest/api/3/search/jql"
    assert (redis.key, redis.body, redis.done_at) == (
        "OPS-8",
        "",
        datetime(2026, 11, 6, 9, 30, tzinfo=SGT),
    )


async def test_a_search_sends_the_date_and_type_filters_in_the_accounts_zone():
    seen: list[httpx.Request] = []
    answers = {("GET", "/myself"): (200, "myself.json"), ("GET", "/search"): (200, "search.json")}
    dc = jira_answering("datacenter", answers, seen)
    since = datetime(2026, 11, 1, tzinfo=UTC)
    before = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    found = await dc.search(
        IssueSearch(("OPS",), created_since=since, updated_before=before, issue_types=("Bug",))
    )
    search = next(r for r in seen if r.url.path.endswith("/search"))
    assert search.url.params["jql"] == (
        'project in ("OPS") AND issuetype in ("Bug") AND created >= "2026-11-01 08:00" '
        'AND updated < "2026-11-06 00:00" ORDER BY created DESC'
    )
    assert search.url.params["maxResults"] == "51"
    assert [i.key for i in found.issues] == ["OPS-7", "OPS-5"] and not found.cut_off


def issues_listing(count: int, flavor: JiraFlavor = "datacenter") -> dict[str, Any]:
    template = fixture(flavor, "issue.json")
    issues = []
    for number in range(count):
        issue = json.loads(json.dumps(template))
        issue["key"] = f"OPS-{100 + number}"
        issue["fields"]["created"] = f"2026-11-0{1 + number % 9}T10:00:00.000+0800"
        issue["fields"]["updated"] = issue["fields"]["created"]
        issues.append(issue)
    return {"issues": issues}


def jira_listing(count: int, time_zone: str | None) -> JiraRestAdapter:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/myself"):
            me = dict(fixture("datacenter", "myself.json"))
            me.pop("timeZone")
            me.update({"timeZone": time_zone} if time_zone else {})
            return httpx.Response(200, json=me)
        return httpx.Response(
            200, json=issues_listing(min(count, int(request.url.params["maxResults"])))
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    auth = JiraAuth.of("datacenter", "token-1", None)
    return JiraRestAdapter(BASES["datacenter"], "datacenter", auth, client)


async def test_a_search_says_when_jira_had_more_than_the_limit():
    full = await jira_listing(60, "Asia/Singapore").search(IssueSearch(("OPS",), limit=3))
    assert len(full.issues) == 3 and full.cut_off
    exact = await jira_listing(3, "Asia/Singapore").search(IssueSearch(("OPS",), limit=3))
    assert len(exact.issues) == 3 and not exact.cut_off


def jira_paging(flavor: JiraFlavor, matching: int, page: int) -> JiraRestAdapter:
    """A Jira where `matching` tickets match and an answer holds at most `page` of them, with its
    flavor's paging signals: Cloud's isLast and nextPageToken, Data Center's total."""

    def answer(request: httpx.Request) -> httpx.Response:
        asked = int(request.url.params["maxResults"])
        shown = min(matching, page, asked)
        issues = issues_listing(shown, flavor)["issues"]
        if flavor == "cloud":
            more = {} if shown == matching else {"nextPageToken": "page-2"}
            return httpx.Response(200, json={"issues": issues, "isLast": not more, **more})
        listing = {"startAt": 0, "maxResults": asked, "total": matching, "issues": issues}
        return httpx.Response(200, json=listing)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    auth = JiraAuth.of(flavor, "token-1", "bot@example.com")
    return JiraRestAdapter(BASES[flavor], flavor, auth, client)


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_a_search_says_it_was_cut_off_when_jira_sends_a_short_page_and_has_more(
    flavor: JiraFlavor,
):
    short = await jira_paging(flavor, matching=120, page=40).search(IssueSearch(("OPS",)))
    assert len(short.issues) == 40 and short.cut_off
    whole = await jira_paging(flavor, matching=40, page=40).search(IssueSearch(("OPS",)))
    assert len(whole.issues) == 40 and not whole.cut_off


def jira_done_in_pages(
    flavor: JiraFlavor, done: list[str], page: int, seen: list[httpx.Request], stall: bool = False
) -> JiraRestAdapter:
    tickets = issues_listing(len(done), flavor)["issues"]
    for ticket, key in zip(tickets, done, strict=True):
        ticket["key"] = key
        ticket["fields"]["status"]["statusCategory"]["key"] = "done"
        ticket["fields"]["resolutiondate"] = "2026-11-05T16:12:00.000+0800"

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        asked = request.url.params["jql"]
        matching = [t for t in tickets if f'"{t["key"]}"' in asked]
        issues = [] if stall and len(seen) > 1 else matching[:page]
        if flavor == "cloud":
            more = len(matching) > len(issues)
            token = {"nextPageToken": "next"} if more else {}
            return httpx.Response(200, json={"issues": issues, "isLast": not more, **token})
        body = {"startAt": 0, "maxResults": page, "total": len(matching), "issues": issues}
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    auth = JiraAuth.of(flavor, "token-1", "bot@example.com")
    return JiraRestAdapter(BASES[flavor], flavor, auth, client)


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_done_tickets_asks_again_when_jira_sends_a_short_page(flavor: JiraFlavor):
    keys = [f"OPS-{n}" for n in range(1, 51)]
    done = keys[::2]
    seen: list[httpx.Request] = []
    found = await jira_done_in_pages(flavor, done, page=10, seen=seen).done_tickets(keys)
    assert sorted(found) == sorted(done)


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_done_tickets_stops_when_jira_says_more_but_sends_nothing_new(flavor: JiraFlavor):
    keys = [f"OPS-{n}" for n in range(1, 51)]
    seen: list[httpx.Request] = []
    jira = jira_done_in_pages(flavor, keys, page=10, seen=seen, stall=True)
    found = await jira.done_tickets(keys)
    assert len(found) == 10 and len(seen) == 2


def practice_without_zone(kit: PracticeKit) -> JiraRestAdapter:
    """The practice Jira, read by an adapter that finds no time zone on the account."""

    async def forward(request: httpx.Request) -> httpx.Response:
        sent = httpx.Request(request.method, request.url, headers=request.headers)
        answer = await kit.client.send(sent)
        body = answer.json()
        if request.url.path.endswith("/myself"):
            body.pop("timeZone")
        return httpx.Response(answer.status_code, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(forward))
    auth = JiraAuth.of("datacenter", kit.jira.auth_header.split(" ", 1)[1], None)
    return JiraRestAdapter(BASE, "datacenter", auth, client)


async def test_with_no_zone_updated_before_keeps_only_the_tickets_updated_before_it(
    db: Database,
):
    kit = PracticeKit(db)
    moment = datetime(2026, 10, 20, tzinfo=UTC)
    for title, at in (
        ("A day before", moment - timedelta(hours=20)),
        ("A minute before", moment - timedelta(minutes=1)),
        ("At the moment", moment),
        ("Hours after", moment + timedelta(hours=6)),
    ):
        await kit.store.create("MOCK", title, "", [], "Bug", created_at=at)
    jira = practice_without_zone(kit)
    found = await jira.search(IssueSearch(("MOCK",), updated_before=moment))
    assert [issue.title for issue in found.issues] == ["A minute before", "A day before"]


async def test_with_no_zone_a_moment_from_the_far_side_of_the_world_still_finds_the_next_hour(
    db: Database,
):
    kit = PracticeKit(db)
    kit.store.time_zone = "Etc/GMT+12"
    moment = datetime(2026, 10, 20, tzinfo=ZoneInfo("Pacific/Kiritimati"))
    await kit.store.create("MOCK", "An hour before", "", [], "Bug", created_at=moment - HOUR)
    await kit.store.create("MOCK", "An hour after", "", [], "Bug", created_at=moment + HOUR)
    jira = practice_without_zone(kit)
    found = await jira.search(IssueSearch(("MOCK",), created_since=moment))
    assert [issue.title for issue in found.issues] == ["An hour after"]


async def test_a_search_in_an_unknown_zone_widens_the_day_and_still_says_it_was_cut_off():
    since = datetime(2026, 11, 3, tzinfo=UTC)
    jira = jira_listing(60, None)
    found = await jira.search(IssueSearch(("OPS",), created_since=since, limit=4))
    assert found.cut_off
    assert all(issue.created_at >= since for issue in found.issues)
    assert len(found.issues) <= 4
    few = await jira_listing(3, None).search(IssueSearch(("OPS",), created_since=since, limit=4))
    assert not few.cut_off


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_a_create_sends_jiras_fields_and_answers_the_new_key(flavor: JiraFlavor):
    seen: list[httpx.Request] = []
    jira = jira_answering(flavor, {("POST", "/issue"): (201, "create.201.json")}, seen)
    issue = NewIssue("OPS", "Upgrade\nLangGraph", "Line *one*.\n\nTwo.", ("wab-run_1-prp_1-0",))
    assert await jira.create_issue(issue) == "OPS-7"
    fields = json.loads(seen[0].content)["fields"]
    assert fields["project"] == {"key": "OPS"}
    assert fields["summary"] == "Upgrade LangGraph"
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["labels"] == ["wab-run_1-prp_1-0"]
    if flavor == "cloud":
        assert fields["description"]["type"] == "doc"
        assert fields["description"]["content"][0]["content"] == [
            {"type": "text", "text": "Line *one*."}
        ]
    else:
        assert fields["description"] == "{noformat}\nLine *one*.\n\nTwo.\n{noformat}"


@pytest.mark.parametrize(
    ("flavor", "account"), [("datacenter", "svc-wab"), ("cloud", "5b10ac8d82e05b22cc7d4ef5")]
)
async def test_the_platform_learns_its_own_account_once_and_reads_who_made_a_ticket(
    flavor: JiraFlavor, account: str
):
    seen: list[httpx.Request] = []
    answers = {
        ("GET", "/myself"): (200, "myself.json"),
        ("GET", "/issue/OPS-7"): (200, "issue.json"),
    }
    jira = jira_answering(flavor, answers, seen)
    assert await jira.whoami() == account
    assert await jira.whoami() == account
    issue = await jira.get_issue("OPS-7")
    assert issue is not None and issue.creator == account
    assert [r.url.path for r in seen].count(
        f"/rest/api/{'3' if flavor == 'cloud' else '2'}/myself"
    ) == 1


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_who_made_a_ticket_comes_from_its_creator_never_its_reporter(flavor: JiraFlavor):
    raw = fixture(flavor, "issue.json")
    mine = raw["fields"]["creator"]
    someone = {"accountId": "mallory", "name": "mallory", "key": "mallory"}
    planted = {**raw, "fields": {**raw["fields"], "creator": someone, "reporter": mine}}
    orphan = {**raw, "fields": {**raw["fields"], "creator": None, "reporter": mine}}

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=planted if request.url.path.endswith("OPS-1") else orphan)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    jira = JiraRestAdapter(BASES[flavor], flavor, JiraAuth.bearer("t"), client)
    first = await jira.get_issue("OPS-1")
    second = await jira.get_issue("OPS-2")
    assert first is not None and first.creator == "mallory"
    assert second is not None and second.creator is None


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_moving_to_done_takes_the_transition_into_the_done_category(flavor: JiraFlavor):
    seen: list[httpx.Request] = []
    answers = {
        ("GET", "/transitions"): (200, "transitions.json"),
        ("POST", "/transitions"): (204, ""),
    }
    await jira_answering(flavor, answers, seen).move_to_done("OPS-7")
    assert json.loads(seen[1].content) == {"transition": {"id": "41"}}


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_jiras_errors_read_as_its_own_words(flavor: JiraFlavor):
    seen: list[httpx.Request] = []
    answers = {
        ("POST", "/issue"): (400, "error.400.json"),
        ("GET", "/issue/OPS-9"): (404, "error.404.json"),
    }
    jira = jira_answering(flavor, answers, seen)
    with pytest.raises(JiraRefused, match="summary: You must specify a summary of the issue"):
        await jira.create_issue(NewIssue("OPS", "", ""))
    assert await jira.get_issue("OPS-9") is None


def shape(value: object, prefix: str = "") -> dict[str, str]:
    """Each path in a JSON value and its type, lists by their first item."""
    out: dict[str, str] = {prefix: type(value).__name__}
    if isinstance(value, dict):
        for name, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            out |= shape(item, f"{prefix}.{name}")
    elif isinstance(value, list) and value:
        out |= shape(value[0], f"{prefix}[]")  # pyright: ignore[reportUnknownArgumentType]
    return out


READ = (
    ".key",
    ".fields.summary",
    ".fields.description",
    ".fields.project.key",
    ".fields.labels",
    ".fields.creator",
    ".fields.status.statusCategory.key",
    ".fields.created",
    ".fields.resolutiondate",
)


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_the_practice_jira_answers_in_jiras_shape(db: Database, flavor: JiraFlavor):
    kit = PracticeKit(db, flavor)
    body = f"LangGraph has 2 new releases.\n{NOTES}"
    key = await kit.jira.create_issue(NewIssue("MOCK", "Upgrade", body, ("wab-run_1-prp_1-0",)))
    version = "3" if flavor == "cloud" else "2"
    if flavor == "cloud":
        await kit.jira.move_to_done(key)
    headers = {"Authorization": kit.jira.auth_header}
    base = "http://platform-api:8000/practice-jira"
    raw = (await kit.client.get(f"{base}/rest/api/{version}/issue/{key}", headers=headers)).json()
    real, practice = shape(fixture(flavor, "issue.json")), shape(raw)
    assert {path: real[path] for path in READ} == {path: practice[path] for path in READ}
    search = "search/jql" if flavor == "cloud" else "search"
    found = (
        await kit.client.get(
            f"{base}/rest/api/{version}/{search}", params={"jql": "project = MOCK"}, headers=headers
        )
    ).json()
    listed = "search-jql.json" if flavor == "cloud" else "search.json"
    assert set(fixture(flavor, listed)) - {"expand"} <= set(found)
    created = (
        await kit.client.post(
            f"{base}/rest/api/{version}/issue",
            json={
                "fields": {
                    "project": {"key": "MOCK"},
                    "summary": "x",
                    "issuetype": {"name": "Task"},
                }
            },
            headers=headers,
        )
    ).json()
    assert set(created) == set(fixture(flavor, "create.201.json"))


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_no_permission_is_a_refusal_for_good(flavor: JiraFlavor):
    seen: list[httpx.Request] = []
    jira = jira_answering(flavor, {("POST", "/issue"): (403, "error.403.json")}, seen)
    with pytest.raises(JiraRefused, match="do not have permission") as refused:
        await jira.create_issue(NewIssue("OPS", "Upgrade", ""))
    assert refused.value.retryable is False


@pytest.mark.parametrize("flavor", ["datacenter", "cloud"])
async def test_the_label_search_and_the_done_check_quote_every_value(flavor: JiraFlavor):
    seen: list[httpx.Request] = []
    search = "/search/jql" if flavor == "cloud" else "/search"
    listed = "search-jql.json" if flavor == "cloud" else "search.json"
    jira = jira_answering(flavor, {("GET", search): (200, listed)}, seen)
    await jira.find_by_label("OPS", "wab-run_1-prp_1-0")
    await jira.done_tickets(["OPS-7", "OPS-8"])
    assert [request.url.params["jql"] for request in seen] == [
        'project = "OPS" AND labels = "wab-run_1-prp_1-0" ORDER BY created ASC',
        'key in ("OPS-7", "OPS-8") AND statusCategory = Done',
    ]


async def test_a_browse_address_puts_the_key_in_made_safe(db: Database):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    template = "https://jira.example.com/jira/browse/{key}?from=wab"
    jira = JiraRestAdapter(
        BASES["cloud"], "cloud", JiraAuth.bearer("t"), client, browse_url=template
    )
    assert jira.browse_url("A B/1") == "https://jira.example.com/jira/browse/A%20B%2F1?from=wab"
    plain = JiraRestAdapter(BASES["datacenter"], "datacenter", JiraAuth.bearer("t"), client)
    assert plain.browse_url("OPS-7") == "https://jira.example.com/browse/OPS-7"
    assert (
        JiraWriteConnector(jira, db, PRACTICE_SITE).link("A B/1")
        == "https://jira.example.com/jira/browse/A%20B%2F1?from=wab"
    )
