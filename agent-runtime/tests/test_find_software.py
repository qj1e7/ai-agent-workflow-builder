import pytest
from fastapi.testclient import TestClient

from agent_runtime.api import HttpCallbacks, Runtime, create_app
from agent_runtime.contract import FoundSoftware, SoftwareNotChecked, SoftwareNotKnown
from agent_runtime.find_software import SoftwareFinder
from agent_runtime.planner import FixedPlanner
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource
from tests.test_api import KEY, SETTINGS


class ByRepo:
    def __init__(
        self,
        releases: dict[str, list[Release]],
        refused: dict[str, int] | None = None,
        down: set[str] | None = None,
    ) -> None:
        self.releases = releases
        self.refused = refused or {}
        self.down = down or set()
        self.calls: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.calls.append(repo)
        if repo in self.down:
            raise SourceUnavailable(503)
        if repo in self.refused:
            raise SourceRejected(self.refused[repo])
        return self.releases[repo]


def found(result: object) -> FoundSoftware:
    assert isinstance(result, FoundSoftware)
    return result


def test_a_known_name_gives_its_project_checked_on_github():
    source = ByRepo({"kubernetes/kubernetes": [Release("v1.31.2"), Release("v1.31.1")]})
    result = found(SoftwareFinder(source).find("Kubernetes"))
    (match,) = result.matches
    assert (match.repo, match.releases, match.newest) == (
        "kubernetes/kubernetes",
        "published",
        "v1.31.2",
    )
    assert "usually kubernetes/kubernetes" in match.why
    assert source.calls == ["kubernetes/kubernetes"]


def test_a_name_is_read_whatever_its_case_spacing_or_punctuation():
    source = ByRepo({"nodejs/node": [Release("v22.0.0")]})
    for typed in ["  NODE.js ", "node-js", "Node"]:
        assert found(SoftwareFinder(source).find(typed)).matches[0].repo == "nodejs/node"


def test_an_unknown_name_is_not_guessed_and_nothing_is_asked_of_github():
    source = ByRepo({})
    result = SoftwareFinder(source).find("Zorblax")
    assert isinstance(result, SoftwareNotKnown)
    assert "Zorblax" in result.message
    assert "owner/name" in result.message
    assert source.calls == []


def test_a_part_of_a_known_name_is_not_a_match():
    assert isinstance(SoftwareFinder(ByRepo({})).find("Kuber"), SoftwareNotKnown)


def test_a_name_with_two_projects_offers_both_for_the_person_to_choose():
    source = ByRepo(
        {
            "hashicorp/terraform": [Release("v1.9.8")],
            "opentofu/opentofu": [Release("v1.8.5")],
        }
    )
    result = found(SoftwareFinder(source).find("Terraform"))
    assert [m.repo for m in result.matches] == ["hashicorp/terraform", "opentofu/opentofu"]


def test_a_project_with_no_releases_is_offered_but_marked_so():
    source = ByRepo({"postgres/postgres": []})
    (match,) = found(SoftwareFinder(source).find("Postgres")).matches
    assert (match.releases, match.newest) == ("none", None)


def test_drafts_and_prereleases_do_not_count_as_releases():
    source = ByRepo(
        {"redis/redis": [Release("8.0-rc1", prerelease=True), Release("9.9.9", draft=True)]}
    )
    (match,) = found(SoftwareFinder(source).find("Redis")).matches
    assert (match.releases, match.newest) == ("none", None)


def test_a_project_github_no_longer_has_is_dropped_not_offered():
    source = ByRepo(
        {"hashicorp/terraform": [Release("v1.9.8")]}, refused={"opentofu/opentofu": 404}
    )
    result = found(SoftwareFinder(source).find("Terraform"))
    assert [m.repo for m in result.matches] == ["hashicorp/terraform"]


def test_when_every_project_is_gone_the_answer_is_not_known():
    source = ByRepo({}, refused={"redis/redis": 404})
    assert isinstance(SoftwareFinder(source).find("Redis"), SoftwareNotKnown)


@pytest.mark.parametrize("trouble", ["down", "rate_limited"])
def test_when_github_cannot_check_nothing_is_offered(trouble: str):
    source = (
        ByRepo({}, down={"redis/redis"}) if trouble == "down" else ByRepo({}, {"redis/redis": 403})
    )
    result = SoftwareFinder(source).find("Redis")
    assert isinstance(result, SoftwareNotChecked)


def test_one_unchecked_project_holds_back_the_whole_answer():
    source = ByRepo({"hashicorp/terraform": [Release("v1.9.8")]}, down={"opentofu/opentofu"})
    assert isinstance(SoftwareFinder(source).find("Terraform"), SoftwareNotChecked)


def client(finder: SoftwareFinder | None) -> TestClient:
    clock = FakeClock()
    checker = VersionChecker(FakeSource([]), TemplateSummarizer(), sleep=clock.sleep)
    runtime = Runtime(
        checker=checker,
        planner=FixedPlanner(),
        clock=clock,
        callbacks=HttpCallbacks(),
        finder=finder,
    )
    return TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})


def test_the_route_answers_with_a_status_and_needs_the_key():
    finder = SoftwareFinder(ByRepo({"n8n-io/n8n": [Release("2.42.6")]}))
    http = client(finder)
    body = http.post("/v1/software/find", json={"name": "n8n"}).json()
    assert body["status"] == "found"
    assert body["matches"][0]["repo"] == "n8n-io/n8n"
    unknown = http.post("/v1/software/find", json={"name": "Zorblax"}).json()
    assert unknown["status"] == "not_known"
    assert http.post("/v1/software/find", json={"name": ""}).status_code == 422
    assert (
        http.post(
            "/v1/software/find", json={"name": "n8n"}, headers={"X-Agent-Key": "no"}
        ).status_code
        == 401
    )


def test_a_runtime_without_a_finder_says_so():
    assert client(None).post("/v1/software/find", json={"name": "n8n"}).status_code == 501
