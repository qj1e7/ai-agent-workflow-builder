import os
import shutil
import subprocess
import time
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from dataclasses import dataclass

import anyio
import psycopg
import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from psycopg import sql

from platform_api.db import PLATFORM_DATABASE, ROLE_OWNER, ROLES, Database, create_roles_sql
from platform_api.migrations import upgrade_all
from platform_api.monitoring import ActivityLog, Copier, CosmosEvents
from platform_api.monitoring.cosmos_log import CONTAINER, cosmos_client
from platform_api.settings import CONTEXTS, CosmosSettings, DatabaseUrls

POSTGRES_IMAGE = (
    "postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
SCHEMAS = ("monitoring", "orchestration", "builder")
EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)
COSMOS_TEST_DATABASE = "activity_test"
COSMOS_WAIT_SECONDS = 180
READERS = ["postgres", pytest.param("cosmos", marks=pytest.mark.cosmos)]


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


def cosmos_settings() -> CosmosSettings:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if not endpoint:
        reason = "no Cosmos DB: set COSMOS_ENDPOINT to the emulator"
        if os.environ.get("COSMOS_REQUIRED"):
            pytest.fail(f"{reason}. COSMOS_REQUIRED is set, so this test may not skip.")
        pytest.skip(reason)
    return CosmosSettings(endpoint=endpoint, key=os.environ.get("COSMOS_KEY") or EMULATOR_KEY)


@dataclass(frozen=True)
class CosmosUnderTest:
    events: CosmosEvents
    database: DatabaseProxy
    container: ContainerProxy

    async def seqs(self, run_id: str) -> list[int]:
        query = self.container.query_items(
            "SELECT c.seq FROM c ORDER BY c.seq", partition_key=run_id
        )
        return [item["seq"] async for item in query]


async def _wait_for_test_database(settings: CosmosSettings) -> tuple[CosmosEvents, DatabaseProxy]:
    deadline = time.monotonic() + COSMOS_WAIT_SECONDS
    while True:
        client = cosmos_client(settings)
        try:
            database = await client.create_database_if_not_exists(COSMOS_TEST_DATABASE)
        except AzureError:
            await client.close()
            if time.monotonic() > deadline:
                raise
            await anyio.sleep(1)
            continue
        return CosmosEvents(client, database=COSMOS_TEST_DATABASE), database


async def fresh_cosmos() -> CosmosUnderTest:
    events, database = await _wait_for_test_database(cosmos_settings())
    try:
        with suppress(CosmosResourceNotFoundError):
            await database.delete_container(CONTAINER)
        await events.ensure()
    except BaseException:
        await events.close()
        raise
    return CosmosUnderTest(events, database, database.get_container_client(CONTAINER))


@pytest.fixture
async def cosmos() -> AsyncIterator[CosmosUnderTest]:
    under_test = await fresh_cosmos()
    try:
        yield under_test
    finally:
        await under_test.events.close()


@pytest.fixture(params=READERS)
async def activity_log(request: pytest.FixtureRequest, db: Database) -> AsyncIterator[ActivityLog]:
    if request.param == "postgres":
        log = ActivityLog(db, reconnect_delay=0.1)
        await log.start()
        try:
            yield log
        finally:
            await log.stop()
        return
    under_test = await fresh_cosmos()
    log = ActivityLog(db, copy=under_test.events, reconnect_delay=0.1, copy_wait=10)
    copier = Copier(db, under_test.events, retry_delay=0.1, reconnect_delay=0.1)
    await log.start()
    await copier.start()
    try:
        yield log
    finally:
        await copier.stop()
        await log.stop()
        await under_test.events.close()


_cosmos_tests: set[str] = set()
_cosmos_outcomes: dict[str, str] = {}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    _cosmos_tests.update(item.nodeid for item in items if item.get_closest_marker("cosmos"))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.nodeid not in _cosmos_tests:
        return
    if report.failed:
        _cosmos_outcomes[report.nodeid] = "failed"
    elif report.skipped:
        _cosmos_outcomes[report.nodeid] = "skipped"
    elif report.when == "call":
        _cosmos_outcomes.setdefault(report.nodeid, "passed")


def _cosmos_counts() -> Counter[str]:
    return Counter(_cosmos_outcomes.values())


def pytest_sessionfinish(session: pytest.Session) -> None:
    counts = _cosmos_counts()
    if os.environ.get("COSMOS_REQUIRED") and (counts["skipped"] or not counts["passed"]):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    counts = _cosmos_counts()
    terminalreporter.write_line(
        f"Cosmos DB tests: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped"
    )
    if os.environ.get("COSMOS_REQUIRED") and (counts["skipped"] or not counts["passed"]):
        terminalreporter.write_line(
            "FAIL: COSMOS_REQUIRED is set, so every Cosmos DB test must run and pass."
        )
