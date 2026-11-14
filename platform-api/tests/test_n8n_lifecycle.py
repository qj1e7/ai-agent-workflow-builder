"""Turn it on, pause, resume, delete and a new schedule for a use case n8n carries in a workflow of
its own (ENGINE-PLAN 2.4 and 2.5): the Portal says On only once n8n has every trigger live, the
person who turned it on is its publisher, and n8n runs exactly the version the records hold."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.db import Database
from platform_api.orchestration import (
    AgentToRun,
    N8nTarget,
    Publisher,
    RanVersion,
    RunSpec,
    next_run,
)
from platform_api.orchestration.n8n import N8nWorkflows
from platform_api.orchestration.n8n_calls import ExecutionFacts, NewRun, decide_link
from platform_api.orchestration.schedule_store import ScheduleBook, ScheduleTicker
from platform_api.shared import UseCaseId, UserId
from tests.fake_n8n import FakeN8n
from tests.support import NOW
from tests.test_builder_lifecycle import Lab
from tests.test_n8n_api import Sleeps, api_for
from tests.test_n8n_builder import BODY, ERROR_WORKFLOW, N8nLab, lab, with_n8n

pytestmark = pytest.mark.anyio

__all__ = ["lab"]

SINGAPORE = ZoneInfo("Asia/Singapore")
NEVER_LIVE = ["in_progress"] * 200


class Workflows(N8nWorkflows):
    """The real store on a fake n8n, whose waits take no time."""

    def __init__(self, n8n: FakeN8n, db: Database) -> None:
        super().__init__(api_for(n8n, Sleeps()), db)

    async def error_workflow_id(self) -> str | None:
        return ERROR_WORKFLOW


@pytest.fixture
async def own(lab: Lab) -> AsyncIterator[N8nLab]:
    n8n = FakeN8n()
    with_n8n(lab, Workflows(n8n, lab.h.db))
    yield N8nLab(lab, n8n)


async def made(own: N8nLab, **changes: Any) -> tuple[str, str]:
    created = await own.create({**BODY, **changes})
    assert created.status_code == 201, created.text
    body = created.json()
    return body["use_case_id"], body["n8n_workflow_id"]


async def version_row(own: N8nLab, use_case_id: str, version: int) -> dict[str, Any]:
    row = await own.row(
        "SELECT n8n_version_id, published_by, published_in, document"
        " FROM builder.use_case_versions WHERE use_case_id = %s AND version = %s",
        use_case_id,
        version,
    )
    assert row is not None
    return row


async def move(own: N8nLab, action: str, use_case_id: str, user: str = "alice") -> Any:
    return await own.lab.move(user, action, use_case_id)


async def test_safety_turn_it_on_says_on_only_once_n8n_has_every_trigger_live(own: N8nLab):
    use_case_id, workflow_id = await made(own)
    own.n8n.publishing = ["in_progress", "in_progress"]
    turned_on = await move(own, "turn-on", use_case_id, "carol")
    assert turned_on.status_code == 200, turned_on.text
    assert own.n8n.publishing == [], "it waited until n8n read published"
    view = turned_on.json()
    assert (view["state"], view["version"]) == ("on", 1)
    first = await version_row(own, use_case_id, 1)
    assert own.n8n.workflows[workflow_id]["activeVersionId"] == first["n8n_version_id"]
    assert (first["published_by"], first["published_in"]) == ("carol", "portal")
    shown = datetime.fromisoformat(view["next_run_at"])
    assert shown == next_run(first["document"], workflow_id, shown - timedelta(days=1))
    assert (shown.astimezone(SINGAPORE).hour, shown.astimezone(SINGAPORE).minute) == (8, 0)

    again = await move(own, "turn-on", use_case_id)
    assert again.json() == view, "turning it on twice changes nothing"


async def test_safety_turn_it_on_stays_a_draft_when_n8n_never_has_its_triggers_live(own: N8nLab):
    use_case_id, workflow_id = await made(own)
    own.n8n.publishing = list(NEVER_LIVE)
    refused = await move(own, "turn-on", use_case_id)
    assert refused.status_code == 503
    view = (await own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert (view["state"], view["next_run_at"]) == ("draft", None)
    assert own.n8n.workflows[workflow_id]["activeVersionId"] is None, "taken off again"
    assert (await version_row(own, use_case_id, 1))["published_in"] is None


async def test_safety_a_trigger_still_moving_is_not_live(own: N8nLab):
    """Ask for a yes counts as a trigger in n8n's publication status (P7 Q19)."""
    use_case_id, _ = await made(own)
    own.n8n.publishing = ["published with a trigger pending"] * 200
    refused = await move(own, "turn-on", use_case_id)
    assert refused.status_code == 503


async def test_set_up_on_is_published_once_n8n_has_it_live(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    view = (await own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert view["state"] == "on"
    first = await version_row(own, use_case_id, 1)
    assert own.n8n.workflows[workflow_id]["activeVersionId"] == first["n8n_version_id"]
    assert first["published_by"] == "alice"


async def test_pause_takes_it_off_in_n8n_and_resume_puts_the_same_version_back(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    live = own.n8n.workflows[workflow_id]["activeVersionId"]
    paused = await move(own, "pause", use_case_id)
    assert (paused.status_code, paused.json()["state"]) == (200, "paused")
    assert own.n8n.workflows[workflow_id]["activeVersionId"] is None
    resumed = await move(own, "resume", use_case_id)
    assert (resumed.status_code, resumed.json()["state"]) == (200, "on")
    assert own.n8n.workflows[workflow_id]["activeVersionId"] == live


async def test_delete_takes_it_off_in_n8n_and_restore_puts_it_back(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    live = own.n8n.workflows[workflow_id]["activeVersionId"]
    assert (await move(own, "delete", use_case_id)).status_code == 200
    assert own.n8n.workflows[workflow_id]["activeVersionId"] is None
    assert (await move(own, "restore", use_case_id)).status_code == 200
    assert own.n8n.workflows[workflow_id]["activeVersionId"] == live


async def test_a_new_schedule_of_a_workflow_that_is_on_is_published_in_n8n_and_undone(
    own: N8nLab,
):
    use_case_id, workflow_id = await made(own, on=True)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    saved = await own.lab.call("carol", "PUT", path, {"day": "monday", "at": "09:00"})
    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert view["version"] == 2
    second = await version_row(own, use_case_id, 2)
    held = own.n8n.workflows[workflow_id]
    assert held["activeVersionId"] == second["n8n_version_id"] == held["versionId"]
    assert (second["published_by"], second["published_in"]) == ("carol", "portal")
    [rule] = [n["parameters"]["rule"] for n in held["nodes"] if n["name"] == "Mon 9:00"]
    assert rule == {"interval": [{"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9,
                                  "triggerAtMinute": 0}]}  # fmt: skip
    shown = datetime.fromisoformat(view["next_run_at"]).astimezone(SINGAPORE)
    assert (shown.weekday(), shown.hour, shown.minute) == (0, 9, 0)

    undone = await own.lab.call(
        "alice", "POST", f"/api/v1/use-cases/{use_case_id}/versions/2/undo", {"via": "page"}
    )
    assert undone.status_code == 200, undone.text
    third = await version_row(own, use_case_id, 3)
    assert own.n8n.workflows[workflow_id]["activeVersionId"] == third["n8n_version_id"]
    names = {n["name"] for n in own.n8n.workflows[workflow_id]["nodes"]}
    assert "Daily 8:00" in names and "Mon 9:00" not in names


async def test_a_new_schedule_of_a_draft_stays_a_draft_in_n8n(own: N8nLab):
    use_case_id, workflow_id = await made(own)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    saved = await own.lab.call("alice", "PUT", path, {"day": "friday", "at": "17:30"})
    assert saved.status_code == 200, saved.text
    held = own.n8n.workflows[workflow_id]
    assert held["activeVersionId"] is None
    first = await version_row(own, use_case_id, 1)
    assert first["n8n_version_id"] == held["versionId"]
    assert "Fri 17:30" in {n["name"] for n in first["document"]["nodes"]}
    versions = await own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/versions")
    assert versions.json() == {"versions": []}


async def test_a_change_made_in_n8n_since_is_never_saved_over(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    own.n8n.edit(workflow_id)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    saved = await own.lab.call("alice", "PUT", path, {"day": "monday", "at": "09:00"})
    assert saved.status_code == 409
    assert saved.json()["detail"] == "Changed again since, in n8n. Nothing was saved."
    view = (await own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert view["version"] == 1


async def test_a_run_carries_its_workflow_and_where_its_trigger_listens(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    spec = await own.lab.builder.run_spec_for(UseCaseId(use_case_id))
    assert isinstance(spec, RunSpec)
    document = (await version_row(own, use_case_id, 1))["document"]
    [hook] = [n["webhookId"] for n in document["nodes"] if n["name"] == "Start from the Portal"]
    assert spec.n8n == N8nTarget(workflow_id, hook)


async def test_the_schedule_tick_leaves_an_own_workflow_to_n8n(own: N8nLab):
    use_case_id, _ = await made(own, on=True)
    lab = own.lab
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.advance(timedelta(days=2))
    assert await ticker.tick() == []
    assert await lab.runs() == [], f"n8n's Schedule Trigger runs {use_case_id}"


async def test_the_card_a_use_case_pinned_runs_not_the_newest(own: N8nLab):
    facts = own.facts()
    values = {"GitHub repository": "acme/planted", "Jira project": "MOCK"}
    newest = await facts.agent_run(VERSION_CHECKER_ID, values)
    assert isinstance(newest, AgentToRun)
    pinned_card = newest.card_run.card.model_copy(update={"version": 7})
    pinned = await facts.agent_run(VERSION_CHECKER_ID, values, pinned_card)
    assert isinstance(pinned, AgentToRun) and pinned.card_run.card.version == 7


async def test_safety_the_person_who_turned_it_on_owns_its_scheduled_runs(own: N8nLab):
    """D5: a Portal publish is the Portal person who acted, never n8n's owner account. Alice set
    it up and Carol turned it on, so its scheduled runs are Carol's work, which she can never
    approve."""
    use_case_id, workflow_id = await made(own)
    assert (await move(own, "turn-on", use_case_id, "carol")).status_code == 200
    version_id = (await version_row(own, use_case_id, 1))["n8n_version_id"]
    ran = await own.facts().version(workflow_id, version_id)
    assert ran == RanVersion("safe", Publisher(UserId("carol")))
    fired = ExecutionFacts(workflow_id, "trigger", None, None, version_id)
    assert decide_link(fired, None, None, None, ran, NOW) == NewRun(UserId("carol"), "schedule")


async def regrade(own: N8nLab, use_case_id: str, grade: str) -> None:
    """What a later sweep would store, having graded the version again (E6)."""
    async with own.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET grade = %s WHERE use_case_id = %s",
            (grade, use_case_id),
        )


async def test_safety_only_a_version_graded_safe_ever_goes_live(own: N8nLab):
    use_case_id, workflow_id = await made(own, on=True)
    assert (await move(own, "pause", use_case_id)).status_code == 200
    await regrade(own, use_case_id, "writes_refused")
    refused = await move(own, "resume", use_case_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "This version did not pass the safety check, so it cannot be turned on.",
    )
    assert own.n8n.workflows[workflow_id]["activeVersionId"] is None
    view = (await own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert view["state"] == "paused"

    draft_id, draft_workflow = await made(own)
    await regrade(own, draft_id, "needs_a_fix")
    assert (await move(own, "turn-on", draft_id)).status_code == 409
    assert own.n8n.workflows[draft_workflow]["activeVersionId"] is None
