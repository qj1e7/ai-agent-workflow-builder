"""POST /v1/releases/read: one read of a repository's counted releases, for the platform's Read
block in n8n (ENGINE-PLAN 2.2)."""

from fastapi.testclient import TestClient

from agent_runtime.api import HttpCallbacks, Runtime, create_app
from agent_runtime.contract import RELEASE_TAG_PATTERN
from agent_runtime.planner import FixedPlanner
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource
from tests.test_api import KEY, SETTINGS

REPO = "langchain-ai/langgraph"


class Releases:
    def __init__(self, releases: list[Release], error: Exception | None = None) -> None:
        self.releases = releases
        self.error = error
        self.asked: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.asked.append(repo)
        if self.error is not None:
            raise self.error
        return self.releases


def client(releases: Releases | None) -> TestClient:
    clock = FakeClock()
    runtime = Runtime(
        checker=VersionChecker(FakeSource([]), TemplateSummarizer(), sleep=clock.sleep),
        planner=FixedPlanner(),
        clock=clock,
        callbacks=HttpCallbacks(),
        releases=releases,
    )
    return TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})


ASK = {"repo": REPO, "tag_pattern": RELEASE_TAG_PATTERN}


def test_it_reads_only_the_stable_releases_the_tag_rule_counts_newest_first():
    source = Releases(
        [
            Release("1.2.17rc1", prerelease=True),
            Release("1.2.16", name="1.2.16", published_at="2026-11-12T08:00:00Z"),
            Release("docs-2026", name="Docs"),
            Release("1.2.15"),
        ]
    )
    body = client(source).post("/v1/releases/read", json=ASK).json()
    assert body["status"] == "read"
    assert [r["tag"] for r in body["releases"]] == ["1.2.16", "1.2.15"]
    assert source.asked == [REPO]


def test_github_trouble_is_said_once_and_whether_to_try_again():
    down = client(Releases([], SourceUnavailable(503))).post("/v1/releases/read", json=ASK).json()
    assert (down["status"], down["retryable"]) == ("not_read", True)
    gone = client(Releases([], SourceRejected(404))).post("/v1/releases/read", json=ASK).json()
    assert (gone["status"], gone["retryable"]) == ("not_read", False)
    assert "404" in gone["message"]


def test_it_needs_the_key_and_a_repository_name():
    http = client(Releases([]))
    assert http.post("/v1/releases/read", json={**ASK, "repo": "../etc"}).status_code == 422
    assert (
        http.post("/v1/releases/read", json=ASK, headers={"X-Agent-Key": "no"}).status_code == 401
    )
    assert client(None).post("/v1/releases/read", json=ASK).status_code == 501
