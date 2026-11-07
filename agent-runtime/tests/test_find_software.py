import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent_runtime.api import HttpCallbacks, Runtime, create_app
from agent_runtime.contract import (
    PLAIN_TAG_PATTERN,
    RELEASE_TAG_PATTERN,
    FindSoftwareRequest,
    FoundSoftware,
    SoftwareMatch,
    SoftwareNotChecked,
    SoftwareNotKnown,
)
from agent_runtime.find_software import KNOWN_PROJECTS, SoftwareFinder
from agent_runtime.planner import FixedPlanner
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource
from tests.test_api import KEY, SETTINGS


class FakeProjectSource:
    def __init__(
        self,
        releases: dict[str, list[Release]],
        errors: dict[str, SourceRejected | SourceUnavailable] | None = None,
        moved: dict[str, str] | None = None,
    ) -> None:
        self.releases = releases
        self.errors = errors or {}
        self.moved = moved or {}
        self.asked: list[str] = []

    def current_name(self, repo: str) -> str:
        self.asked.append(repo)
        if repo in self.errors:
            raise self.errors[repo]
        return self.moved.get(repo, repo)

    def fetch(self, repo: str) -> list[Release]:
        self.asked.append(repo)
        return self.releases[repo]


def find(source: FakeProjectSource, name: str, tag_pattern: str = RELEASE_TAG_PATTERN):
    return SoftwareFinder(source).find(name, tag_pattern)


def found(result: object) -> FoundSoftware:
    assert isinstance(result, FoundSoftware)
    return result


def not_checked(result: object) -> SoftwareNotChecked:
    assert isinstance(result, SoftwareNotChecked)
    return result


def test_a_known_name_gives_its_project_checked_on_github():
    source = FakeProjectSource({"kubernetes/kubernetes": [Release("v1.31.2"), Release("v1.31.1")]})
    (match,) = found(find(source, "Kubernetes")).matches
    assert (match.repo, match.releases, match.newest) == (
        "kubernetes/kubernetes",
        "published",
        "v1.31.2",
    )
    assert match.why == "From our list of known projects."
    assert set(source.asked) == {"kubernetes/kubernetes"}


def test_a_name_is_read_whatever_its_case_spacing_or_punctuation():
    source = FakeProjectSource({"nodejs/node": [Release("v22.0.0")]})
    for typed in ["  NODE.js ", "node-js", "Node"]:
        assert found(find(source, typed)).matches[0].repo == "nodejs/node"


def test_an_unknown_name_is_not_guessed_and_nothing_is_asked_of_github():
    source = FakeProjectSource({})
    result = find(source, "Zorblax")
    assert isinstance(result, SoftwareNotKnown)
    assert "Zorblax" in result.message
    assert "owner/name" in result.message
    assert source.asked == []


def test_a_part_of_a_known_name_is_not_a_match():
    assert isinstance(find(FakeProjectSource({}), "Kuber"), SoftwareNotKnown)


def test_a_name_with_two_projects_offers_both_each_saying_what_it_is():
    source = FakeProjectSource(
        {
            "hashicorp/terraform": [Release("v1.9.8")],
            "opentofu/opentofu": [Release("v1.8.5")],
        }
    )
    terraform, opentofu = found(find(source, "Terraform")).matches
    assert (terraform.repo, opentofu.repo) == ("hashicorp/terraform", "opentofu/opentofu")
    assert terraform.what.startswith("Terraform")
    assert opentofu.what.startswith("OpenTofu")
    assert "fork of Terraform" in opentofu.what
    assert terraform.why == opentofu.why == "From our list of known projects."


def test_every_project_on_the_list_can_be_offered():
    for project in KNOWN_PROJECTS:
        match = SoftwareMatch(
            repo=project.repo, what=project.what, why="", releases="none", newest=None
        )
        assert match.what


def test_the_newest_release_is_the_newest_tag_the_watch_would_count():
    source = FakeProjectSource(
        {
            "langchain-ai/langgraph": [
                Release("sdk==0.4.14"),
                Release("1.2.21rc1", prerelease=True),
                Release("1.2.20"),
                Release("cli==0.4.37"),
            ]
        }
    )
    (match,) = found(find(source, "LangGraph")).matches
    assert (match.releases, match.newest) == ("published", "1.2.20")


def test_a_project_whose_tags_the_watch_ignores_has_no_release_to_compare():
    source = FakeProjectSource({"n8n-io/n8n": [Release("stable"), Release("n8n-nightly@2.46.6")]})
    (match,) = found(find(source, "n8n")).matches
    assert (match.releases, match.newest) == ("none", None)


@pytest.mark.parametrize(
    ("name", "repo", "tags", "newest"),
    [
        (
            "Docker Engine",
            "moby/moby",
            ["docker-v29.1.0", "docker-v29.0.4", "v25.0.18"],
            "docker-v29.1.0",
        ),
        ("n8n", "n8n-io/n8n", ["n8n@2.4.2", "n8n@2.4.1", "stable"], "n8n@2.4.2"),
        (
            "LangChain",
            "langchain-ai/langchain",
            ["langchain-core==0.3.9", "langchain==0.3.4", "langchain==0.3.3"],
            "langchain==0.3.4",
        ),
    ],
    ids=["moby", "n8n", "langchain"],
)
def test_a_project_that_prefixes_its_tags_has_a_release_to_compare(
    name: str, repo: str, tags: list[str], newest: str
):
    source = FakeProjectSource({repo: [Release(tag) for tag in tags]})
    (match,) = found(find(source, name)).matches
    assert (match.releases, match.newest) == ("published", newest)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_name_is_refused_before_it_is_looked_up(blank: str):
    with pytest.raises(ValidationError, match="at least 1 character"):
        FindSoftwareRequest(name=blank, tag_pattern=RELEASE_TAG_PATTERN)


def test_a_name_is_trimmed_before_it_is_looked_up():
    request = FindSoftwareRequest(name="  Kubernetes ", tag_pattern=RELEASE_TAG_PATTERN)
    assert request.name == "Kubernetes"


def test_the_tag_rule_comes_from_the_request():
    source = FakeProjectSource({"kubernetes/kubernetes": [Release("v1.31.2")]})
    with_v = found(find(source, "Kubernetes", RELEASE_TAG_PATTERN)).matches[0]
    without_v = found(find(source, "Kubernetes", PLAIN_TAG_PATTERN)).matches[0]
    assert with_v.newest == "v1.31.2"
    assert (without_v.releases, without_v.newest) == ("none", None)


def test_a_project_with_no_releases_is_offered_but_marked_so():
    source = FakeProjectSource({"postgres/postgres": []})
    (match,) = found(find(source, "Postgres")).matches
    assert (match.releases, match.newest) == ("none", None)


def test_drafts_and_prereleases_do_not_count_as_releases():
    source = FakeProjectSource(
        {"redis/redis": [Release("8.0.0", prerelease=True), Release("9.9.9", draft=True)]}
    )
    (match,) = found(find(source, "Redis")).matches
    assert (match.releases, match.newest) == ("none", None)


def test_a_moved_project_is_offered_at_the_address_github_gives_now():
    source = FakeProjectSource(
        {"k8s/kubernetes": [Release("v1.31.2")]},
        moved={"kubernetes/kubernetes": "k8s/kubernetes"},
    )
    (match,) = found(find(source, "Kubernetes")).matches
    assert (match.repo, match.newest) == ("k8s/kubernetes", "v1.31.2")
    assert "kubernetes/kubernetes" in match.why
    assert "k8s/kubernetes" in match.why


def test_a_project_github_does_not_find_is_dropped_not_offered():
    source = FakeProjectSource(
        {"hashicorp/terraform": [Release("v1.9.8")]},
        errors={"opentofu/opentofu": SourceRejected(404)},
    )
    result = found(find(source, "Terraform"))
    assert [m.repo for m in result.matches] == ["hashicorp/terraform"]


def test_when_github_finds_none_of_them_the_answer_says_only_that():
    source = FakeProjectSource({}, errors={"redis/redis": SourceRejected(404)})
    result = find(source, "Redis")
    assert isinstance(result, SoftwareNotKnown)
    assert "GitHub didn't find redis/redis" in result.message
    assert "no longer" not in result.message
    assert "owner/name" in result.message


@pytest.mark.parametrize(
    ("error", "says", "then"),
    [
        (
            SourceRejected(401),
            "GitHub did not accept the key in the GitHub connection",
            "Ask whoever looks after the platform to check that connection.",
        ),
        (
            SourceRejected(403, limited=True),
            "GitHub is limiting how often we can ask it",
            "Try again later.",
        ),
        (SourceUnavailable(429), "GitHub is limiting how often we can ask it", "Try again later."),
        (SourceUnavailable(None), "I couldn't reach GitHub", "Try again later."),
        (SourceUnavailable(503), "GitHub answered 503 Service Unavailable", "Try again later."),
        (SourceRejected(403), "GitHub answered 403 Forbidden", ""),
    ],
)
def test_when_github_cannot_check_nothing_is_offered_and_the_answer_says_why(
    error: SourceRejected | SourceUnavailable, says: str, then: str
):
    result = not_checked(find(FakeProjectSource({}, errors={"redis/redis": error}), "Redis"))
    assert result.message.startswith(f"{says}, so I can't check Redis yet.")
    assert result.message.endswith(then)
    assert "minute" not in result.message


def test_one_unchecked_project_holds_back_the_whole_answer():
    source = FakeProjectSource(
        {"hashicorp/terraform": [Release("v1.9.8")]},
        errors={"opentofu/opentofu": SourceUnavailable(503)},
    )
    assert isinstance(find(source, "Terraform"), SoftwareNotChecked)


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
    finder = SoftwareFinder(FakeProjectSource({"n8n-io/n8n": [Release("2.42.6")]}))
    http = client(finder)
    ask = {"name": "n8n", "tag_pattern": RELEASE_TAG_PATTERN}
    body = http.post("/v1/software/find", json=ask).json()
    assert body["status"] == "found"
    assert body["matches"][0]["repo"] == "n8n-io/n8n"
    assert body["matches"][0]["newest"] == "2.42.6"
    unknown = http.post("/v1/software/find", json={**ask, "name": "Zorblax"}).json()
    assert unknown["status"] == "not_known"
    assert http.post("/v1/software/find", json={**ask, "name": ""}).status_code == 422
    assert http.post("/v1/software/find", json={**ask, "name": "   "}).status_code == 422
    assert http.post("/v1/software/find", json={"name": "n8n"}).status_code == 422
    assert http.post("/v1/software/find", json={**ask, "tag_pattern": ".*"}).status_code == 422
    assert (
        http.post("/v1/software/find", json=ask, headers={"X-Agent-Key": "no"}).status_code == 401
    )


def test_a_runtime_without_a_finder_says_so():
    ask = {"name": "n8n", "tag_pattern": RELEASE_TAG_PATTERN}
    assert client(None).post("/v1/software/find", json=ask).status_code == 501
