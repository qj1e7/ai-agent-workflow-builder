import psycopg
import pytest

from platform_api.db import Database
from platform_api.migrations import downgrade, upgrade
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import RunId
from tests.conftest import PostgresUrls
from tests.support import NOW, SPEC

pytestmark = pytest.mark.anyio


async def test_a_watchlist_run_survives_a_downgrade_to_0002_and_back(
    postgres: PostgresUrls, db: Database
):
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_new"), 1, None, NOW)
        record = RunRecord(RunId("run_new"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-new")
    downgrade("orchestration", postgres.owner, "0002")
    upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        loaded = await Store().load_run(uow, RunId("run_new"))
    assert loaded is not None and loaded.spec == SPEC


async def test_the_card_tables_come_and_go_with_migration_0003_and_belong_to_the_builder(
    postgres: PostgresUrls,
):
    tables = ("cards", "card_versions", "use_case_cards")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:

        def present() -> list[str]:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'builder' AND table_name = ANY(%s) ORDER BY 1",
                (list(tables),),
            ).fetchall()
            return [r[0] for r in rows]

        assert present() == sorted(tables)
        downgrade("builder", postgres.owner, "0002")
        assert present() == []
        upgrade("builder", postgres.owner)
        assert present() == sorted(tables)

    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute("SELECT count(*) FROM builder.use_case_cards")
        builder.rollback()
    with (
        psycopg.connect(postgres.contexts.orchestration) as other,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        other.execute("SELECT count(*) FROM builder.cards")
