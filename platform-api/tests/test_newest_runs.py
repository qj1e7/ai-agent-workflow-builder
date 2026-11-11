from dataclasses import replace
from datetime import timedelta

import pytest

from platform_api.db import Database
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import RunId, UseCaseId
from tests.support import NOW, SPEC

pytestmark = pytest.mark.anyio

BUSY = UseCaseId("uc_busy")
QUIET = UseCaseId("uc_quiet")
UNASKED = UseCaseId("uc_unasked")


async def start(db: Database, use_case_id: UseCaseId, run_id: str, minutes: int) -> None:
    at = NOW + timedelta(minutes=minutes)
    async with db.transaction("orchestration") as uow:
        record = RunRecord(
            RunId(run_id),
            replace(SPEC, use_case_id=use_case_id),
            SPEC.owner,
            at,
            at,
            1,
            Pending(RunId(run_id), 1, None, at),
            (),
            None,
        )
        await Store().insert_run(uow, record, f"key-{run_id}")


async def test_a_workflow_with_many_runs_gets_its_newest_and_only_asked_workflows_are_read(
    db: Database,
):
    for minute in range(30):
        await start(db, BUSY, f"run_busy_{minute:02}", minute)
    await start(db, QUIET, "run_quiet", 5)
    await start(db, UNASKED, "run_unasked", 50)
    async with db.transaction("orchestration") as uow:
        found = await Store().newest_runs(uow, [BUSY, QUIET, UseCaseId("uc_never_ran")])
    assert {r.spec.use_case_id: r.run_id for r in found} == {
        BUSY: "run_busy_29",
        QUIET: "run_quiet",
    }


async def test_two_runs_that_started_together_go_by_run_id(db: Database):
    await start(db, BUSY, "run_a", 0)
    await start(db, BUSY, "run_b", 0)
    async with db.transaction("orchestration") as uow:
        (newest,) = await Store().newest_runs(uow, [BUSY])
    assert newest.run_id == "run_b"


async def test_no_workflows_asked_reads_no_runs(db: Database):
    await start(db, BUSY, "run_a", 0)
    async with db.transaction("orchestration") as uow:
        assert await Store().newest_runs(uow, []) == []
