"""Confluence through the platform, on the mock Confluence: the connection and its check, an agent
reading the one page the platform may read, and a page it may not read.

Each run's workflow is deleted at the end, so nothing it leaves reaches Alice's Needs you, which
the browser suite reads after this one."""

import uuid
from collections.abc import Iterator

import pytest
from harness import Api, Json, MockConfluence

INVENTORY_ID = "424242"
READ = "Page reader read the Confluence page Software inventory."
PAGE_READER: Json = {
    "name": "Page reader",
    "purpose": "Reads one Confluence page and says what it holds.",
    "good_for": ["Read the Software inventory page"],
    "inputs": [
        {
            "name": "Confluence page",
            "kind": "text",
            "what": "The page, by its title or its id.",
            "example": "Software inventory",
        }
    ],
    "blocks": [
        {"say": "Read the page.", "tool": "confluence.read_page"},
        {"say": "Say what it holds, in plain words.", "tool": None},
    ],
    "approvals": [],
}


@pytest.fixture
def confluence() -> Iterator[MockConfluence]:
    mock = MockConfluence()
    mock.set_mode("ok")
    mock.forget_reads()
    yield mock
    mock.set_mode("ok")


@pytest.fixture(scope="module")
def page_reader(api: Api) -> str:
    saved = api.post("alice", "/api/v1/agent-cards", PAGE_READER, expect=(201,)).json()
    return saved["card_id"]


@pytest.fixture
def workflows(api: Api) -> Iterator[list[str]]:
    """The workflows a test made, deleted after it, with the runs they hold."""
    made: list[str] = []
    yield made
    for use_case_id in made:
        api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


def read_page(api: Api, card_id: str, page: str, workflows: list[str]) -> str:
    body: Json = {
        "name": f"Read {page} {uuid.uuid4().hex[:6]}",
        "instruction": "Read the page.",
        "agents": [{"card_id": card_id, "values": {"Confluence page": page}}],
    }
    made = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()
    workflows.append(made["use_case_id"])
    run_id, _ = api.start_run("alice", made["use_case_id"])
    return run_id


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


def test_reading_confluence_is_ready_and_an_agent_that_reads_a_page_uses_it(
    api: Api, page_reader: str, mock_model: None
) -> None:
    listed = {c["id"]: c for c in api.get("bob", "/api/v1/capabilities")["capabilities"]}
    reading = listed["confluence.read"]
    assert (reading["state"], reading["connection"]) == ("ready", "confluence")
    assert page_reader in reading["agents"]
    assert listed["confluence.change"]["state"] == "planned"


def test_an_agent_reads_the_allowed_page_and_asks_nobody(
    api: Api, confluence: MockConfluence, page_reader: str, workflows: list[str], mock_model: None
) -> None:
    run_id = read_page(api, page_reader, "Software inventory", workflows)
    events = api.stream_until("alice", run_id, {"run_succeeded"})
    assert READ in [e["summary"] for e in events if e["kind"] == "agent_step_finished"]
    assert "approval_requested" not in [e["kind"] for e in events], "a read asks nobody"
    assert confluence.reads() == [INVENTORY_ID]


def test_a_page_the_platform_may_not_read_stops_the_run_and_leaves_nothing_in_needs_you(
    api: Api, confluence: MockConfluence, page_reader: str, workflows: list[str], mock_model: None
) -> None:
    run_id = read_page(api, page_reader, "Board salaries", workflows)
    events = api.stream_until("alice", run_id, {"run_failed"})
    failed = [e for e in events if e["kind"] == "agent_failed"]
    assert failed and "may not read that Confluence page" in failed[-1]["data"]["message"]
    assert confluence.reads() == [], "Confluence was never asked for the page"
    api.delete("alice", f"/api/v1/use-cases/{workflows.pop()}", expect=(200,))
    stopped = [s["run_id"] for s in api.get("alice", "/api/v1/home")["stopped"]]
    assert run_id not in stopped, "a deleted workflow's stopped run is not Alice's to act on"
