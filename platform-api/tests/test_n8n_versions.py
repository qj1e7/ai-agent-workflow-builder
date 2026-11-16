"""The versions sweep, Changed in n8n, roll back and Add the yes back (ENGINE-PLAN 2.5, D5, D7):
a version published in n8n's editor is kept and graded with its publisher matched, never
guessed; only a safe version is put back in use, under the version compare; every author of a
workflow a version puts back joins its runs; a delete cancels the open request, then archives
and deletes in n8n; a workflow deleted in n8n keeps its runs and versions."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from platform_api.builder import Builder
from platform_api.builder.layout import LayoutPlan, release_check, schedule_rule
from platform_api.builder.models import RepublishIn, ScheduleSaveIn, WatchlistView
from platform_api.builder.service import NO_START
from platform_api.builder.sweep import ASKED_GAP, Found, Regraded, VersionsSweep
from platform_api.builder.versions import changes_between, schedule_of
from platform_api.builder.watchlist import MovedToN8n
from platform_api.orchestration import (
    GRADING_RULES,
    ChangedInN8n,
    N8nError,
    N8nWorkflow,
    Publisher,
    RanVersion,
    Schedule,
)
from platform_api.orchestration.n8n_calls import VERSION_FAILED, ExecutionFacts, decide_link
from platform_api.orchestration.n8n_schedule import SCHEDULE_TRIGGER
from platform_api.orchestration.schedule import DAYS
from platform_api.shared import UseCaseId, UserId
from tests.fake_n8n import FakeN8n
from tests.support import ALICE, CAROL, NOW, TEAM_ZONE
from tests.test_builder_lifecycle import Lab, ModelConnected, start_run
from tests.test_n8n_builder import ERROR_WORKFLOW, WRITES, Drafts, N8nLab, lab
from tests.test_n8n_lifecycle import Workflows, made, move, version_row
from tests.test_watchlist_n8n import Starts, World, watchlist_before_the_move, world

pytestmark = pytest.mark.anyio

__all__ = ["lab", "world"]

DAVE_IN_N8N = "n8n-user-dave"
DAVE = UserId("dave")
CHANGED_SINCE = "Changed again since, in n8n. Nothing was saved."


@dataclass
class Accounts:
    people: dict[str, UserId] = field(default_factory=lambda: {DAVE_IN_N8N: DAVE})

    async def people_by_n8n_user(self) -> Mapping[str, UserId]:
        return self.people


@dataclass
class Requests:
    """The orchestrator's cancel, recorded with how far n8n had got when it was asked."""

    n8n: FakeN8n
    cancelled: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])

    async def cancel_for_deleted(self, use_case_id: UseCaseId) -> int:
        self.cancelled.append((use_case_id, len(self.n8n.calls)))
        return 1


AGAIN = " Save its schedule again, or change its time zone in n8n."
"""What every time zone finding says to do."""


@dataclass
class Versions:
    own: N8nLab
    accounts: Accounts
    requests: Requests

    @property
    def n8n(self) -> FakeN8n:
        return self.own.n8n

    @property
    def builder(self) -> Builder:
        return self.own.lab.builder

    async def sweep(self) -> int:
        assert self.builder.sweep is not None
        return len(await self.builder.sweep.sweep())

    async def call(self, user: str, method: str, path: str, body: Any = None) -> Any:
        return await self.own.lab.call(user, method, path, body)

    async def view(self, use_case_id: str) -> dict[str, Any]:
        return (await self.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()

    async def rollback(self, user: str, use_case_id: str, to: int, in_use: int | None) -> Any:
        path = f"/api/v1/use-cases/{use_case_id}/versions/{to}/rollback"
        return await self.call(user, "POST", path, {"via": "page", "in_use": in_use})

    async def add_yes(self, user: str, use_case_id: str, in_use: int | None) -> Any:
        path = f"/api/v1/use-cases/{use_case_id}/add-the-yes-back"
        return await self.call(user, "POST", path, {"via": "chat", "in_use": in_use})

    async def parties(self, use_case_id: str, version: int, workflow_id: str) -> set[UserId]:
        row = await version_row(self.own, use_case_id, version)
        ran = await self.own.lab.builder.facts.version(workflow_id, row["n8n_version_id"])
        assert ran is not None
        return set(ran.parties)


def on_n8n(
    lab: Lab, n8n: FakeN8n, accounts: Accounts, requests: Requests, zone: str = TEAM_ZONE
) -> None:
    lab.builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=Workflows(n8n, lab.h.db),
        writes=WRITES,
        requests=requests,
        accounts=accounts,
        time_zone=ZoneInfo(zone),
    )
    lab.app.state.builder = lab.builder


@pytest.fixture
async def v(lab: Lab) -> AsyncIterator[Versions]:
    n8n = FakeN8n()
    accounts, requests = Accounts(), Requests(n8n)
    on_n8n(lab, n8n, accounts, requests)
    yield Versions(N8nLab(lab, n8n), accounts, requests)


def without_yes(workflow: dict[str, Any]) -> None:
    """Deletes Ask for a yes in n8n's editor and joins the block before it to the write."""
    connections: dict[str, Any] = workflow["connections"]
    write = connections.pop("Ask for a yes")["main"][1][0]["node"]
    workflow["nodes"] = [n for n in workflow["nodes"] if n["name"] != "Ask for a yes"]
    for outputs in connections.values():
        for targets in outputs["main"]:
            for target in targets:
                if target["node"] == "Ask for a yes":
                    target["node"] = write


def adding(node_type: str) -> Callable[[dict[str, Any]], None]:
    def change(workflow: dict[str, Any]) -> None:
        workflow["nodes"].append(
            {"name": "Added in n8n", "type": node_type, "parameters": {}, "position": [0, 0]}
        )

    return change


def at_seven_thirty(workflow: dict[str, Any]) -> None:
    for node in workflow["nodes"]:
        if node["type"] == "n8n-nodes-base.scheduleTrigger":
            node["parameters"] = schedule_rule(Schedule("every_day", "07:30", TEAM_ZONE))


async def on_and_changed(
    v: Versions, change: Callable[[dict[str, Any]], None] = without_yes, by: str = DAVE_IN_N8N
) -> tuple[str, str]:
    use_case_id, workflow_id = await made(v.own, on=True)
    v.n8n.publish_as(workflow_id, by, change)
    assert await v.sweep() == 1
    return use_case_id, workflow_id


@pytest.mark.parametrize("day", DAYS)
def test_the_schedule_is_read_back_from_the_rule_the_planner_lays_out(day: str):
    schedule = Schedule(day, "07:30", TEAM_ZONE)  # type: ignore[arg-type]
    trigger = {"type": "n8n-nodes-base.scheduleTrigger", "parameters": schedule_rule(schedule)}
    assert schedule_of({"nodes": [trigger]}, TEAM_ZONE) == schedule


@pytest.mark.parametrize(
    ("interval", "day"),
    [
        ({"field": "weeks", "triggerAtDay": None}, "sunday"),
        ({"field": "days", "daysInterval": None}, "every_day"),
    ],
)
def test_a_part_n8n_sets_to_its_default_when_null_is_shown_as_n8n_runs_it(
    interval: dict[str, Any], day: str
):
    rule = {"interval": [{**interval, "triggerAtHour": 9, "triggerAtMinute": 0}]}
    trigger = {"type": "n8n-nodes-base.scheduleTrigger", "parameters": {"rule": rule}}
    assert schedule_of({"nodes": [trigger]}, TEAM_ZONE) == Schedule(day, "09:00", TEAM_ZONE)  # type: ignore[arg-type]


def test_the_schedule_read_back_is_in_the_zone_the_workflow_runs_on():
    trigger = {
        "type": "n8n-nodes-base.scheduleTrigger",
        "parameters": schedule_rule(Schedule("monday", "09:00", TEAM_ZONE)),
    }
    own = {"nodes": [trigger], "settings": {"timezone": "Europe/London"}}
    instance = {"nodes": [trigger], "settings": {"timezone": "DEFAULT"}}
    assert schedule_of(own, TEAM_ZONE) == Schedule("monday", "09:00", "Europe/London")
    assert schedule_of(instance, "Europe/London") == Schedule("monday", "09:00", "Europe/London")


def test_the_changes_are_a_plain_comparison_of_blocks_the_schedule_and_settings():
    trigger = {
        "name": "Daily 8:00",
        "type": "n8n-nodes-base.scheduleTrigger",
        "parameters": schedule_rule(Schedule("every_day", "08:00", TEAM_ZONE)),
    }
    ask = {"name": "Ask for a yes", "type": "CUSTOM.wabAskForYes", "parameters": {}}
    make = {"name": "Create ticket", "type": "CUSTOM.wabMakeApprovedChanges", "parameters": {}}
    before = {
        "nodes": [trigger, ask, make],
        "connections": {
            "Daily 8:00": {"main": [[{"node": "Ask for a yes"}]]},
            "Ask for a yes": {"main": [[], [{"node": "Create ticket"}]]},
        },
        "settings": {"timezone": "Asia/Singapore"},
    }
    moved = {**trigger, "parameters": schedule_rule(Schedule("monday", "07:30", TEAM_ZONE))}
    after = {
        "nodes": [moved, make, {"name": "Tell you", "type": "CUSTOM.wabTell", "parameters": {}}],
        "connections": {"Daily 8:00": {"main": [[{"node": "Create ticket"}]]}},
        "settings": {"timezone": "Asia/Singapore", "saveManualExecutions": False},
    }
    assert changes_between(before, after) == [
        "Now runs every Monday at 7:30.",
        "Deleted “Ask for a yes”.",
        "Added “Tell you”.",
        "Changed its settings: keeping its test runs.",
    ]
    rewired = {**before, "connections": {"Daily 8:00": {"main": [[{"node": "Create ticket"}]]}}}
    assert changes_between(before, rewired) == ["Changed how the blocks connect."]
    assert changes_between(before, before) == ["Published again, with no change to its blocks."]


def test_the_changes_name_a_block_turned_off_or_on_its_key_and_its_version():
    """Each of these changes what n8n runs, though the block's type and parameters stay."""
    ask = {"name": "Ask for a yes", "type": "CUSTOM.wabAskForYes", "parameters": {}}
    read = {
        "name": "Read tickets",
        "type": "n8n-nodes-base.jira",
        "typeVersion": 1,
        "parameters": {"operation": "getAll"},
        "credentials": {"jiraSoftwareCloudApi": {"id": "wab-jira-read", "name": "Jira"}},
    }
    before = {"nodes": [ask, read], "connections": {}, "settings": {}}
    off = {**before, "nodes": [{**ask, "disabled": True}, read]}
    assert changes_between(before, off) == ["Turned off “Ask for a yes”."]
    assert changes_between(off, before) == ["Turned on “Ask for a yes”."]
    assert changes_between(before, {**before, "nodes": [{**ask, "disabled": False}, read]}) == [
        "Published again, with no change to its blocks."
    ], "n8n runs a block with disabled false as one with none"
    other_key = {**read, "credentials": {"jiraSoftwareCloudApi": {"id": "dave-own-jira"}}}
    renamed_key = {**read, "credentials": {"jiraSoftwareCloudApi": {"id": "wab-jira-read"}}}
    newer = {**read, "typeVersion": 2}
    assert changes_between(before, {**before, "nodes": [ask, other_key]}) == [
        "Changed the key on “Read tickets”."
    ]
    assert changes_between(before, {**before, "nodes": [ask, {**read, "credentials": {}}]}) == [
        "Changed the key on “Read tickets”."
    ]
    assert changes_between(before, {**before, "nodes": [ask, renamed_key]}) == [
        "Published again, with no change to its blocks."
    ], "a key is the same key by its id, whatever name n8n shows for it"
    assert changes_between(before, {**before, "nodes": [ask, newer]}) == [
        "Changed “Read tickets” to another version of its block."
    ]


async def test_safety_a_version_published_in_n8n_without_its_yes_is_kept_as_writes_refused(
    v: Versions,
):
    use_case_id, workflow_id = await on_and_changed(v)
    second = await version_row(v.own, use_case_id, 2)
    assert (second["published_by"], second["published_in"]) == ("dave", "n8n")
    assert second["n8n_version_id"] == v.n8n.workflows[workflow_id]["activeVersionId"]
    view = await v.view(use_case_id)
    assert (view["version"], view["grade"]) == (2, "writes_refused")
    assert view["findings"] == ['"Create ticket" can run without a yes.']
    ran = await v.builder.facts.version(workflow_id, second["n8n_version_id"])
    assert ran == RanVersion("writes_refused", Publisher(DAVE))
    [card] = await v.builder.changed_in_n8n(10)
    assert (card.answer, card.version, card.by, card.grade, card.in_use) == (
        "changed_in_n8n",
        2,
        DAVE,
        "writes_refused",
        2,
    )
    assert card.changes == ["Deleted “Ask for a yes”."]
    assert card.findings == view["findings"]
    assert await v.sweep() == 0, "a version is kept once"


def yes_turned_off(workflow: dict[str, Any]) -> None:
    """Ticks Deactivate on Ask for a yes in n8n's editor, which leaves it on the canvas."""
    for node in workflow["nodes"]:
        if node["name"] == "Ask for a yes":
            node["disabled"] = True


async def test_safety_a_version_published_in_n8n_with_its_yes_turned_off_is_writes_refused(
    v: Versions,
):
    use_case_id, workflow_id = await on_and_changed(v, yes_turned_off)
    view = await v.view(use_case_id)
    assert (view["version"], view["grade"]) == (2, "writes_refused")
    assert view["findings"] == ['"Create ticket" can run without a yes.']
    second = await version_row(v.own, use_case_id, 2)
    ran = await v.builder.facts.version(workflow_id, second["n8n_version_id"])
    assert ran == RanVersion("writes_refused", Publisher(DAVE))
    [card] = await v.builder.changed_in_n8n(10)
    assert (card.grade, card.changes) == ("writes_refused", ["Turned off “Ask for a yes”."])
    versions = (await v.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    assert versions["versions"][0]["changes"] == ["Turned off “Ask for a yes”."]


async def test_safety_a_publisher_the_people_list_cant_match_is_never_guessed(v: Versions):
    v.accounts.people.clear()
    use_case_id, workflow_id = await on_and_changed(v, at_seven_thirty)
    second = await version_row(v.own, use_case_id, 2)
    assert (second["published_by"], second["published_in"]) == (None, "n8n")
    ran = await v.builder.facts.version(workflow_id, second["n8n_version_id"])
    assert ran is not None and ran.unknown, "its runs stop at their first block (D5)"
    versions = (await v.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    assert versions["versions"][0] | {"at": None} == versions["versions"][0] | {
        "at": None,
        "version": 2,
        "by": None,
        "made": "published_in_n8n",
        "grade": "safe",
        "changes": ["Now runs every day at 7:30."],
        "publisher_unknown": True,
    }
    view = await v.view(use_case_id)
    assert (view["schedule"]["day"], view["schedule"]["at"]) == ("every_day", "07:30")


@pytest.mark.parametrize(
    "node_type",
    [
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.somethingNobodyClassed",
    ],
)
async def test_safety_a_block_that_is_off_needs_a_fix(v: Versions, node_type: str):
    use_case_id, _ = await on_and_changed(v, adding(node_type))
    view = await v.view(use_case_id)
    assert view["grade"] == "needs_a_fix"
    assert view["findings"] == [f'"Added in n8n" uses a block that is off: {node_type}.']


async def test_the_platforms_own_publish_is_never_taken_for_one_made_in_n8n(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    v.n8n.publish_as(workflow_id, v.n8n.timeline[workflow_id][-1]["user"]["id"], at_seven_thirty)
    assert await v.sweep() == 0
    assert (await v.view(use_case_id))["version"] == 1


async def test_safety_undo_puts_the_version_before_back_as_n8n_still_holds_it(v: Versions):
    use_case_id, workflow_id = await on_and_changed(v)
    first = await version_row(v.own, use_case_id, 1)
    draft = v.n8n.workflows[workflow_id]["versionId"]
    undone = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert undone.status_code == 200, undone.text
    assert (undone.json()["version"], undone.json()["grade"]) == (3, "safe")
    third = await version_row(v.own, use_case_id, 3)
    assert third["n8n_version_id"] == first["n8n_version_id"]
    held = v.n8n.workflows[workflow_id]
    assert held["activeVersionId"] == first["n8n_version_id"]
    assert held["versionId"] == draft, "publishing a held version leaves the draft alone"
    assert (third["published_by"], third["published_in"]) == ("carol", "portal")
    again = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert (again.status_code, again.json()["version"]) == (200, 3), "asked again, the same"
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    later = await v.call(
        "carol", "PUT", path, {"day": "monday", "at": "09:00", "expected_version": 3}
    )
    assert later.status_code == 200, "the compare checks the draft the platform last saw"


async def test_safety_roll_back_writes_the_kept_workflow_once_n8n_has_forgotten_it(v: Versions):
    use_case_id, workflow_id = await on_and_changed(v)
    first = await version_row(v.own, use_case_id, 1)
    del v.n8n.history[workflow_id][first["n8n_version_id"]]
    undone = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert undone.status_code == 200, undone.text
    third = await version_row(v.own, use_case_id, 3)
    held = v.n8n.workflows[workflow_id]
    assert held["activeVersionId"] == third["n8n_version_id"] != first["n8n_version_id"]
    assert [n["name"] for n in held["nodes"]] == [n["name"] for n in first["document"]["nodes"]]


async def test_safety_a_version_that_is_not_safe_is_never_put_back(v: Versions):
    use_case_id, workflow_id = await on_and_changed(v)
    await v.rollback("carol", use_case_id, 1, in_use=2)
    live = v.n8n.workflows[workflow_id]["activeVersionId"]
    refused = await v.rollback("carol", use_case_id, 2, in_use=3)
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("This version did not pass the safety check")
    assert v.n8n.workflows[workflow_id]["activeVersionId"] == live
    assert (await v.view(use_case_id))["version"] == 3


async def test_safety_add_the_yes_back_puts_a_yes_before_the_write_and_publishes(v: Versions):
    use_case_id, workflow_id = await on_and_changed(v)
    fixed = await v.add_yes("carol", use_case_id, in_use=2)
    assert fixed.status_code == 200, fixed.text
    assert (fixed.json()["version"], fixed.json()["grade"]) == (3, "safe")
    held = v.n8n.workflows[workflow_id]
    third = await version_row(v.own, use_case_id, 3)
    assert held["activeVersionId"] == third["n8n_version_id"]
    asks = held["connections"]["Ask for a yes"]["main"]
    assert asks[1] == [{"node": "Create ticket", "type": "main", "index": 0}]
    again = await v.add_yes("carol", use_case_id, in_use=2)
    assert (again.status_code, again.json()["version"]) == (200, 3)
    moved_on = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert (moved_on.status_code, moved_on.json()["detail"]) == (
        409,
        "Another version is in use by now, so nothing changed.",
    )


async def test_safety_a_change_in_n8n_the_sweep_has_not_seen_is_never_overwritten(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    v.n8n.publish_as(workflow_id, DAVE_IN_N8N, without_yes)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    refused = await v.call(
        "carol", "PUT", path, {"day": "monday", "at": "09:00", "expected_version": 1}
    )
    assert (refused.status_code, refused.json()["detail"]) == (409, CHANGED_SINCE)
    await v.sweep()
    v.n8n.edit(workflow_id)
    draft = v.n8n.workflows[workflow_id]["versionId"]
    refused = await v.add_yes("carol", use_case_id, in_use=2)
    assert (refused.status_code, refused.json()["detail"]) == (409, CHANGED_SINCE)
    assert v.n8n.workflows[workflow_id]["versionId"] == draft, "the editor's draft is kept"
    assert (await v.view(use_case_id))["version"] == 2


async def test_safety_every_author_of_the_n8n_version_a_run_used_is_a_party(v: Versions):
    """Dave published in n8n, Carol put the yes back, Alice undid it, and Carol put Carol's
    version back: n8n publishes the version it still holds, so the run is Dave's work too."""
    use_case_id, workflow_id = await on_and_changed(v)
    assert (await v.add_yes("carol", use_case_id, in_use=2)).status_code == 200
    assert (await v.rollback("alice", use_case_id, 1, in_use=3)).status_code == 200
    assert (await v.rollback("carol", use_case_id, 3, in_use=4)).status_code == 200
    assert {UserId("carol"), DAVE} <= await v.parties(use_case_id, 5, workflow_id)


async def test_safety_every_author_is_kept_when_the_kept_workflow_is_written_again(v: Versions):
    use_case_id, workflow_id = await on_and_changed(v)
    assert (await v.add_yes("carol", use_case_id, in_use=2)).status_code == 200
    assert (await v.rollback("alice", use_case_id, 1, in_use=3)).status_code == 200
    v.n8n.history[workflow_id].clear()
    assert (await v.rollback("alice", use_case_id, 3, in_use=4)).status_code == 200
    fifth = await version_row(v.own, use_case_id, 5)
    third = await version_row(v.own, use_case_id, 3)
    assert fifth["n8n_version_id"] != third["n8n_version_id"], "written again, a new version"
    assert {UserId("alice"), UserId("carol"), DAVE} <= await v.parties(use_case_id, 5, workflow_id)


async def test_safety_a_version_that_carries_the_same_workflow_keeps_every_author(v: Versions):
    """A schedule save that n8n already holds carries the version before it: same workflow,
    same authors, same findings."""
    use_case_id, workflow_id = await on_and_changed(v)
    assert (await v.add_yes("carol", use_case_id, in_use=2)).status_code == 200
    async with v.own.lab.h.db.transaction("builder") as uow:
        from platform_api.builder import service

        await uow.conn.execute(
            "UPDATE builder.use_cases SET current_version = 3 WHERE use_case_id = %s",
            (use_case_id,),
        )
        await uow.conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
            " instruction, params, created_at) SELECT use_case_id, 4, template, name,"
            " instruction, params, created_at FROM builder.use_case_versions"
            " WHERE use_case_id = %s AND version = 3",
            (use_case_id,),
        )
        await service._carry_n8n(uow, use_case_id, 3)  # pyright: ignore[reportPrivateUsage]
    carried = await v.own.row(
        "SELECT a.also = b.also AND a.findings IS NOT DISTINCT FROM b.findings AS same"
        " FROM builder.use_case_versions a JOIN builder.use_case_versions b"
        " ON a.use_case_id = b.use_case_id WHERE a.use_case_id = %s"
        " AND a.version = 4 AND b.version = 3",
        use_case_id,
    )
    assert carried == {"same": True}
    assert {UserId("carol"), DAVE} <= await v.parties(use_case_id, 4, workflow_id)


async def test_safety_a_delete_cancels_the_open_request_then_archives_and_deletes(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    assert (await move(v.own, "delete", use_case_id)).status_code == 200
    [(cancelled, calls_then)] = v.requests.cancelled
    assert cancelled == use_case_id
    after = v.n8n.calls[calls_then:]
    assert after == [
        f"POST /api/v1/workflows/{workflow_id}/archive",
        f"DELETE /api/v1/workflows/{workflow_id}",
    ], "the request ends before n8n archives and deletes"
    assert workflow_id not in v.n8n.workflows


async def test_a_workflow_deleted_in_n8n_keeps_its_runs_and_versions(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    del v.n8n.workflows[workflow_id]
    assert await v.sweep() == 1
    assert [c for c, _ in v.requests.cancelled] == [use_case_id]
    view = await v.view(use_case_id)
    assert view["deleted_in_n8n_at"] is not None and view["next_run_at"] is None
    versions = (await v.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    assert [x["version"] for x in versions["versions"]] == [1]
    assert await v.sweep() == 0
    assert (await move(v.own, "pause", use_case_id)).status_code == 200
    resumed = await move(v.own, "resume", use_case_id)
    assert resumed.status_code == 503
    assert "deleted in n8n" in resumed.json()["detail"]


async def test_safety_a_roll_back_never_publishes_over_a_newer_publish_in_n8n(v: Versions):
    """n8n still holds version 1, so the roll back would publish it as it is: only the version
    compare stops it hiding a publish the sweep has not seen yet."""
    use_case_id, workflow_id = await on_and_changed(v)
    newer = v.n8n.publish_as(workflow_id, DAVE_IN_N8N, at_seven_thirty)
    refused = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert (refused.status_code, refused.json()["detail"]) == (409, CHANGED_SINCE)
    assert v.n8n.workflows[workflow_id]["activeVersionId"] == newer


async def test_safety_a_version_published_again_from_n8ns_history_keeps_its_authors(v: Versions):
    """Dave publishes, in n8n, the version Carol turned on: a run of it is Carol's work too."""
    use_case_id, workflow_id = await made(v.own, on=True)
    assert (await move(v.own, "pause", use_case_id, "carol")).status_code == 200
    assert (await move(v.own, "resume", use_case_id, "carol")).status_code == 200
    first = await version_row(v.own, use_case_id, 1)
    v.n8n.publish_as(workflow_id, DAVE_IN_N8N, without_yes)
    await v.sweep()
    v.n8n._activate(workflow_id, first["n8n_version_id"], DAVE_IN_N8N)  # pyright: ignore[reportPrivateUsage]
    assert await v.sweep() == 1
    assert {UserId("alice"), DAVE} <= await v.parties(use_case_id, 3, workflow_id)


async def test_a_workflow_deleted_in_n8n_comes_back_whole_when_restored(v: Versions):
    """Deleted in n8n, then deleted and restored in the Portal: restoring saves it in n8n again,
    so it is no longer marked deleted there, and it resumes, runs and is swept again."""
    use_case_id, workflow_id = await made(v.own, on=True)
    assert (await move(v.own, "pause", use_case_id)).status_code == 200
    del v.n8n.workflows[workflow_id]
    assert await v.sweep() == 1
    assert (await move(v.own, "delete", use_case_id)).status_code == 200
    restored = await move(v.own, "restore", use_case_id)
    assert restored.status_code == 200, restored.text
    assert (restored.json()["state"], restored.json()["deleted_in_n8n_at"]) == ("paused", None)
    [again] = v.n8n.workflows
    assert again != workflow_id
    resumed = await move(v.own, "resume", use_case_id)
    assert resumed.status_code == 200, resumed.text
    assert v.n8n.workflows[again]["activeVersionId"] is not None
    assert (await start_run(v.own.lab, use_case_id)).startswith("run")
    assert await v.sweep() == 0, "the sweep looks at it again, and n8n has it"
    v.n8n.publish_as(again, DAVE_IN_N8N, at_seven_thirty)
    assert await v.sweep() == 1


async def test_a_look_the_portal_asks_for_is_made_once_every_few_seconds(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    sweep = v.builder.sweep
    assert sweep is not None
    looked = f"GET /api/v1/workflows/{workflow_id}"

    async def looks(ask: str | None) -> int:
        before = v.n8n.calls.count(looked)
        await sweep.asked(ask)
        return v.n8n.calls.count(looked) - before

    assert await looks(use_case_id) == 1
    assert await looks(use_case_id) == 0, "asked again at once, for one workflow"
    assert await looks(None) == 1, "a look at all is its own"
    assert await looks(None) == 0
    v.own.lab.h.advance(ASKED_GAP)
    assert (await looks(use_case_id), await looks(None)) == (1, 1)


class Stuck(Workflows):
    """An n8n that never answers a look."""

    async def look(self, workflow_id: str) -> N8nWorkflow | None:
        await asyncio.sleep(60)
        return await super().look(workflow_id)


async def test_safety_a_slow_n8n_never_holds_a_workflow_from_undo_for_long(v: Versions):
    use_case_id, _ = await on_and_changed(v)
    stuck = VersionsSweep(
        v.own.lab.h.db,
        Stuck(v.n8n, v.own.lab.h.db),
        v.builder.facts,
        v.accounts,
        None,
        TEAM_ZONE,
        0.2,
    )
    looking = asyncio.create_task(stuck.sweep())
    await asyncio.sleep(0.05)
    undone = await asyncio.wait_for(v.rollback("carol", use_case_id, 1, in_use=2), 5)
    assert undone.status_code == 200, undone.text
    assert await asyncio.wait_for(looking, 5) == [], "the slow look gave up, and changed nothing"


async def test_the_watchlists_own_workflow_grades_safe_when_published_again_in_n8n(world: World):
    """The sweep grades with what the editor's lists hold, the watchlist's own block and place
    included, so a change in n8n that keeps them is safe, never Needs a fix."""
    await watchlist_before_the_move(world)
    moved = await world.on_n8n.move_to_n8n()
    assert isinstance(moved, MovedToN8n)
    builder = Builder(world.db, Starts(), world.on_n8n, "", n8n=Drafts(world.n8n, world.db))
    assert builder.sweep is not None
    assert await builder.sweep.sweep() == [], "the platform's own move is no publish in n8n"
    world.n8n.publish_as(moved.workflow_id, DAVE_IN_N8N, at_seven_thirty)
    [found] = await builder.sweep.sweep()
    [row] = await world.rows(
        "SELECT v.grade, v.findings, v.published_in FROM builder.use_case_versions v"
        " JOIN builder.use_cases u ON u.use_case_id = v.use_case_id"
        " WHERE v.version = u.current_version"
    )
    assert isinstance(found, Found)
    assert row["findings"] == []
    assert (row["grade"], row["published_in"]) == ("safe", "n8n")


async def test_the_watchlists_schedule_save_compares_with_the_draft_after_a_roll_back(
    world: World,
):
    """A roll back publishes a version n8n still holds and leaves n8n's draft where it was, so the
    watchlist's own schedule save compares with that draft, not with the version in use."""
    await watchlist_before_the_move(world)
    moved = await world.on_n8n.move_to_n8n()
    assert isinstance(moved, MovedToN8n)
    builder = Builder(world.db, Starts(), world.on_n8n, "", n8n=Drafts(world.n8n, world.db))
    assert builder.sweep is not None
    world.n8n.publish_as(moved.workflow_id, DAVE_IN_N8N, at_seven_thirty)
    [found] = await builder.sweep.sweep()
    assert isinstance(found, Found)
    use_case_id = (await world.use_case())["use_case_id"]
    back = RepublishIn(via="page", in_use=found.version)
    rolled = await builder.rollback_version(use_case_id, moved.version, CAROL, back)
    assert not isinstance(rolled, ChangedInN8n) and rolled is not None
    draft = world.n8n.workflows[moved.workflow_id]["versionId"]
    assert world.n8n.workflows[moved.workflow_id]["activeVersionId"] != draft

    friday = ScheduleSaveIn(day="friday", at="08:00", expected_version=(await world.view()).version)
    saved = await world.on_n8n.save_schedule(ALICE, friday)

    assert isinstance(saved, WatchlistView), saved
    [row] = await world.rows("SELECT n8n_draft_id FROM builder.use_cases")
    assert row["n8n_draft_id"] == world.n8n.workflows[moved.workflow_id]["versionId"] != draft


def off_singapore_time(workflow: dict[str, Any]) -> None:
    workflow["settings"] = {**workflow["settings"], "timezone": "America/New_York"}


async def test_a_changed_team_time_zone_needs_a_fix_until_the_schedule_is_saved_again(
    v: Versions,
):
    use_case_id, workflow_id = await made(v.own, on=True)
    on_n8n(v.own.lab, v.n8n, v.accounts, v.requests, "Europe/London")

    assert await v.sweep() == 1, "a new zone grades every version again"
    view = await v.view(use_case_id)
    assert (view["grade"], view["findings"]) == (
        "needs_a_fix",
        [f"It does not run on London time.{AGAIN}"],
    )
    again = {"day": "every_day", "at": "08:00", "expected_version": view["version"]}
    saved = await v.call("alice", "PUT", f"/api/v1/use-cases/{use_case_id}/schedule", again)

    assert saved.status_code == 200, saved.text
    assert (saved.json()["grade"], saved.json()["schedule"]["time_zone"]) == (
        "safe",
        "Europe/London",
    )
    assert v.n8n.workflows[workflow_id]["settings"]["timezone"] == "Europe/London"


async def test_safety_undo_puts_the_settings_back_that_a_change_in_n8n_took_away(v: Versions):
    """n8n keeps settings once for the workflow and runs every version with them, so a version it
    still holds would run with the changed ones. Undo writes the kept workflow instead."""
    use_case_id, workflow_id = await on_and_changed(v, off_singapore_time)
    view = await v.view(use_case_id)
    assert (view["grade"], view["findings"]) == (
        "needs_a_fix",
        [f"It does not run on Singapore time.{AGAIN}"],
    )
    first = await version_row(v.own, use_case_id, 1)
    undone = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert (undone.status_code, undone.json()["grade"]) == (200, "safe"), undone.text
    held = v.n8n.workflows[workflow_id]
    assert held["settings"]["timezone"] == "Asia/Singapore"
    assert held["activeVersionId"] != first["n8n_version_id"], (
        "written again, not published as held"
    )


def no_error_workflow(settings: dict[str, Any]) -> None:
    settings.pop("errorWorkflow")


async def test_safety_settings_changed_in_n8n_with_no_publish_stop_the_next_run(v: Versions):
    """n8n runs the live version with the workflow's settings now, so a save that clears the
    error workflow, with no publish, needs a fix at once, and the next run stops before it reads."""
    use_case_id, workflow_id = await made(v.own, on=True)
    live = v.n8n.workflows[workflow_id]["activeVersionId"]
    v.n8n.save_settings(workflow_id, no_error_workflow)
    assert await v.sweep() == 1
    view = await v.view(use_case_id)
    assert (view["version"], view["grade"]) == (2, "needs_a_fix")
    assert view["findings"] == ["Its failures do not go to the platform's error workflow."]
    second = await version_row(v.own, use_case_id, 2)
    assert second["n8n_version_id"] == live, "the same version runs, with other settings"
    versions = (await v.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    newest = versions["versions"][0]
    assert (newest["made"], newest["by"], newest["changes"]) == (
        "settings_changed_in_n8n",
        None,
        ["Changed its settings: the error workflow."],
    )
    ran = await v.builder.facts.version(workflow_id, live)
    assert ran is not None and ran.grade == "needs_a_fix"
    fired = ExecutionFacts(workflow_id, "trigger", None, None, live)
    assert decide_link(fired, None, None, None, ran, NOW) == VERSION_FAILED
    [card] = await v.builder.changed_in_n8n(10)
    assert (card.made, card.version, card.grade, card.by) == (
        "settings_changed_in_n8n",
        2,
        "needs_a_fix",
        None,
    )
    assert await v.sweep() == 0, "kept once"
    undone = await v.rollback("carol", use_case_id, 1, in_use=2)
    assert (undone.status_code, undone.json()["grade"]) == (200, "safe"), undone.text
    assert v.n8n.workflows[workflow_id]["settings"]["errorWorkflow"] == ERROR_WORKFLOW


async def test_settings_put_back_in_n8n_grade_safe_again(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    v.n8n.save_settings(workflow_id, no_error_workflow)
    await v.sweep()
    v.n8n.save_settings(workflow_id, lambda s: s.update(errorWorkflow=ERROR_WORKFLOW))
    assert await v.sweep() == 1
    view = await v.view(use_case_id)
    assert (view["version"], view["grade"], view["findings"]) == (3, "safe", [])


RULE_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("field", "days"),
    ("triggerAtDay", [0]),
    ("triggerAtHour", 0),
    ("triggerAtMinute", 0),
)


def saved_in_n8ns_editor(workflow: dict[str, Any]) -> None:
    """What n8n 2.42.6's editor writes as it saves a workflow the platform laid out, with no block
    touched, as docs/evidence/n8n-editor-save/editor_save.txt shows for every layout: a
    parameter at its default is left out, IF's condition options gain its leftValue, and the
    settings gain its binary mode."""
    editors_own = {"executionOrder": "v1", "binaryMode": "separate"}
    workflow["settings"] = {**editors_own, **workflow["settings"]}
    for node in workflow["nodes"]:
        parameters = node["parameters"]
        if node["type"] == "CUSTOM.wabRead" and parameters.get("source") == "github_releases":
            del parameters["source"]
        if node["type"] == "n8n-nodes-base.if":
            parameters["conditions"]["options"]["leftValue"] = ""
        if node["type"] == "n8n-nodes-base.scheduleTrigger":
            for interval in parameters["rule"]["interval"]:
                for key, default in RULE_DEFAULTS:
                    if interval.get(key) == default:
                        del interval[key]


def adding_a_schedule_at_three(workflow: dict[str, Any]) -> None:
    """Adds n8n's Schedule Trigger at 3am in the editor and joins it to the first block. The
    editor saves it with only the hour, the one value not at n8n's default."""
    saved_in_n8ns_editor(workflow)
    workflow["nodes"].append(
        {
            "name": "Schedule Trigger",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, -200],
            "parameters": {"rule": {"interval": [{"triggerAtHour": 3}]}},
        }
    )
    first = {"node": "Read release", "type": "main", "index": 0}
    workflow["connections"]["Schedule Trigger"] = {"main": [[first]]}


async def test_an_autosave_in_n8n_that_writes_only_its_own_defaults_is_no_new_version(
    v: Versions,
):
    """n8n's editor saves on its own while someone looks, writing its defaults in. n8n runs the
    workflow the same, so there is nothing to roll back to and nothing to tell. A real change
    to the settings is still a version, since n8n runs the live version with them."""
    use_case_id, workflow_id = await made(v.own, on=True)
    v.n8n.save_draft(workflow_id, saved_in_n8ns_editor)

    assert await v.sweep() == 0
    assert (await v.view(use_case_id))["version"] == 1
    assert await v.builder.changed_in_n8n(10) == []

    v.n8n.save_settings(workflow_id, no_error_workflow)
    assert await v.sweep() == 1
    [card] = await v.builder.changed_in_n8n(10)
    assert (card.made, card.changes) == (
        "settings_changed_in_n8n",
        ["Changed its settings: the error workflow."],
    )


async def test_a_publish_in_n8n_names_only_what_someone_changed(v: Versions):
    """The editor rewrites blocks nobody touched as it saves, in ways n8n runs the same."""
    use_case_id, workflow_id = await made(v.own, on=True, schedule=None)
    v.n8n.publish_as(workflow_id, DAVE_IN_N8N, adding_a_schedule_at_three)
    assert await v.sweep() == 1

    versions = (await v.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    changed = ["Now runs every day at 3:00.", "Added “Schedule Trigger”."]
    assert versions["versions"][0]["changes"] == changed
    [card] = await v.builder.changed_in_n8n(10)
    assert card.changes == changed


@pytest.mark.parametrize(
    "schedule",
    [
        Schedule("every_day", "08:00", TEAM_ZONE),
        Schedule("every_day", "00:00", TEAM_ZONE),
        Schedule("sunday", "07:00", TEAM_ZONE),
        Schedule("weekdays", "09:15", TEAM_ZONE),
    ],
)
def test_a_layout_n8ns_editor_saved_untouched_has_no_change(schedule: Schedule):
    plan = LayoutPlan("uc", "Release check", "https://portal", schedule, (), "errors", TEAM_ZONE)
    laid_out = release_check(plan, "langchain-ai/langgraph", "MOCK")
    saved = deepcopy(laid_out)
    saved_in_n8ns_editor(saved)
    assert changes_between(laid_out, saved) == ["Published again, with no change to its blocks."]


async def test_a_holder_is_a_colleague_where_n8n_access_is_not_set_up(v: Versions):
    """With no n8n access set up, the platform can't look anyone up, and never shows an id."""
    use_case_id, _ = await made(v.own, on=True)
    async with v.own.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_cases SET held_by = 'carol', held_since = %s"
            " WHERE use_case_id = %s",
            (uow.now, use_case_id),
        )
    assert (await v.view(use_case_id))["held_in_n8n"]["name"] == "a colleague"


async def test_settings_saved_in_another_order_are_no_change(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)

    def reordered(settings: dict[str, Any]) -> None:
        items = list(settings.items())
        settings.clear()
        settings.update(reversed(items))

    v.n8n.save_settings(workflow_id, reordered)
    assert await v.sweep() == 0
    assert (await v.view(use_case_id))["version"] == 1


async def kept_before_the_allow_list(v: Versions, use_case_id: str) -> None:
    """The version in use as a release before E11 kept it: graded safe with an HTTP Request block
    in it, put back in use by Carol over Bob's earlier version, after a move to n8n."""
    async with v.own.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET document = jsonb_set(document, '{nodes}',"
            " document -> 'nodes' || %s::jsonb), made = 'moved_to_n8n', also = %s::jsonb"
            " WHERE use_case_id = %s AND version = 1",
            (
                '[{"name": "Send it out", "type": "n8n-nodes-base.httpRequest",'
                ' "typeVersion": 4.2, "parameters": {}, "position": [0, 400]}]',
                '[{"by": "bob", "in": "portal"}]',
                use_case_id,
            ),
        )


async def test_safety_the_sweep_grades_every_workflow_again_under_new_rules_and_keeps_whose_work(
    v: Versions,
):
    """A block a new release turns off shows on the version in use at the next look, as at
    start, before any run. The version is changed in place, so its publisher, its earlier
    authors and how it came about stay, and so do the people who may not approve its runs."""
    use_case_id, workflow_id = await made(v.own, on=True)
    await kept_before_the_allow_list(v, use_case_id)
    before = await version_row(v.own, use_case_id, 1)
    parties = await v.parties(use_case_id, 1, workflow_id)
    assert v.builder.sweep is not None

    assert await v.builder.sweep.sweep() == [Regraded(use_case_id, 1, "needs_a_fix")]

    view = await v.view(use_case_id)
    assert (view["version"], view["grade"]) == (1, "needs_a_fix")
    assert view["findings"] == [
        '"Send it out" uses a block that is off: n8n-nodes-base.httpRequest.'
    ]
    assert await version_row(v.own, use_case_id, 1) == before
    row = await v.own.row(
        "SELECT made, also FROM builder.use_case_versions WHERE use_case_id = %s AND version = 1",
        use_case_id,
    )
    assert row == {"made": "moved_to_n8n", "also": [{"by": "bob", "in": "portal"}]}
    assert await v.parties(use_case_id, 1, workflow_id) == parties
    ran = await v.builder.facts.version(workflow_id, before["n8n_version_id"])
    assert ran is not None and ran.grade == "needs_a_fix"
    fired = ExecutionFacts(workflow_id, "trigger", None, None, before["n8n_version_id"])
    assert decide_link(fired, None, None, None, ran, NOW) == VERSION_FAILED
    assert await v.builder.sweep.sweep() == [], "graded once under these rules"
    marked = await v.own.row(
        "SELECT graded_by FROM builder.use_case_versions WHERE use_case_id = %s AND version = 1",
        use_case_id,
    )
    assert marked == {"graded_by": f"{GRADING_RULES} {ERROR_WORKFLOW} {TEAM_ZONE}"}


async def test_a_look_that_fails_is_graded_at_the_next_sweep(
    v: Versions, monkeypatch: pytest.MonkeyPatch
):
    use_case_id, _ = await made(v.own, on=True)
    await kept_before_the_allow_list(v, use_case_id)
    assert v.builder.sweep is not None
    sweep = v.builder.sweep
    look = sweep._n8n.look  # pyright: ignore[reportPrivateUsage]

    async def unreachable(workflow_id: str) -> N8nWorkflow | None:
        raise N8nError(f"n8n did not answer for {workflow_id}")

    monkeypatch.setattr(sweep._n8n, "look", unreachable)  # pyright: ignore[reportPrivateUsage]
    assert await sweep.sweep() == []
    assert (await v.view(use_case_id))["grade"] == "safe"
    monkeypatch.setattr(sweep._n8n, "look", look)  # pyright: ignore[reportPrivateUsage]
    assert await sweep.sweep() == [Regraded(use_case_id, 1, "needs_a_fix")]


async def test_safety_while_bootstrap_is_not_ready_the_grade_uses_the_error_workflow_on_record(
    v: Versions, monkeypatch: pytest.MonkeyPatch
):
    """A stale safe grade must not outlive a failed bootstrap: the version is graded against
    the error workflow the last bootstrap recorded."""
    use_case_id, _ = await made(v.own, on=True)
    await kept_before_the_allow_list(v, use_case_id)
    assert v.builder.sweep is not None
    drafts = v.builder.sweep._n8n  # pyright: ignore[reportPrivateUsage]

    async def not_ready() -> str | None:
        return None

    async def recorded() -> str | None:
        return ERROR_WORKFLOW

    monkeypatch.setattr(drafts, "error_workflow_id", not_ready)
    monkeypatch.setattr(drafts, "recorded_error_workflow_id", recorded)
    assert await v.builder.sweep.sweep() == [Regraded(use_case_id, 1, "needs_a_fix")]
    assert (await v.view(use_case_id))["findings"] == [
        '"Send it out" uses a block that is off: n8n-nodes-base.httpRequest.'
    ]


async def test_safety_with_no_error_workflow_on_record_every_workflow_needs_a_fix_until_one_is(
    v: Versions, monkeypatch: pytest.MonkeyPatch
):
    use_case_id, _ = await made(v.own, on=True)
    assert v.builder.sweep is not None
    drafts = v.builder.sweep._n8n  # pyright: ignore[reportPrivateUsage]
    ready = drafts.error_workflow_id

    async def none() -> str | None:
        return None

    monkeypatch.setattr(drafts, "error_workflow_id", none)
    monkeypatch.setattr(drafts, "recorded_error_workflow_id", none)
    assert await v.builder.sweep.sweep() == [Regraded(use_case_id, 1, "needs_a_fix")]
    assert (await v.view(use_case_id))["findings"] == [
        "Its failures do not go to the platform's error workflow."
    ]
    monkeypatch.setattr(drafts, "error_workflow_id", ready)
    assert await v.builder.sweep.sweep() == [Regraded(use_case_id, 1, "safe")]


async def test_a_workflow_that_is_off_is_graded_again_as_it_was_kept(v: Versions):
    """Nothing runs it, so its grade decides whether it may be turned on again."""
    use_case_id, _ = await made(v.own, on=True)
    paused = await v.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/pause")
    assert paused.status_code == 200, paused.text
    await kept_before_the_allow_list(v, use_case_id)
    assert v.builder.sweep is not None
    assert await v.builder.sweep.sweep() == [Regraded(use_case_id, 1, "needs_a_fix")]


def daily_at_three_as_n8n_s_editor_saves_it(workflow: dict[str, Any]) -> None:
    """A Schedule Trigger added in n8n's editor at 3am, its minute left at the 0 the editor
    shows, joined to the block Start from the Portal starts."""
    connections: dict[str, Any] = workflow["connections"]
    first = connections["Start from the Portal"]["main"][0][0]["node"]
    workflow["nodes"].append(
        {
            "id": "9a3c0e52-5d1f-4f7e-8a0b-2f6d1c3e4b5a",
            "name": "Schedule Trigger",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.3,
            "position": [0, 400],
            "parameters": {"rule": {"interval": [{"triggerAtHour": 3}]}},
        }
    )
    connections["Schedule Trigger"] = {"main": [[{"node": first, "type": "main", "index": 0}]]}


def without_the_schedule(workflow: dict[str, Any]) -> None:
    names = {n["name"] for n in workflow["nodes"] if n["type"] == SCHEDULE_TRIGGER}
    workflow["nodes"] = [n for n in workflow["nodes"] if n["name"] not in names]
    for name in names:
        workflow["connections"].pop(name, None)


def without_start_from_the_portal(workflow: dict[str, Any]) -> None:
    workflow["nodes"] = [n for n in workflow["nodes"] if n["name"] != "Start from the Portal"]
    workflow["connections"].pop("Start from the Portal")


async def test_a_schedule_set_in_n8n_is_the_one_every_screen_shows(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True, schedule=None)
    assert (await v.view(use_case_id))["schedule"] is None
    v.n8n.publish_as(workflow_id, DAVE_IN_N8N, daily_at_three_as_n8n_s_editor_saves_it)
    assert await v.sweep() == 1
    view = await v.view(use_case_id)
    assert (view["grade"], view["findings"]) == ("safe", [])
    assert view["schedule"] == {
        "day": "every_day",
        "at": "03:00",
        "time_zone": TEAM_ZONE,
        "owner_name": None,
        "held": None,
        "held_words": None,
    }
    at = datetime.fromisoformat(view["next_run_at"]).astimezone(ZoneInfo(TEAM_ZONE))
    assert (at.hour, at.minute) == (3, 0), "the minute n8n's editor showed, which n8n runs"
    listed = await v.call("alice", "GET", "/api/v1/use-cases")
    [row] = [u for u in listed.json()["use_cases"] if u["use_case_id"] == use_case_id]
    assert (row["schedule"], row["next_run_at"]) == (view["schedule"], view["next_run_at"])


async def test_a_schedule_taken_out_in_n8n_is_gone_from_every_screen(v: Versions):
    use_case_id, _ = await on_and_changed(v, without_the_schedule)
    view = await v.view(use_case_id)
    assert (view["schedule"], view["next_run_at"]) == (None, None)


async def test_with_no_start_from_the_portal_run_now_is_not_offered_and_says_why(v: Versions):
    use_case_id, _ = await on_and_changed(v, without_start_from_the_portal)
    view = await v.view(use_case_id)
    assert view["start_refused"] == NO_START
    refused = await v.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert (refused.status_code, refused.json()["detail"]) == (409, NO_START)
    laid_out, _ = await made(v.own, on=True)
    assert (await v.view(laid_out))["start_refused"] is None
