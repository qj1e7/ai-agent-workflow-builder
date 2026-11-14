"""The platform's own calls to n8n while it runs (ENGINE-PLAN 2.1 and 2.5), against a fake n8n
that answers as spike P7 recorded n8n 2.42.6 answering."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from platform_api.orchestration.n8n import (
    ChangedInN8n,
    N8nApi,
    N8nError,
    N8nExecutions,
    N8nWorkflows,
    PublishEvent,
    RetryRefused,
    StillRetrying,
    Written,
    publisher_of,
    same_as_sent,
)
from platform_api.orchestration.n8n_calls import FailedExecution, Finished, Publisher
from platform_api.settings import N8nOwner
from platform_api.shared import N8nExecutionId, UserId
from tests.fake_n8n import OWNER_EMAIL, OWNER_ID, OWNER_PASSWORD, FakeN8n

pytestmark = pytest.mark.anyio

ALICE, BOB = UserId("alice"), UserId("bob")
WALL = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
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
        self.wall = WALL

    def wall_clock(self) -> datetime:
        return self.wall

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
        wall=sleeps.wall_clock,
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


async def test_the_platform_signs_in_and_makes_its_key_once() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    for _ in range(3):
        await api.create(DOCUMENT)
    assert (n8n.logins, n8n.keys) == (1, ["key-1"])


def listed_key(key_id: str, label: str, made: datetime, email: str = OWNER_EMAIL) -> dict[str, Any]:
    owner = {"id": OWNER_ID, "email": email}
    return {"id": key_id, "label": label, "createdAt": made.isoformat(), "owner": owner}


async def test_the_platform_s_key_has_only_the_scopes_it_uses_and_runs_out_in_days() -> None:
    n8n = FakeN8n()
    await api_for(n8n).create(DOCUMENT)
    [asked] = n8n.key_requests
    assert asked["label"] == "platform-api"
    assert sorted(asked["scopes"]) == [
        "execution:list",
        "execution:read",
        "execution:retry",
        "workflow:activate",
        "workflow:create",
        "workflow:deactivate",
        "workflow:delete",
        "workflow:move",
        "workflow:read",
        "workflow:update",
    ]
    assert asked["expiresAt"] == int((WALL + timedelta(days=3)).timestamp())


async def test_a_key_that_ran_out_is_replaced_without_a_new_sign_in() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    await api.create(DOCUMENT)
    n8n.keys.clear()
    await api.create(DOCUMENT)
    assert (n8n.logins, len(n8n.key_requests)) == (1, 2)


async def test_making_a_key_removes_only_the_platform_s_own_keys_older_than_a_day() -> None:
    n8n = FakeN8n(
        listed_keys=[
            listed_key("old", "platform-api", WALL - timedelta(days=2)),
            listed_key("fresh", "platform-api", WALL - timedelta(hours=2)),
            listed_key("hers", "platform-api", WALL - timedelta(days=9), "alice@example.com"),
            listed_key("staff", "Alice's key", WALL - timedelta(days=9)),
        ]
    )
    await api_for(n8n).create(DOCUMENT)
    assert [k["id"] for k in n8n.listed_keys] == ["fresh", "hers", "staff"]


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


async def test_write_refuses_when_n8n_keeps_something_other_than_what_was_put() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    workflow_id = await published_workflow(n8n, api)
    live = n8n.workflows[workflow_id]["activeVersionId"]
    n8n.keeps = lambda document: {**document, "nodes": document["nodes"][:1]}
    current = n8n.workflows[workflow_id]["versionId"]
    assert await api.write(workflow_id, current, renamed) == ChangedInN8n()
    assert n8n.workflows[workflow_id]["activeVersionId"] == live, "nothing was published"


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


def failures_for(n8n: FakeN8n) -> N8nWorkflows:
    return N8nWorkflows(api_for(n8n), None)  # type: ignore[arg-type]


async def test_the_sweep_reads_how_each_execution_ended_from_n8n_s_own_record() -> None:
    n8n = FakeN8n()
    n8n.execution("45", "error", failed=("Read release", "GitHub answered 503."))
    n8n.execution("46", "success")
    for status in ("running", "waiting", "crashed"):
        n8n.execution(status, status)
    failures = failures_for(n8n)
    ended = {e: await failures.ended(N8nExecutionId(e)) for e in ("45", "46", "running")}
    assert ended == {
        "45": FailedExecution(N8nExecutionId("45"), "Read release", "GitHub answered 503."),
        "46": Finished(N8nExecutionId("46")),
        "running": None,
    }
    assert await failures.ended(N8nExecutionId("waiting")) is None
    assert isinstance(await failures.ended(N8nExecutionId("crashed")), FailedExecution)
    assert await failures.ended(N8nExecutionId("gone")) is None


async def test_a_failure_is_the_block_and_the_words_from_n8n_s_own_record() -> None:
    n8n = FakeN8n()
    n8n.execution("45", "error", failed=("Read release", "GitHub answered 503."))
    n8n.execution("46", "error", last_node="Compare")
    failures = failures_for(n8n)
    assert await failures.failure(N8nExecutionId("45")) == FailedExecution(
        N8nExecutionId("45"), "Read release", "GitHub answered 503."
    )
    assert await failures.failure(N8nExecutionId("46")) == FailedExecution(
        N8nExecutionId("46"), "Compare", None
    )


async def test_an_execution_that_did_not_end_in_an_error_is_no_failure() -> None:
    n8n = FakeN8n()
    for status in ("success", "running", "waiting", "canceled"):
        n8n.execution(status, status, failed=("Read release", "words"))
    failures = failures_for(n8n)
    for status in ("success", "running", "waiting", "canceled", "gone"):
        assert await failures.failure(N8nExecutionId(status)) is None, status


async def test_a_draft_runs_by_hand_from_start_from_the_portal_with_our_item() -> None:
    """P7 Q3, body B: n8n ignores a bare item, so it goes as the trigger's task data."""
    n8n = FakeN8n()
    api = api_for(n8n)
    created = await api.create(DOCUMENT)
    item = {"nonce": "start_1", "kind": "test", "workflow_id": created.id}
    execution = await api.run_draft(created.id, item)
    [(workflow, body)] = n8n.draft_runs
    assert (workflow, execution) == (created.id, "301")
    assert body == {
        "triggerToStartFrom": {
            "name": "Start from the Portal",
            "data": {
                "startTime": 0,
                "executionTime": 0,
                "source": [],
                "data": {"main": [[{"json": item}]]},
            },
        }
    }


async def test_n8n_s_retry_is_taken_when_it_stops_or_is_still_running_and_refused_in_its_words():
    n8n = FakeN8n()
    api = api_for(n8n)
    assert await api.retry("45") is None
    n8n.retry_answer = "slow"
    assert await api.retry("46") == StillRetrying(), "the wait ran out, so it says nothing yet"
    n8n.retry_answer = "succeeded"
    refused = await api.retry("47")
    assert isinstance(refused, RetryRefused) and "succeeded" in refused.detail
    assert n8n.retries == ["45", "46", "47"]


async def test_unpublish_takes_the_workflow_off_and_is_nothing_when_it_is_off() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    created = await api.create(DOCUMENT)
    await api.unpublish(created.id)
    assert not any(call.endswith("/unpublish") for call in n8n.calls), "nothing was published"
    await api.publish(created.id, created.version_id)
    await api.unpublish(created.id)
    held = await api.workflow(created.id)
    assert held is not None and held.active_version_id is None


async def test_write_can_leave_the_change_a_draft_for_a_workflow_that_is_off() -> None:
    n8n = FakeN8n()
    api = api_for(n8n)
    created = await api.create(DOCUMENT)
    written = await api.write(created.id, created.version_id, renamed, publish=False)
    assert isinstance(written, Written)
    held = await api.workflow(created.id)
    assert held is not None and (held.version_id, held.active_version_id) == (
        written.version_id,
        None,
    )


async def test_the_sweep_reads_an_execution_s_data_only_once_it_failed() -> None:
    """Every few seconds for each open run: the status alone, and the data, which n8n sends in
    full, only for a failure's block and words."""
    n8n = FakeN8n()
    n8n.execution("45", "running")
    n8n.execution("46", "success")
    n8n.execution("47", "error", failed=("Read release", "GitHub answered 503."))
    failures = failures_for(n8n)
    for execution in ("45", "46"):
        await failures.ended(N8nExecutionId(execution))
    assert await N8nExecutions(api_for(n8n)).landed(N8nExecutionId("46"))
    assert n8n.data_reads == []
    assert await failures.ended(N8nExecutionId("47")) == FailedExecution(
        N8nExecutionId("47"), "Read release", "GitHub answered 503."
    )
    assert n8n.data_reads == ["47"]


async def test_the_platform_keeps_its_n8n_session_and_signs_in_again_only_when_it_ends() -> None:
    """n8n limits sign-ins to a few a minute, and the sweep and Turn it on read /rest often."""
    n8n = FakeN8n()
    api = api_for(n8n)
    created = await api.create(DOCUMENT)
    for _ in range(5):
        await api.publication_status(created.id)
    assert n8n.logins == 1
    n8n.session_ends = True
    status = await api.publication_status(created.id)
    assert (status.status, n8n.logins) == ("published", 2)
