import httpx
import pytest

from agent_runtime.github import GitHubReleaseSource
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable

BASE = "https://github.test"


def source(handler: httpx.MockTransport, token: str | None = None) -> GitHubReleaseSource:
    return GitHubReleaseSource(BASE, token=token, client=httpx.Client(transport=handler))


def answering(status: int, body: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


def test_reads_tags_and_flags_in_the_order_github_gives_them():
    body = [
        {"tag_name": "cli==0.4.37", "prerelease": False, "draft": False, "id": 1},
        {"tag_name": "1.2.17rc", "prerelease": True, "draft": False},
        {"tag_name": "1.2.16", "prerelease": False, "draft": True},
    ]
    assert source(answering(200, body)).fetch("langchain-ai/langgraph") == [
        Release(tag="cli==0.4.37"),
        Release(tag="1.2.17rc", prerelease=True),
        Release(tag="1.2.16", draft=True),
    ]


def test_asks_for_the_repo_releases_with_an_optional_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    source(httpx.MockTransport(handler)).fetch("o/r")
    source(httpx.MockTransport(handler), token="ghp_example").fetch("o/r")
    assert seen[0].url.path == "/repos/o/r/releases"
    assert seen[0].url.params["per_page"] == "30"
    assert "authorization" not in seen[0].headers
    assert seen[1].headers["authorization"] == "Bearer ghp_example"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_server_trouble_is_unavailable(status: int):
    with pytest.raises(SourceUnavailable) as raised:
        source(answering(status, {})).fetch("o/r")
    assert raised.value.status == status


def test_a_network_error_is_unavailable_without_a_status():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SourceUnavailable) as raised:
        source(httpx.MockTransport(down)).fetch("o/r")
    assert raised.value.status is None


def test_a_timeout_is_unavailable_without_a_status():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(SourceUnavailable):
        source(httpx.MockTransport(slow)).fetch("o/r")


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_refusal_is_rejected_not_retried(status: int):
    with pytest.raises(SourceRejected) as raised:
        source(answering(status, {"message": "no"})).fetch("o/r")
    assert raised.value.status == status


@pytest.mark.parametrize("body", [{"not": "a list"}, [{"no_tag": 1}], "text"])
def test_an_unexpected_body_is_unavailable(body: object):
    with pytest.raises(SourceUnavailable):
        source(answering(200, body)).fetch("o/r")


def test_path_segments_are_url_encoded():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    source(httpx.MockTransport(handler)).fetch("a/b?x#y%2f")
    assert seen[0].url.raw_path.startswith(b"/repos/a/b%3Fx%23y%252f/releases")


@pytest.mark.parametrize("repo", ["../x", "a/..", "a/.", "a", "/b", ""])
def test_dot_segments_are_never_sent(repo: str):
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json=[]))
    with pytest.raises(SourceRejected):
        source(transport).fetch(repo)
    assert seen == []


def test_reads_the_name_the_date_and_the_notes_cut_to_400_characters():
    body = [
        {
            "tag_name": "1.2.16",
            "name": "LangGraph 1.2.16",
            "published_at": "2026-10-24T09:00:00Z",
            "body": "n" * 500,
        },
        {"tag_name": "1.2.15", "name": None, "published_at": None, "body": None},
    ]
    found = source(answering(200, body)).fetch("o/r")
    assert found == [
        Release(
            tag="1.2.16",
            name="LangGraph 1.2.16",
            published_at="2026-10-24T09:00:00Z",
            notes="n" * 400,
        ),
        Release(tag="1.2.15"),
    ]


def test_reads_the_address_github_gives_a_repo_now():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": 10270250, "full_name": "react/react"})

    assert source(httpx.MockTransport(handler)).current_name("facebook/react") == "react/react"
    assert seen[0].url.path == "/repos/facebook/react"


def test_an_address_answer_without_a_name_is_unavailable():
    with pytest.raises(SourceUnavailable):
        source(answering(200, {"id": 1})).current_name("o/r")


def test_an_address_github_does_not_find_is_rejected():
    with pytest.raises(SourceRejected) as raised:
        source(answering(404, {"message": "Not Found"})).current_name("gitlab-org/gitlab")
    assert raised.value.status == 404


@pytest.mark.parametrize(
    ("headers", "body", "limited"),
    [
        ({"x-ratelimit-remaining": "0"}, {}, True),
        ({"retry-after": "60"}, {}, True),
        ({}, {"message": "You have exceeded a secondary rate limit."}, True),
        ({"x-ratelimit-remaining": "41"}, {"message": "Resource not accessible"}, False),
        ({}, {}, False),
    ],
)
def test_a_refusal_says_whether_github_limited_how_often_we_ask(
    headers: dict[str, str], body: dict[str, str], limited: bool
):
    transport = httpx.MockTransport(lambda r: httpx.Response(403, json=body, headers=headers))
    for ask in (lambda s: s.fetch("o/r"), lambda s: s.current_name("o/r")):
        with pytest.raises(SourceRejected) as raised:
            ask(source(transport))
        assert (raised.value.status, raised.value.limited) == (403, limited)


def test_a_releases_read_says_whether_github_sent_it_to_another_address():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/repos/"):
            return httpx.Response(301, headers={"Location": f"{BASE}/repositories/7/releases"})
        return httpx.Response(200, json=[{"tag_name": "1.0.0"}])

    moved = GitHubReleaseSource(
        BASE, client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )
    assert moved.fetch_noting_move("old/name").redirected
    assert not source(answering(200, [{"tag_name": "1.0.0"}])).fetch_noting_move("o/r").redirected
