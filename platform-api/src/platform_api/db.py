import hashlib
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from platform_api.settings import CONTEXTS, Context, DatabaseUrls

ROLE_OWNER = "wab_owner"
ROLES: Mapping[Context, str] = {
    "builder": "wab_builder",
    "orchestration": "wab_orchestration",
    "monitoring": "wab_monitoring",
}
PLATFORM_DATABASE = "platform"

type Clock = Callable[[], datetime]
type Connection = AsyncConnection[DictRow]


def utcnow() -> datetime:
    return datetime.now(UTC)


def json(value: object) -> Jsonb:
    return Jsonb(value)


@dataclass(frozen=True)
class UnitOfWork:
    conn: Connection
    now: datetime


class Database:
    def __init__(self, urls: DatabaseUrls, clock: Clock = utcnow, pool_size: int = 8) -> None:
        self._urls = urls
        self._pool_size = pool_size
        self._clock = clock
        self._pools: dict[Context, AsyncConnectionPool[Connection]] = {}

    @property
    def clock(self) -> Clock:
        return self._clock

    async def open(self) -> None:
        for context in CONTEXTS:
            pool: AsyncConnectionPool[Connection] = AsyncConnectionPool(
                self._urls.for_context(context),
                open=False,
                min_size=1,
                max_size=self._pool_size,
                kwargs={"row_factory": dict_row},
            )
            await pool.open(wait=True, timeout=30)
            self._pools[context] = pool

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()

    @asynccontextmanager
    async def connection(self, context: Context) -> AsyncGenerator[Connection]:
        async with self._pools[context].connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self, context: Context) -> AsyncGenerator[UnitOfWork]:
        async with self.connection(context) as conn, conn.transaction():
            yield UnitOfWork(conn, self._clock())


def create_roles_sql(passwords: Mapping[str, str]) -> list[sql.Composed]:
    statements: list[sql.Composed] = []
    for role in (ROLE_OWNER, *ROLES.values()):
        statements.append(
            sql.SQL(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {name}) "
                "THEN CREATE ROLE {role} LOGIN PASSWORD {password}; "
                "ELSE ALTER ROLE {role} WITH LOGIN PASSWORD {password}; END IF; END $$"
            ).format(
                name=sql.Literal(role),
                role=sql.Identifier(role),
                password=sql.Literal(passwords[role]),
            )
        )
    return statements


def workflow_lock_key(use_case_id: str) -> int:
    """The advisory lock key for one workflow. Both contexts derive it here, so they name the
    same lock."""
    digest = hashlib.blake2b(f"use_case:{use_case_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def hold_workflow(conn: Connection, use_case_id: str, *, alone: bool) -> None:
    """Orders a run's start against a pause or delete of its workflow (#56), until the
    transaction on conn ends. A start holds it shared, from the state read to the run insert,
    so starts don't wait for each other. A pause or delete holds it alone, so it waits for a
    start that has read the state, and a start waits for it, then reads the new state.

    Take it once per start, on one connection. A second request for it on another connection
    queues behind a pause that is already waiting, and neither ever moves. It works only because
    every context's database URL names the same PostgreSQL database, so they share its locks."""
    take = "pg_advisory_xact_lock" if alone else "pg_advisory_xact_lock_shared"
    await conn.execute(f"SELECT {take}(%s)", (workflow_lock_key(use_case_id),))
