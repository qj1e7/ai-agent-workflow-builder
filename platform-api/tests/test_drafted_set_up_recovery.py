"""What happens after a yes to set up a drafted workflow, when anything goes wrong (the step 6
safety review, S1 to S3 and N2 to N4). The set-up is idempotent on our own request id, a set-up
that can't finish never strands the drafted workflow, and the approval page and its route never
take a yes the platform wouldn't set up."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import timedelta
from typing import Any

import httpx
import pytest

from platform_api.builder.drafted_workflows import CHANGED
from platform_api.db import Database
from platform_api.orchestration import (
    KnownOptions,
    N8nError,
    N8nWorkflow,
    NotKeptAsSent,
    SavedDraft,
)
from platform_api.orchestration.n8n import N8nWorkflows
from tests.test_drafted_workflows import Lab, N8n, lab

pytestmark = pytest.mark.anyio

__all__ = ["lab"]


async def page(lab: Lab, approval_id: str, user: str = "bob") -> dict[str, Any]:
    r = await lab.call(user, "GET", f"/api/v1/setup-approvals/{approval_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def decide(
    lab: Lab, approval_id: str, user: str = "bob", verdict: str = "approve"
) -> httpx.Response:
    digest = (await page(lab, approval_id, user))["digest"]
    body: dict[str, Any] = {"verdict": verdict, "digest": digest}
    if verdict == "decline":
        body["reason"] = "Not needed"
    return await lab.call(user, "POST", f"/api/v1/setup-approvals/{approval_id}/decisions", body)


async def sent(lab: Lab) -> tuple[str, str]:
    drafted_id = (await lab.start())["drafted_id"]
    approval = (await lab.send(drafted_id, 1)).json()["approval"]
    return drafted_id, approval["approval_id"]


async def change(lab: Lab, drafted_id: str, revision: int) -> httpx.Response:
    body = {"words": "post at 10:00 instead", "revision": revision}
    return await lab.call("alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/changes", body)


async def laid_out(lab: Lab, drafted_id: str) -> dict[str, Any]:
    async with lab.db.connection("builder") as conn:
        row = await (
            await conn.execute(
                "SELECT document FROM builder.drafted_revisions WHERE drafted_id = %s",
                (drafted_id,),
            )
        ).fetchone()
    assert row is not None
    return dict(row["document"])


async def retried(lab: Lab, db: Database, times: int = 8) -> None:
    for later in range(times):
        await lab.approvals.work_once(db.clock() + timedelta(minutes=10 * later))


async def test_after_a_refused_set_up_the_draft_can_be_changed_or_sent_again(lab: Lab):
    lab.n8n.changes_it = True
    drafted_id, approval_id = await sent(lab)
    assert (await decide(lab, approval_id)).status_code == 201
    await lab.approvals.work_once()
    refused = await lab.read(drafted_id)

    assert refused["state"] == "draft"
    assert refused["set_up"] == {"state": "refused", "use_case_id": None, "words": CHANGED}
    assert refused["can_send"] is True
    again = await lab.send(drafted_id, 1)
    assert (again.status_code, again.json()["state"]) == (200, "waiting")
    assert (await change(lab, drafted_id, 1)).status_code == 202


async def test_a_yes_that_lands_before_a_new_revision_replaces_it_blocks_nothing(lab: Lab):
    drafted_id, approval_id = await sent(lab)

    async def too_late(drafted_id: str) -> None:
        pass

    lab.approvals.replace_waiting = too_late  # type: ignore[method-assign]
    assert (await change(lab, drafted_id, 1)).status_code == 202
    await lab.drafted.settle()
    assert (await decide(lab, approval_id)).status_code == 201
    await lab.approvals.work_once()

    assert lab.n8n.saved == [], "nothing is set up for a revision that is not the newest"
    assert (await change(lab, drafted_id, 2)).status_code == 202
    await lab.drafted.settle()
    assert (await lab.send(drafted_id, 3)).json()["state"] == "waiting"


class NoProjects:
    """The team's allowed Jira projects, emptied after the draft was sent."""

    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions:
        repos = frozenset({"fastapi/fastapi", *adding.get("github_releases", ())})
        return KnownOptions(frozenset(), {"github_releases": repos}, {}, {}, {})


async def test_a_flag_under_today_s_rules_takes_approve_away_and_refuses_a_direct_yes(lab: Lab):
    drafted_id, approval_id = await sent(lab)
    lab.drafted._facts = NoProjects()  # type: ignore[attr-defined]

    seen = await page(lab, approval_id)
    yes = await decide(lab, approval_id)

    assert seen["report"]["flags"]
    assert seen["you_can_decide"] is False
    assert seen["why_not"].startswith("It has a flag under today's rules")
    assert (yes.status_code, yes.json()["detail"]) == (403, seen["why_not"])
    await lab.approvals.work_once()
    assert lab.n8n.saved == []
    assert (await lab.read(drafted_id))["state"] == "waiting"


async def test_the_same_yes_again_answers_200_with_the_decision_recorded_before(lab: Lab):
    _, approval_id = await sent(lab)

    first = await decide(lab, approval_id)
    again = await decide(lab, approval_id)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["approval"]["status"] == "approved"


class DiesAfterCreate(N8n):
    """n8n created the workflow, and then the platform crashed before it kept a record of it."""

    def __init__(self) -> None:
        super().__init__()
        self.dies = True

    async def save_draft(self, document: Mapping[str, Any]) -> SavedDraft:
        saved = await super().save_draft(document)
        if self.dies:
            self.dies = False
            raise RuntimeError("the process died")
        return saved


class ReadBackFails(N8n):
    """n8n created the workflow, then answered the read-back with a 502. save_draft removes
    what it created and raises."""

    def __init__(self) -> None:
        super().__init__()
        self.fails = True

    async def save_draft(self, document: Mapping[str, Any]) -> SavedDraft:
        saved = await super().save_draft(document)
        if self.fails:
            self.fails = False
            await self.remove(saved.workflow_id)
            raise N8nError("GET /workflows/wf1 failed", 502)
        return saved


def with_n8n(lab: Lab, n8n: N8n) -> None:
    lab.n8n = n8n
    lab.drafted._n8n = n8n  # type: ignore[attr-defined]


async def test_after_a_crash_the_retry_adopts_the_copy_n8n_made_and_creates_no_second(
    lab: Lab, db: Database
):
    with_n8n(lab, DiesAfterCreate())
    drafted_id, approval_id = await sent(lab)
    assert (await decide(lab, approval_id)).status_code == 201

    await retried(lab, db)

    after = await lab.read(drafted_id)
    assert after["set_up"]["state"] == "set_up"
    assert (len(lab.n8n.saved), lab.n8n.removed) == (1, [])
    [use_case] = await lab.use_cases()
    assert use_case["n8n_workflow_id"] == "wf1"


async def test_a_read_back_error_is_tried_again_and_never_refused_as_changed(
    lab: Lab, db: Database
):
    with_n8n(lab, ReadBackFails())
    drafted_id, approval_id = await sent(lab)
    assert (await decide(lab, approval_id)).status_code == 201

    await retried(lab, db)

    after = await lab.read(drafted_id)
    assert after["set_up"]["state"] == "set_up"
    assert lab.n8n.removed == ["wf1"]
    assert list(lab.n8n.held) == ["wf2"]


async def test_a_copy_of_ours_that_differs_from_the_approved_one_is_deleted_first(
    lab: Lab, db: Database
):
    drafted_id, approval_id = await sent(lab)
    other = deepcopy(await laid_out(lab, drafted_id))
    other["settings"]["timezone"] = "UTC"
    lab.n8n.held["wf0"] = N8nWorkflow("wf0", "v0", None, other, None)
    assert (await decide(lab, approval_id)).status_code == 201

    await lab.approvals.work_once()

    assert lab.n8n.removed == ["wf0"]
    assert (await lab.read(drafted_id))["set_up"]["state"] == "set_up"


async def test_a_new_approval_never_shows_the_last_one_s_refusal(lab: Lab, db: Database):
    lab.n8n.changes_it = True
    drafted_id, approval_id = await sent(lab)
    await decide(lab, approval_id)
    await lab.approvals.work_once()
    lab.n8n.changes_it = False
    again = (await lab.send(drafted_id, 1)).json()["approval"]["approval_id"]

    await decide(lab, again)
    pending = await lab.read(drafted_id)

    assert pending["state"] == "approved"
    assert pending["set_up"] == {"state": "setting_up", "use_case_id": None, "words": None}
    assert (await change(lab, drafted_id, 1)).status_code == 409


class Api:
    """n8n's API: the create works, and the read-back answers 502."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def create(self, document: Mapping[str, Any]) -> N8nWorkflow:
        return N8nWorkflow("wf9", "v1", None, dict(document))

    async def workflow(self, workflow_id: str) -> N8nWorkflow | None:
        raise N8nError("GET failed", 502)

    async def delete(self, workflow_id: str) -> None:
        self.deleted.append(workflow_id)


async def test_save_draft_removes_what_it_created_when_the_read_back_fails(db: Database):
    api = Api()
    drafts = N8nWorkflows(api, db)  # type: ignore[arg-type]

    with pytest.raises(N8nError) as raised:
        await drafts.save_draft({"name": "x", "nodes": [], "connections": {}})

    assert not isinstance(raised.value, NotKeptAsSent)
    assert api.deleted == ["wf9"]
