"""The hourly look at the daily self-test: a warning in the logs while the error workflow does
not report, so App Insights shows it without anyone reading /healthz/ready, and rows kept 90
days."""

import logging
from collections.abc import Iterator

import psycopg
import pytest

from platform_api.db import Database
from platform_api.orchestration.self_test import watch
from tests.conftest import PostgresUrls

pytestmark = pytest.mark.anyio


def plant(owner_url: str, execution: str, arrived_days_ago: float | None, sent_days_ago: float):
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.self_tests (execution_id, workflow_id, sent_at, arrived_at) "
            "VALUES (%s, 'wf_self_test', now() - make_interval(secs => %s), "
            "now() - make_interval(secs => %s))",
            (
                execution,
                sent_days_ago * 86400,
                None if arrived_days_ago is None else arrived_days_ago * 86400,
            ),
        )


def kept(owner_url: str) -> list[str]:
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT execution_id FROM orchestration.self_tests ORDER BY 1"
        ).fetchall()
    return [str(row[0]) for row in rows]


@pytest.fixture
def warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.WARNING, logger="platform_api.orchestration.self_test"):
        yield caplog


def said(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


async def test_a_missed_self_test_is_a_warning_in_the_logs(
    db: Database, postgres: PostgresUrls, warnings: pytest.LogCaptureFixture
):
    plant(postgres.owner, "300", 2, 2)
    await watch(db)
    [line] = said(warnings)
    assert line.startswith("the daily self-test: no self-test has reached the platform since ")


async def test_a_self_test_that_arrived_says_nothing(
    db: Database, postgres: PostgresUrls, warnings: pytest.LogCaptureFixture
):
    plant(postgres.owner, "300", 0.5, 0.5)
    await watch(db)
    assert said(warnings) == []


async def test_self_tests_are_kept_90_days(db: Database, postgres: PostgresUrls):
    plant(postgres.owner, "old", 91, 91)
    plant(postgres.owner, "unreported", None, 91)
    plant(postgres.owner, "recent", 89, 89)
    await watch(db)
    assert kept(postgres.owner) == ["recent"]
