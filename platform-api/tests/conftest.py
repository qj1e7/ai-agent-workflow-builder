import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import psycopg
import pytest
from psycopg import sql

from platform_api.db import PLATFORM_DATABASE, ROLE_OWNER, ROLES, Database, create_roles_sql
from platform_api.migrations import upgrade_all
from platform_api.settings import CONTEXTS, DatabaseUrls

POSTGRES_IMAGE = (
    "postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
SCHEMAS = ("monitoring", "orchestration", "builder")


@dataclass(frozen=True)
class PostgresUrls:
    superuser: str
    owner: str
    contexts: DatabaseUrls


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


def _wait_ready(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.3)


def _superuser_url() -> Iterator[str]:
    configured = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if configured:
        _wait_ready(configured)
        yield configured
        return
    if shutil.which("docker") is None:
        pytest.skip("no PostgreSQL: set PLATFORM_TEST_DATABASE_URL or install Docker")
    started = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--env",
            "POSTGRES_PASSWORD=test",
            "--publish",
            "127.0.0.1:0:5432",
            POSTGRES_IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        pytest.skip(f"docker could not start PostgreSQL: {started.stderr.strip()}")
    container = started.stdout.strip()
    try:
        port_line = subprocess.run(
            ["docker", "port", container, "5432/tcp"], capture_output=True, text=True, check=True
        ).stdout.splitlines()[0]
        port = port_line.rsplit(":", 1)[1]
        url = f"postgresql://postgres:test@127.0.0.1:{port}/postgres"
        _wait_ready(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)


@pytest.fixture(scope="session")
def superuser_url() -> Iterator[str]:
    yield from _superuser_url()


def _url_for(superuser: str, role: str, password: str) -> str:
    host_part = superuser.split("@", 1)[1].rsplit("/", 1)[0]
    return f"postgresql://{role}:{password}@{host_part}/{PLATFORM_DATABASE}"


@pytest.fixture(scope="session")
def postgres(superuser_url: str) -> PostgresUrls:
    passwords = {role: f"pw-{role}" for role in (ROLE_OWNER, *ROLES.values())}
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        for statement in create_roles_sql(passwords):
            conn.execute(statement)
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (PLATFORM_DATABASE,)
        ).fetchone()
        if exists is None:
            conn.execute(f"CREATE DATABASE {PLATFORM_DATABASE} OWNER {ROLE_OWNER}")
    owner = _url_for(superuser_url, ROLE_OWNER, passwords[ROLE_OWNER])
    with psycopg.connect(owner, autocommit=True) as conn:
        for schema in SCHEMAS:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    upgrade_all(owner)
    contexts = DatabaseUrls(
        **{
            context: _url_for(superuser_url, ROLES[context], passwords[ROLES[context]])
            for context in CONTEXTS
        }
    )
    return PostgresUrls(superuser=superuser_url, owner=owner, contexts=contexts)


def truncate_all(owner_url: str) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        tables = conn.execute(
            "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(%s) "
            "AND tablename <> 'alembic_version'",
            (list(SCHEMAS),),
        ).fetchall()
        if tables:
            names = sql.SQL(", ").join(sql.Identifier(schema, table) for schema, table in tables)
            conn.execute(sql.SQL("TRUNCATE {} CASCADE").format(names))


@pytest.fixture
async def db(postgres: PostgresUrls) -> AsyncIterator[Database]:
    truncate_all(postgres.owner)
    database = Database(postgres.contexts)
    await database.open()
    try:
        yield database
    finally:
        await database.close()
