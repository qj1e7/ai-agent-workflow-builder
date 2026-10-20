import psycopg
import pytest
from psycopg import sql

from platform_api.db import Database
from platform_api.settings import Context
from tests.conftest import PostgresUrls

pytestmark = pytest.mark.anyio


def test_each_context_has_a_version_table_in_its_own_schema(postgres: PostgresUrls):
    with psycopg.connect(postgres.owner) as conn:
        for context in ("builder", "orchestration", "monitoring"):
            row = conn.execute(f"SELECT version_num FROM {context}.alembic_version").fetchone()
            assert row == ("0001",)


@pytest.mark.parametrize(
    ("context", "table"),
    [
        ("builder", "orchestration.runs"),
        ("builder", "monitoring.run_events"),
        ("monitoring", "orchestration.runs"),
        ("monitoring", "builder.use_cases"),
        ("orchestration", "builder.use_cases"),
    ],
)
async def test_a_context_cannot_read_another_contexts_tables(
    db: Database, context: Context, table: str
):
    async with db.transaction(context) as uow:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            schema, name = table.split(".")
            await uow.conn.execute(sql.SQL("SELECT 1 FROM {}").format(sql.Identifier(schema, name)))


async def test_orchestration_may_insert_into_the_activity_log_only(db: Database):
    async with db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "INSERT INTO monitoring.run_events "
            "(run_id, seq, ts, actor, kind, summary, data, dedupe_key) "
            "VALUES ('run_1', 1, now(), '{}', 'run_created', 's', '{}', 'k')"
        )
    async with db.transaction("orchestration") as uow:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await uow.conn.execute("DELETE FROM monitoring.run_events")
