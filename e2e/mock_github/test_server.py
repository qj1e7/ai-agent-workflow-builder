import http.client
import json
import threading
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import Any

import server

RELEASES_URL = "/repos/langchain-ai/langgraph/releases"
REDIS = "redis/redis"
REDIS_URL = f"/repos/{REDIS}/releases"


@contextmanager
def running() -> Generator[str]:
    httpd: ThreadingHTTPServer = server.build_server("127.0.0.1", 0, server.State())
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(base: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    status, _, parsed = call_with(base, path, body)
    return status, parsed


def call_with(
    base: str, path: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, dict[str, str], Any]:
    connection = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    try:
        payload = None if body is None else json.dumps(body)
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        connection.request("GET" if body is None else "POST", path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())
    finally:
        connection.close()


class MockGithubTest(unittest.TestCase):
    def test_serves_thirty_releases_newest_first(self) -> None:
        with running() as base:
            status, releases = call(base, RELEASES_URL)
        self.assertEqual(status, 200)
        self.assertEqual(len(releases), 30)
        self.assertEqual([r["tag_name"] for r in releases[:3]], ["1.2.16", "1.2.15", "1.2.14"])
        stamps = [r["published_at"] for r in releases]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_release_has_the_shape_of_github(self) -> None:
        with running() as base:
            _, releases = call(base, RELEASES_URL)
        for key in ("tag_name", "name", "draft", "prerelease", "published_at", "html_url", "id"):
            self.assertIn(key, releases[0])

    def test_other_tag_families_are_present(self) -> None:
        with running() as base:
            _, releases = call(base, RELEASES_URL)
        self.assertTrue(any(r["tag_name"].startswith("cli==") for r in releases))

    def test_one_repository_carries_a_planted_order_in_its_release_notes(self) -> None:
        with running() as base:
            status, releases = call(base, "/repos/acme/planted/releases")
        self.assertEqual(status, 200)
        self.assertEqual([r["tag_name"] for r in releases], ["2.0.0"])
        self.assertIn("Jira project SECRET", releases[0]["body"])

    def test_the_rate_limit_answers_without_a_token_with_the_anonymous_limit(self) -> None:
        with running() as base:
            status, headers, body = call_with(base, "/rate_limit")
        self.assertEqual(status, 200)
        self.assertEqual(body["rate"]["limit"], 60)
        self.assertNotIn(server.EXPIRY_HEADER, {name.lower() for name in headers})

    def test_the_rate_limit_accepts_a_good_token(self) -> None:
        with running() as base:
            status, headers, body = call_with(base, "/rate_limit", token=server.GOOD_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body["rate"]["limit"], 5000)
        self.assertNotIn(server.EXPIRY_HEADER, {name.lower() for name in headers})

    def test_the_rate_limit_names_when_an_expiring_token_runs_out(self) -> None:
        with running() as base:
            status, headers, _ = call_with(base, "/rate_limit", token=server.EXPIRING_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(
            {name.lower(): value for name, value in headers.items()}[server.EXPIRY_HEADER],
            server.TOKEN_EXPIRES,
        )

    def test_the_rate_limit_refuses_a_token_it_does_not_know(self) -> None:
        with running() as base:
            status, _, body = call_with(base, "/rate_limit", token="ghp_something_else")
        self.assertEqual(status, 401)
        self.assertEqual(body, {"message": "Bad credentials"})

    def test_the_rate_limit_follows_the_unavailable_mode(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "unavailable"})
            status, _, _ = call_with(base, "/rate_limit", token=server.GOOD_TOKEN)
        self.assertEqual(status, 503)

    def test_pagination(self) -> None:
        with running() as base:
            _, first = call(base, RELEASES_URL + "?per_page=10&page=1")
            _, last = call(base, RELEASES_URL + "?per_page=10&page=3")
            _, beyond = call(base, RELEASES_URL + "?per_page=10&page=4")
        self.assertEqual(len(first), 10)
        self.assertEqual(len(last), 10)
        self.assertEqual(beyond, [])

    def test_unavailable_mode_answers_503_then_recovers(self) -> None:
        with running() as base:
            self.assertEqual(
                call(base, "/_admin/mode", {"mode": "unavailable"}), (200, {"mode": "unavailable"})
            )
            status, body = call(base, RELEASES_URL)
            self.assertEqual((status, body["message"]), (503, "Service Unavailable"))
            self.assertEqual(call(base, "/healthz")[0], 200)
            call(base, "/_admin/mode", {"mode": "ok"})
            self.assertEqual(call(base, RELEASES_URL)[0], 200)

    def test_mode_can_be_read_back(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "unavailable"})
            self.assertEqual(call(base, "/_admin/mode"), (200, {"mode": "unavailable"}))

    def test_bad_mode_is_rejected_and_mode_unchanged(self) -> None:
        with running() as base:
            self.assertEqual(call(base, "/_admin/mode", {"mode": "slow"})[0], 400)
            self.assertEqual(call(base, "/_admin/mode", {})[0], 400)
            self.assertEqual(call(base, "/_admin/mode")[1], {"mode": "ok"})

    def test_unknown_repo_is_404(self) -> None:
        with running() as base:
            self.assertEqual(call(base, "/repos/someone/else/releases")[0], 404)
            self.assertEqual(call(base, "/repos/redis/releases")[0], 404)

    def test_a_repository_answers_with_the_address_github_gives_it(self) -> None:
        with running() as base:
            status, body = call(base, "/repos/langchain-ai/langgraph")
            _, other = call(base, "/repos/redis/redis/")
        self.assertEqual(status, 200)
        self.assertEqual(body["full_name"], "langchain-ai/langgraph")
        self.assertEqual(other["full_name"], "redis/redis")

    def test_an_unknown_repository_has_no_address_and_follows_its_mode(self) -> None:
        with running() as base:
            self.assertEqual(call(base, "/repos/someone/else")[0], 404)
            call(base, "/_admin/mode", {"mode": "not_found", "repo": "redis/redis"})
            self.assertEqual(call(base, "/repos/redis/redis")[0], 404)
            call(base, "/_admin/mode", {"mode": "unavailable"})
            self.assertEqual(call(base, "/repos/langchain-ai/langgraph")[0], 503)

    def test_n8n_tags_carry_its_prefix(self) -> None:
        with running() as base:
            _, releases = call(base, "/repos/n8n-io/n8n/releases")
        self.assertEqual([r["tag_name"] for r in releases[:2]], ["n8n@2.4.2", "n8n@2.4.1"])

    def test_a_second_repository_has_its_own_releases(self) -> None:
        with running() as base:
            status, releases = call(base, "/repos/redis/redis/releases")
            _, paged = call(base, "/repos/redis/redis/releases?per_page=2&page=2")
        self.assertEqual(status, 200)
        self.assertEqual([r["tag_name"] for r in releases[:2]], ["8.2.1", "8.2.0"])
        self.assertEqual(len(releases), len(server.REDIS_TAGS))
        urls = [r["html_url"] for r in releases]
        self.assertTrue(all(url.startswith("https://github.com/redis/redis/") for url in urls))
        self.assertEqual([r["tag_name"] for r in paged], ["8.0.3", "8.0.2"])

    def test_fastapi_has_plain_releases_newer_than_the_version_the_review_adds(self) -> None:
        with running() as base:
            status, releases = call(base, "/repos/fastapi/fastapi/releases")
        self.assertEqual(status, 200)
        tags = [r["tag_name"] for r in releases]
        self.assertEqual(tags, server.FASTAPI_TAGS)
        self.assertEqual(tags[0], "0.115.6")
        self.assertIn("0.115.0", tags)
        urls = [r["html_url"] for r in releases]
        self.assertTrue(all(url.startswith("https://github.com/fastapi/fastapi/") for url in urls))

    def test_unavailable_mode_covers_every_repository(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "unavailable"})
            self.assertEqual(call(base, "/repos/redis/redis/releases")[0], 503)
            self.assertEqual(call(base, "/repos/someone/else/releases")[0], 503)

    def test_one_repository_can_fail_while_the_others_answer(self) -> None:
        with running() as base:
            set_redis = call(base, "/_admin/mode", {"mode": "unavailable", "repo": REDIS})
            self.assertEqual(set_redis, (200, {"mode": "unavailable", "repo": REDIS}))
            self.assertEqual(call(base, REDIS_URL)[0], 503)
            self.assertEqual(call(base, RELEASES_URL)[0], 200)
            read_back = call(base, f"/_admin/mode?repo={REDIS}")
            self.assertEqual(read_back, (200, {"mode": "unavailable", "repo": REDIS}))
            self.assertEqual(call(base, "/_admin/mode"), (200, {"mode": "ok"}))

    def test_not_found_mode_answers_404_for_a_repository_it_knows(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "not_found", "repo": REDIS})
            status, body = call(base, REDIS_URL)
            self.assertEqual((status, body["message"]), (404, "Not Found"))
            self.assertEqual(call(base, RELEASES_URL)[0], 200)

    def test_two_repositories_can_fail_for_different_reasons(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "unavailable", "repo": "langchain-ai/langgraph"})
            call(base, "/_admin/mode", {"mode": "not_found", "repo": REDIS})
            self.assertEqual(call(base, RELEASES_URL)[0], 503)
            self.assertEqual(call(base, REDIS_URL)[0], 404)
            self.assertEqual(call(base, "/repos/fastapi/fastapi/releases")[0], 200)

    def test_a_mode_for_every_repository_clears_each_repositorys_own(self) -> None:
        with running() as base:
            call(base, "/_admin/mode", {"mode": "unavailable", "repo": REDIS})
            self.assertEqual(call(base, "/_admin/mode", {"mode": "ok"}), (200, {"mode": "ok"}))
            self.assertEqual(call(base, REDIS_URL)[0], 200)
            self.assertEqual(call(base, f"/_admin/mode?repo={REDIS}")[1]["mode"], "ok")

    def test_a_repository_mode_needs_an_owner_and_a_name(self) -> None:
        with running() as base:
            for repo in ("redis", 5):
                asked = {"mode": "unavailable", "repo": repo}
                self.assertEqual(call(base, "/_admin/mode", asked)[0], 400)
            self.assertEqual(call(base, "/_admin/mode?repo=redis")[0], 400)
            self.assertEqual(call(base, REDIS_URL)[0], 200)


if __name__ == "__main__":
    unittest.main()
