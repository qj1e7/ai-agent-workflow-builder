"""Turn back on, the builder's half (ADR 0055, section 7): after an Approver's yes, the fixed
version is put in n8n as the workflow's draft, beside the version in use, and tried with the one
real test run, which stops at the yes and writes nothing (ADR 0044). Only once it passed does the
fixed version go live, as a new version whose authors are the fix's parties."""

from copy import deepcopy
from typing import Any, cast

import pytest

from platform_api.builder.fixes import STALE, FixLive, FixTrying
from platform_api.builder.n8n_holds import HeldInN8n, Holding
from platform_api.db import Connection
from platform_api.shared import RunId, UserId
from tests import support
from tests.test_n8n_lifecycle import MONDAY_NINE, made, version_row
from tests.test_n8n_versions import Versions, lab, v

pytestmark = pytest.mark.anyio

__all__ = ["lab", "v"]

ALICE, CAROL = UserId("alice"), UserId("carol")
CAROL_ON = support.CAROL


def with_a_new_note(document: dict[str, Any]) -> dict[str, Any]:
    fixed = deepcopy(document)
    for node in fixed["nodes"]:
        if node["type"] == "n8n-nodes-base.stickyNote":
            node["parameters"]["content"] = node["parameters"].get("content", "") + " Fixed."
    return fixed


async def test_the_fix_is_tried_as_a_test_run_that_stops_at_the_yes_while_the_old_one_runs(
    v: Versions,
):
    use_case_id, workflow_id = await made(v.own, on=True)
    live = v.n8n.workflows[workflow_id]["activeVersionId"]
    first = await version_row(v.own, use_case_id, 1)

    trying = await v.builder.try_fixed(
        use_case_id, with_a_new_note(first["document"]), CAROL_ON, stopped_version=1
    )
    assert isinstance(trying, FixTrying), trying

    held = v.n8n.workflows[workflow_id]
    assert held["activeVersionId"] == live, "the version in use stays live while it is tried"
    assert held["versionId"] == trying.draft
    run = await v.own.lab.h.orchestrator.get_run(RunId(trying.run_id))
    assert run is not None
    spec = run.record.spec
    assert (spec.test, spec.stops_at_gate) == (True, True)
    assert spec.n8n is not None and spec.n8n.draft_version == trying.draft
    assert (await v.view(use_case_id))["version"] == 1


async def test_only_then_the_fix_goes_live_as_a_new_version_with_the_fix_s_parties(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    first = await version_row(v.own, use_case_id, 1)
    fixed = with_a_new_note(first["document"])
    trying = await v.builder.try_fixed(use_case_id, fixed, CAROL_ON, stopped_version=1)
    assert isinstance(trying, FixTrying)

    refused = await v.builder.put_fixed_live(
        use_case_id, trying, fixed, CAROL, frozenset({ALICE, CAROL}), stopped_version=1
    )
    assert refused == FixLive(paused=False)
    view = await v.view(use_case_id)
    assert (view["state"], view["version"]) == ("on", 2)
    second = await version_row(v.own, use_case_id, 2)
    assert v.n8n.workflows[workflow_id]["activeVersionId"] == second["n8n_version_id"]
    assert {ALICE, CAROL} <= await v.parties(use_case_id, 2, workflow_id)


async def test_a_version_a_person_made_meanwhile_keeps_the_fix_from_being_tried_or_going_live(
    v: Versions,
):
    """The check and the act are one, under the workflow's lock: a fix made for version 1 never
    goes live over a version 2 a person made while it waited or was tried."""
    use_case_id, workflow_id = await made(v.own, on=True)
    first = await version_row(v.own, use_case_id, 1)
    fixed = with_a_new_note(first["document"])
    trying = await v.builder.try_fixed(use_case_id, fixed, CAROL_ON, stopped_version=1)
    assert isinstance(trying, FixTrying)

    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    saved = await v.call("carol", "PUT", path, {**MONDAY_NINE, "expected_version": 1})
    assert saved.status_code == 200, saved.text
    live = v.n8n.workflows[workflow_id]["activeVersionId"]

    refused = await v.builder.put_fixed_live(
        use_case_id, trying, fixed, CAROL, frozenset({ALICE, CAROL}), stopped_version=1
    )
    assert refused == STALE
    assert v.n8n.workflows[workflow_id]["activeVersionId"] == live
    assert (await v.view(use_case_id))["version"] == 2
    again = await v.builder.try_fixed(use_case_id, fixed, CAROL_ON, stopped_version=1)
    assert again == STALE


async def test_a_workflow_an_operator_paused_stays_paused_with_the_fix_saved_for_its_resume(
    v: Versions,
):
    use_case_id, workflow_id = await made(v.own, on=True)
    assert (await v.own.lab.move("alice", "pause", use_case_id)).status_code == 200
    first = await version_row(v.own, use_case_id, 1)
    fixed = with_a_new_note(first["document"])
    trying = await v.builder.try_fixed(use_case_id, fixed, CAROL_ON, stopped_version=1)
    assert isinstance(trying, FixTrying), trying

    put = await v.builder.put_fixed_live(
        use_case_id, trying, fixed, CAROL, frozenset({ALICE, CAROL}), stopped_version=1
    )
    assert put == FixLive(paused=True)
    view = await v.view(use_case_id)
    assert (view["state"], view["version"]) == ("paused", 2)
    second = await version_row(v.own, use_case_id, 2)
    assert second["published_by"] is None, "nobody put it live"


class HeldByDave:
    """Dave holds the workflow in his own n8n space (Open in n8n)."""

    async def refused_while_held(
        self, conn: Connection, use_case_id: str, actor: UserId
    ) -> HeldInN8n | None:
        return HeldInN8n(HELD)


HELD = "Dave is editing it in n8n."


async def test_a_workflow_someone_holds_in_n8n_keeps_the_fix_from_going_live(v: Versions):
    use_case_id, workflow_id = await made(v.own, on=True)
    first = await version_row(v.own, use_case_id, 1)
    fixed = with_a_new_note(first["document"])
    trying = await v.builder.try_fixed(use_case_id, fixed, CAROL_ON, stopped_version=1)
    assert isinstance(trying, FixTrying)
    live = v.n8n.workflows[workflow_id]["activeVersionId"]

    v.builder.holding = cast(Holding, HeldByDave())
    put = await v.builder.put_fixed_live(
        use_case_id, trying, fixed, CAROL, frozenset({ALICE, CAROL}), stopped_version=1
    )
    assert put == HELD
    assert v.n8n.workflows[workflow_id]["activeVersionId"] == live
    assert (await v.view(use_case_id))["version"] == 1
