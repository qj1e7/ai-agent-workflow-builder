"""Confluence through the platform, on the mock Confluence: the connection and its check, the
Cert list parser reading the Cert List page, and a page the platform may not read.

The mock's Cert List page is dated from today, so its split never drifts: three certificates to
act on, and two rows to check (one with no environment, one date that cannot be read)."""

from collections.abc import Iterator

import pytest
from harness import Api, Json, MockConfluence
from test_agent_cards import run_agents

CERT_LIST_PARSER = "crd_cert_list_parser"
FOUND = "Cert list parser found 3 certificates to act on and 2 rows to check on Cert List."
CERT_LIST_ID = "424242"


@pytest.fixture
def confluence() -> Iterator[MockConfluence]:
    mock = MockConfluence()
    mock.set_mode("ok")
    mock.forget_reads()
    yield mock
    mock.set_mode("ok")


def connection(api: Api) -> Json:
    listed = api.get("alice", "/api/v1/settings/connections")["connections"]
    [found] = [c for c in listed if c["id"] == "confluence"]
    return found


def check_now(api: Api) -> Json:
    path = "/api/v1/settings/connections/confluence/check"
    return api.post("alice", path, expect=(200,)).json()


def test_confluence_is_connected_and_a_check_reads_no_page(
    api: Api, confluence: MockConfluence
) -> None:
    assert (connection(api)["state"], connection(api)["practice"]) == ("working", False)
    assert check_now(api)["state"] == "working"
    assert confluence.reads() == [], "a check asks who the key is and reads no page"


def test_check_now_sees_confluence_go_down_and_come_back(
    api: Api, confluence: MockConfluence
) -> None:
    confluence.set_mode("unavailable")
    down = check_now(api)
    assert (down["state"], down["problem"]) == ("not_answering", "Confluence is not answering.")
    confluence.set_mode("ok")
    assert check_now(api)["state"] == "working"


def test_reading_confluence_is_ready_and_the_cert_list_parser_uses_it(
    api: Api, mock_model: None
) -> None:
    listed = {c["id"]: c for c in api.get("bob", "/api/v1/capabilities")["capabilities"]}
    reading = listed["confluence.read"]
    assert (reading["state"], reading["connection"]) == ("ready", "confluence")
    assert CERT_LIST_PARSER in reading["agents"]
    assert listed["confluence.change"]["state"] == "planned"


def test_the_cert_list_parser_reads_the_page_and_finds_what_to_renew(
    api: Api, confluence: MockConfluence, mock_model: None
) -> None:
    values = {"Confluence page": "Cert List"}
    run_id = run_agents(api, CERT_LIST_PARSER, values, "Cert list check")
    events = api.stream_until("alice", run_id, {"run_succeeded"})
    steps = [e["summary"] for e in events if e["kind"] == "agent_step_finished"]
    assert FOUND in steps
    assert "approval_requested" not in [e["kind"] for e in events], "a read asks nobody"
    assert confluence.reads() == [CERT_LIST_ID]


def test_a_page_the_platform_may_not_read_stops_the_run_before_confluence_is_asked(
    api: Api, confluence: MockConfluence, mock_model: None
) -> None:
    values = {"Confluence page": "Board salaries"}
    run_id = run_agents(api, CERT_LIST_PARSER, values, "Not allowed")
    events = api.stream_until("alice", run_id, {"run_failed"})
    failed = [e for e in events if e["kind"] == "agent_failed"]
    assert failed and "may not read that Confluence page" in failed[-1]["data"]["message"]
    assert confluence.reads() == [], "Confluence was never asked for the page"
