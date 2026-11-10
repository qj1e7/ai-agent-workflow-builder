"""Software read from Maven Central or npm, and the vulnerabilities the check reports (ADR 0025)."""

import psycopg
import pytest
from pydantic import ValidationError

from platform_api.builder import Builder, Watchlist
from platform_api.builder.models import AddSoftware, PackageIn, WatchlistView
from platform_api.builder.watchlist import RepoAlreadyWatched, source_url
from platform_api.db import Database
from platform_api.orchestration import (
    RunSpec,
    ScheduleBook,
    SoftwareSource,
    WatchedSoftware,
    WatchlistTask,
)
from platform_api.orchestration.agents import (
    GithubSource,
    MavenSource,
    NpmSource,
    TaskFinished,
    source_in,
    task_result_adapter,
)
from platform_api.shared import UseCaseId
from tests.conftest import PostgresUrls
from tests.support import ALICE
from tests.test_watchlist_builder import FakeFacts, FakeRuns, added

pytestmark = pytest.mark.anyio

LOG4J = "org.apache.logging.log4j:log4j-core"


@pytest.fixture
def facts() -> FakeFacts:
    return FakeFacts()


@pytest.fixture
def watchlist(db: Database, facts: FakeFacts) -> Watchlist:
    return Watchlist(db, facts, ScheduleBook(db))


@pytest.fixture
def builder(db: Database, watchlist: Watchlist) -> Builder:
    return Builder(db, FakeRuns(), watchlist, "http://localhost:8080")


def package(name: str, kind: str, ref: str, our_version: str | None = None) -> AddSoftware:
    return AddSoftware.model_validate(
        {"name": name, "package": {"kind": kind, "ref": ref}, "our_version": our_version}
    )


@pytest.mark.parametrize(
    "body",
    [
        {"name": "X"},
        {"name": "X", "repo": "a/b", "package": {"kind": "npm", "ref": "express"}},
    ],
)
def test_an_add_names_a_repository_or_a_package_never_both_or_neither(body: dict[str, object]):
    with pytest.raises(ValidationError, match="give repo or package"):
        AddSoftware.model_validate(body)


@pytest.mark.parametrize(
    ("kind", "ref"),
    [
        ("maven", "org..evil:x"),
        ("maven", "no-artifact"),
        ("npm", "../etc"),
        ("npm", "UPPER"),
        ("pypi", "requests"),
    ],
)
def test_a_package_its_registry_would_not_name_is_refused(kind: str, ref: str):
    with pytest.raises(ValidationError):
        PackageIn.model_validate({"kind": kind, "ref": ref})


def test_a_github_add_still_reads_as_before():
    body = AddSoftware(name="LangGraph", repo="langchain-ai/langgraph", our_version="1.2.14")
    assert (body.source_kind, body.source_ref) == ("github", "langchain-ai/langgraph")
    log4j = package("Log4j", "maven", LOG4J)
    assert (log4j.source_kind, log4j.source_ref) == ("maven", LOG4J)


def test_each_source_links_the_page_that_lists_its_versions():
    assert source_url(SoftwareSource("redis/redis")) == "https://github.com/redis/redis/releases"
    assert source_url(SoftwareSource(LOG4J, "maven")) == (
        "https://central.sonatype.com/artifact/org.apache.logging.log4j/log4j-core/versions"
    )
    assert source_url(SoftwareSource("@angular/core", "npm")) == (
        "https://www.npmjs.com/package/@angular/core?activeTab=versions"
    )


def test_the_task_names_each_source_as_the_agent_api_does():
    assert source_in("github", "redis/redis") == GithubSource(ref="redis/redis")
    assert source_in("maven", LOG4J) == MavenSource(ref=LOG4J)
    assert source_in("npm", "express") == NpmSource(ref="express")


def test_a_finding_with_vulnerabilities_is_read_from_the_agent():
    finding = {
        "software_id": "sw_01JC2A3B4C5D6E7F8G9H0J1K2L",
        "state": "behind",
        "newest": "2.24.3",
        "new_versions": ["2.24.3"],
        "detail": "1 release newer than 2.14.1.",
        "vulnerability_check": "checked",
        "vulnerabilities": [
            {
                "id": "CVE-2021-44228",
                "severity": "critical",
                "score": 10.0,
                "summary": "Log4Shell",
                "fixed_in": "2.15.0",
                "reported_by": ["OSV", "NVD"],
                "url": "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
            }
        ],
    }
    result = task_result_adapter.validate_python(
        {
            "task_id": "tsk_1",
            "status": "finished",
            "output": {
                "summary": "s",
                "new_tags": [],
                "proposed": [],
                "carry_forward": {},
                "findings": [finding],
            },
            "events": [],
        }
    )
    assert isinstance(result, TaskFinished)
    [read] = result.output.findings
    assert read.vulnerability_check == "checked"
    assert [(v.id, v.score) for v in read.vulnerabilities] == [("CVE-2021-44228", 10.0)]


async def test_a_package_is_saved_with_its_kind_and_shown_with_its_registry_page(
    watchlist: Watchlist,
):
    view = await added(watchlist, package("Log4j", "maven", LOG4J, "2.14.1"))
    [row] = view.software
    assert (row.source.kind, row.source.ref) == ("maven", LOG4J)
    assert row.source.url.startswith("https://central.sonatype.com/artifact/")
    assert (row.moved_to, row.not_found) == (None, False)
    assert await watchlist.view() == view


async def test_one_package_is_watched_once_but_the_same_name_on_another_source_is_not_the_same(
    watchlist: Watchlist,
):
    await added(watchlist, package("Express", "npm", "express"))
    again = await watchlist.add(ALICE, package("Express again", "npm", "express"))
    assert again == RepoAlreadyWatched("express")
    # A GitHub repository whose owner/name happens to read alike is another source.
    other = await watchlist.add(
        ALICE, AddSoftware(name="Express on GitHub", repo="expressjs/express")
    )
    assert isinstance(other, WatchlistView)


async def test_a_check_sends_each_package_with_its_kind(
    watchlist: Watchlist, builder: Builder, facts: FakeFacts
):
    await added(watchlist, package("Log4j", "maven", LOG4J, "2.14.1"))
    view = await added(watchlist, package("Express", "npm", "express", "4.21.2"))
    spec = await builder.run_spec_for(UseCaseId(view.use_case_id))
    assert isinstance(spec, RunSpec)
    assert isinstance(spec.task, WatchlistTask)
    assert [(s.name, s.source) for s in spec.task.software if isinstance(s, WatchedSoftware)] == [
        ("Log4j", SoftwareSource(LOG4J, "maven")),
        ("Express", SoftwareSource("express", "npm")),
    ]


def test_the_database_holds_only_the_source_kinds_the_platform_reads(postgres: PostgresUrls):
    with psycopg.connect(postgres.owner) as conn:
        row = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'watched_software_source_kind_check'"
        ).fetchone()
    assert row is not None
    definition = str(row[0])
    for kind in ("github", "maven", "npm"):
        assert f"'{kind}'" in definition
    assert "pypi" not in definition
