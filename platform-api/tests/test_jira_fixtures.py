"""The adapter against Jira's own answers, kept in contracts/fixtures/jira/ (ADR 0035).

The fixtures follow Atlassian's REST reference for Data Center v2 and Cloud v3, with made-up
values. The practice Jira must answer in the same shape, so the adapter can't tell them apart.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from platform_api.db import Database
from platform_api.orchestration.jira import IssueSearch, JiraFlavor, JiraRefused, NewIssue
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from tests.practice import PracticeKit
from tests.support import FIXTURES

pytestmark = pytest.mark.anyio

SGT = timezone(timedelta(hours=8))
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
    assert seen[0].url.path == "/rest/api/3/issue/OPS-7"
    assert seen[0].headers["authorization"].startswith("Basic ")


async def test_a_search_reads_a_body_written_by_hand_and_a_done_with_no_resolution():
    seen: list[httpx.Request] = []
    dc = jira_answering("datacenter", {("GET", "/search"): (200, "search.json")}, seen)
    found = await dc.search(IssueSearch(("OPS",), ("langgraph", "backup"), "Done"))
    assert [(i.key, i.status) for i in found] == [("OPS-7", "To Do"), ("OPS-5", "Done")]
    assert found[1].body.startswith("*Written by hand*")
    jql = seen[0].url.params["jql"]
    assert jql == (
        'project in ("OPS") AND (text ~ "langgraph" OR text ~ "backup") '
        "AND statusCategory = Done ORDER BY created DESC"
    )
    cloud = jira_answering("cloud", {("GET", "/search/jql"): (200, "search-jql.json")}, seen)
    [_, redis] = await cloud.search(IssueSearch(("OPS",)))
    assert seen[1].url.path == "/rest/api/3/search/jql"
    assert (redis.key, redis.body, redis.done_at) == (
        "OPS-8",
        "",
        datetime(2026, 11, 6, 9, 30, tzinfo=SGT),
    )


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
