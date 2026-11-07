import httpx
import pytest

from agent_runtime.contracts import card_request
from agent_runtime.jira import JiraUnavailable, PlatformJiraFor

BASE = "http://platform-api:8000"
TICKET = {
    "key": "MOCK-7",
    "project": "MOCK",
    "title": "Upgrade LangGraph",
    "status": "To Do",
    "created_at": "2026-10-20T01:00:00Z",
    "done_at": None,
    "updated_at": "2026-10-21T08:30:00Z",
    "issue_type": "Bug",
    "assignee": "Dana Tan",
}


def reader(handler: httpx.MockTransport, base: str = BASE):
    request = card_request("run_01JD1")
    client = httpx.Client(transport=handler, follow_redirects=True)
    reader = PlatformJiraFor(base, client)(request)
    assert reader is not None
    return reader, request


def test_a_search_asks_the_platform_with_the_task_and_the_token_in_a_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"tickets": [TICKET]})

    jira, request = reader(httpx.MockTransport(handler))
    found = jira.search("MOCK", "langgraph", "To Do", "2026-10-01")
    assert [t.key for t in found.tickets] == ["MOCK-7"]
    [sent] = seen
    assert sent.url.host == "platform-api"
    assert sent.url.path == "/internal/v1/runs/run_01JD1/jira/tickets"
    assert dict(sent.url.params) == {
        "task": request.task_id,
        "project": "MOCK",
        "text": "langgraph",
        "status": "To Do",
        "done_since": "2026-10-01",
        "updated_before": "",
        "issue_type": "",
        "created_since": "",
    }
    assert sent.headers["x-callback-token"] == request.callback.token
    assert request.callback.token not in str(sent.url)


def test_a_read_asks_for_one_ticket_and_returns_its_body():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={**TICKET, "body": "Soon."})

    jira, request = reader(httpx.MockTransport(handler))
    ticket = jira.read("MOCK-7")
    assert ticket.body == "Soon."
    assert seen[0].url.path == "/internal/v1/runs/run_01JD1/jira/tickets/MOCK-7"
    assert seen[0].url.params["task"] == request.task_id


def test_a_redirect_is_not_followed_so_the_token_never_leaves():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://evil.test/steal"})

    jira, _ = reader(httpx.MockTransport(handler))
    with pytest.raises(JiraUnavailable):
        jira.search("MOCK", None, None, None)
    assert [r.url.host for r in seen] == ["platform-api"]


@pytest.mark.parametrize("status", [401, 404, 500])
def test_a_refusal_is_plain_words_and_not_the_platforms_text(status: int):
    handler = httpx.MockTransport(lambda r: httpx.Response(status, text="secret detail"))
    jira, _ = reader(handler)
    with pytest.raises(JiraUnavailable) as raised:
        jira.read("MOCK-7")
    assert "secret detail" not in str(raised.value)


def test_no_answer_is_jira_could_not_be_reached():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    jira, _ = reader(httpx.MockTransport(down))
    with pytest.raises(JiraUnavailable, match="could not be reached"):
        jira.search("MOCK", None, None, None)


def test_an_answer_that_is_not_tickets_is_unusable():
    jira, _ = reader(httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": 1})))
    with pytest.raises(JiraUnavailable, match="could not be read"):
        jira.search("MOCK", None, None, None)


def test_more_than_fifty_tickets_is_unusable():
    many = {"tickets": [TICKET] * 51}
    jira, _ = reader(httpx.MockTransport(lambda r: httpx.Response(200, json=many)))
    with pytest.raises(JiraUnavailable):
        jira.search("MOCK", None, None, None)


def test_the_request_has_a_timeout_and_does_not_follow_redirects():
    extensions: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        extensions.append(dict(request.extensions))
        return httpx.Response(200, json={"tickets": []})

    jira, _ = reader(httpx.MockTransport(handler))
    jira.search("MOCK", None, None, None)
    assert extensions[0]["timeout"] == {"connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0}


def test_a_search_sends_the_update_day_and_the_type_and_reads_the_new_fields():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"tickets": [TICKET], "cut_off": False})

    jira, _ = reader(httpx.MockTransport(handler))
    found = jira.search("MOCK", None, None, None, "2026-10-15", "Bug")
    [sent] = seen
    assert sent.url.params["updated_before"] == "2026-10-15"
    assert sent.url.params["issue_type"] == "Bug"
    [ticket] = found.tickets
    assert (ticket.updated_at, ticket.issue_type, ticket.assignee) == (
        "2026-10-21T08:30:00Z",
        "Bug",
        "Dana Tan",
    )
    assert found.cut_off is False


def test_a_search_cut_at_the_limit_says_so():
    jira, _ = reader(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"tickets": [TICKET], "cut_off": True})
        )
    )
    assert jira.search("MOCK", None, None, None).cut_off is True


def test_an_answer_from_before_the_new_fields_still_reads():
    old = {k: v for k, v in TICKET.items() if k not in ("updated_at", "issue_type", "assignee")}
    jira, _ = reader(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"tickets": [old]}))
    )
    found = jira.search("MOCK", None, None, None)
    assert found.cut_off is False
    assert (found.tickets[0].updated_at, found.tickets[0].issue_type) == (None, "")
