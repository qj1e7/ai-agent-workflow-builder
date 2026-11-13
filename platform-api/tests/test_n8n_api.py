"""The platform's own calls to n8n while it runs (ENGINE-PLAN 2.1 and 2.5), against a fake n8n
that answers as spike P7 recorded n8n 2.42.6 answering."""

from typing import Any

import pytest

from platform_api.orchestration.n8n import (
    ChangedInN8n,
    N8nApi,
    N8nError,
    N8nExecutions,
    N8nOwner,
    PublishEvent,
    Written,
    publisher_of,
    same_as_sent,
)
from platform_api.orchestration.n8n_calls import Publisher
from platform_api.shared import N8nExecutionId, UserId
from tests.fake_n8n import OWNER_EMAIL, OWNER_ID, OWNER_PASSWORD, FakeN8n

pytestmark = pytest.mark.anyio

ALICE, BOB = UserId("alice"), UserId("bob")
ALICE_IN_N8N = "c3040094-09d8-44f7-9c09-471bf8113c35"
DOCUMENT: dict[str, Any] = {
    "name": "LangGraph release check",
    "nodes": [
        {
            "id": "n1",
            "name": "Start from the Portal",
            "type": "CUSTOM.wabStartFromPortal",
            "typeVersion": 1,
            "position": [0, 200],
            "parameters": {},
        },
        {
            "id": "n2",
            "name": "Read release",
            "type": "CUSTOM.wabRead",
            "typeVersion": 1,
            "position": [220, 0],
            "parameters": {"source": "github_releases", "place": "langchain-ai/langgraph"},
        },
    ],
    "connections": {
        "Start from the Portal": {"main": [[{"node": "Read release", "type": "main", "index": 0}]]}
    },
    "settings": {"timezone": "Asia/Singapore", "saveExecutionProgress": True},
}


class Sleeps:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def api_for(n8n: FakeN8n, sleeps: Sleeps | None = None) -> N8nApi:
    sleeps = sleeps or Sleeps()
    return N8nApi(
        "http://n8n",
        N8nOwner(OWNER_EMAIL, OWNER_PASSWORD),
        n8n.client(),
        sleep=sleeps.sleep,
        clock=sleeps.clock,
    )


async def published_workflow(n8n: FakeN8n, api: N8nApi) -> str:
    created = await api.create(DOCUMENT)
    n8n.workflows[created.id]["active"] = True
    n8n.workflows[created.id]["activeVersionId"] = created.version_id
    return created.id


def renamed(document: dict[str, Any]) -> dict[str, Any]:
    return {**document, "name": "LangGraph release check, renamed"}


async def test_a_draft_is_saved_unpublished_and_n8n_holds_what_was_sent() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    created = await api.create(DOCUMENT)
    held = await api.workflow(created.id)
    assert held is not None
    assert held.active_version_id is None, "a draft is not published"
    assert same_as_sent(DOCUMENT, held.document)


async def test_the_platform_signs_in_and_makes_its_key_once_and_never_deletes_a_key() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    for _ in range(3):
        await api.create(DOCUMENT)
    assert (n8n.logins, n8n.keys) == (1, ["key-1"])
    n8n.keys.remove("key-1")
    await api.create(DOCUMENT)
    assert (n8n.logins, n8n.keys, n8n.deleted_keys) == (1, ["key-2"], 0)


async def test_write_publishes_the_change_when_nothing_changed_under_it() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    before = n8n.workflows[workflow_id]["versionId"]
    written = await api.write(workflow_id, before, renamed)
    assert isinstance(written, Written)
    held = n8n.workflows[workflow_id]
    assert held["name"] == "LangGraph release check, renamed"
    assert held["activeVersionId"] == written.version_id != before


async def test_write_refuses_when_the_draft_changed_since_the_platform_read_it() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    stale = n8n.workflows[workflow_id]["versionId"]
    n8n.edit(workflow_id)
    assert await api.write(workflow_id, stale, renamed) == ChangedInN8n()
    assert n8n.workflows[workflow_id]["name"] == DOCUMENT["name"], "nothing was put"


async def test_write_refuses_when_an_editor_saves_between_the_put_and_the_read_back() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    live = n8n.workflows[workflow_id]["activeVersionId"]
    n8n.after_put = n8n.edit
    current = n8n.workflows[workflow_id]["versionId"]
    assert await api.write(workflow_id, current, renamed) == ChangedInN8n()
    assert n8n.workflows[workflow_id]["activeVersionId"] == live, "nothing was published"


async def test_write_refuses_when_an_editor_saves_just_before_the_publish() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    live = n8n.workflows[workflow_id]["activeVersionId"]
    n8n.after_checksum_read = n8n.edit
    current = n8n.workflows[workflow_id]["versionId"]
    assert await api.write(workflow_id, current, renamed) == ChangedInN8n()
    assert n8n.workflows[workflow_id]["activeVersionId"] == live, "n8n refused the publish"


async def test_waiting_for_a_publish_ends_only_once_every_trigger_is_activated() -> None:
    n8n = FakeN8n(publishing=["in_progress", "in_progress"])
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    status = await api.wait_published(workflow_id)
    assert status.published
    assert n8n.calls.count(f"GET /rest/workflows/{workflow_id}/publication-status") == 3


async def test_waiting_for_a_publish_gives_up_after_its_time() -> None:
    n8n = FakeN8n(publishing=["in_progress"] * 100)
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    with pytest.raises(N8nError, match="did not finish publishing"):
        await api.wait_published(workflow_id, timeout=5)


async def test_the_publish_timeline_names_each_publisher_by_n8n_user_id() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    await api.publish(workflow_id, "v-old")
    [event] = await api.publish_timeline(workflow_id)
    assert (event.version_id, event.event, event.user_id) == ("v-old", "activated", OWNER_ID)


def timeline(*events: tuple[str, str, str, str]) -> list[PublishEvent]:
    return [PublishEvent(version, event, user, at) for version, event, user, at in events]


def test_a_publish_in_n8n_is_the_n8n_user_matched_by_their_stored_id() -> None:
    events = timeline(("v2", "activated", ALICE_IN_N8N, "2026-11-13T09:00:00Z"))
    people = {ALICE_IN_N8N: ALICE}
    assert publisher_of("v2", "n8n", None, events, people) == Publisher(ALICE)


def test_a_publisher_nobody_matches_is_never_guessed() -> None:
    events = timeline(("v2", "activated", ALICE_IN_N8N, "2026-11-13T09:00:00Z"))
    assert publisher_of("v2", "n8n", None, events, {OWNER_ID: BOB}) == Publisher(None)
    assert publisher_of("v3", "n8n", None, events, {ALICE_IN_N8N: ALICE}) is None


def test_the_last_activation_of_the_version_is_its_publisher() -> None:
    events = timeline(
        ("v2", "activated", OWNER_ID, "2026-11-13T09:00:00Z"),
        ("v2", "deactivated", ALICE_IN_N8N, "2026-11-13T09:05:00Z"),
        ("v2", "activated", ALICE_IN_N8N, "2026-11-13T09:06:00Z"),
    )
    people = {ALICE_IN_N8N: ALICE, OWNER_ID: BOB}
    assert publisher_of("v2", "n8n", None, events, people) == Publisher(ALICE)


def test_a_portal_publish_is_the_portal_actor_never_the_owner_the_timeline_names() -> None:
    events = timeline(("v1", "activated", OWNER_ID, "2026-11-13T09:00:00Z"))
    assert publisher_of("v1", "portal", BOB, events, {OWNER_ID: ALICE}) == Publisher(BOB)


async def test_an_execution_counts_only_while_n8n_says_it_is_running_or_waiting() -> None:
    n8n = FakeN8n()
    executions = N8nExecutions(api_for(n8n))
    n8n.execution("41", "running", nonce="start_1")
    n8n.execution("42", "waiting")
    for status in ("success", "error", "canceled", "crashed", "new"):
        n8n.execution(f"x-{status}", status, nonce="start_2")
    running = await executions.execution(N8nExecutionId("41"))
    assert running is not None
    assert (running.workflow_id, running.mode, running.start_nonce, running.version_id) == (
        "wf1",
        "webhook",
        "start_1",
        "v1",
    )
    assert await executions.execution(N8nExecutionId("42")) is not None
    for status in ("success", "error", "canceled", "crashed", "new"):
        assert await executions.execution(N8nExecutionId(f"x-{status}")) is None, status
    assert await executions.execution(N8nExecutionId("404")) is None


async def test_a_wake_landed_when_n8n_shows_the_execution_running_or_finished() -> None:
    n8n = FakeN8n()
    executions = N8nExecutions(api_for(n8n))
    for status in ("running", "success", "error", "waiting", "canceled"):
        n8n.execution(status, status)
    landed = {s: await executions.landed(N8nExecutionId(s)) for s in n8n.executions}
    assert landed == {
        "running": True,
        "success": True,
        "error": True,
        "waiting": False,
        "canceled": False,
    }
    assert not await executions.landed(N8nExecutionId("gone"))
