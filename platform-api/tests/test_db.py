import psycopg
import pytest
from psycopg import sql

from platform_api.db import Database
from platform_api.settings import Context
from tests.conftest import PostgresUrls

pytestmark = pytest.mark.anyio


def test_each_context_has_a_version_table_in_its_own_schema(postgres: PostgresUrls):
    with psycopg.connect(postgres.owner) as conn:
        for context, head in (
            ("builder", "0005"),
            ("orchestration", "0008"),
            ("monitoring", "0001"),
        ):
            table = sql.Identifier(context, "alembic_version")
            row = conn.execute(sql.SQL("SELECT version_num FROM {}").format(table)).fetchone()
            assert row == (head,)


@pytest.mark.parametrize(
    ("context", "table"),
    [
        ("builder", "orchestration.runs"),
        ("builder", "monitoring.run_events"),
        ("monitoring", "orchestration.runs"),
        ("monitoring", "builder.use_cases"),
        ("orchestration", "builder.use_cases"),
        ("builder", "orchestration.model_setting"),
        ("monitoring", "orchestration.model_setting"),
        ("builder", "orchestration.people"),
        ("monitoring", "orchestration.people"),
        ("builder", "orchestration.confirmations"),
        ("monitoring", "orchestration.settings_changes"),
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


async def test_the_settings_history_is_append_only(db: Database):
    async with db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "INSERT INTO orchestration.settings_changes "
            "(changed_at, area, changed_by, summary) VALUES (now(), 'people', 'deploy', 's')"
        )
    for statement in (
        "DELETE FROM orchestration.settings_changes",
        "UPDATE orchestration.settings_changes SET summary = 'x'",
    ):
        async with db.transaction("orchestration") as uow:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await uow.conn.execute(statement)


async def test_nobody_deletes_people_or_confirmations(db: Database):
    for statement in (
        "DELETE FROM orchestration.people",
        "DELETE FROM orchestration.confirmations",
    ):
        async with db.transaction("orchestration") as uow:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await uow.conn.execute(statement)
