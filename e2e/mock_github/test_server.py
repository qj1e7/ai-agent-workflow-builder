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
    connection = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    try:
        payload = None if body is None else json.dumps(body)
        connection.request("GET" if body is None else "POST", path, body=payload)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
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


if __name__ == "__main__":
    unittest.main()
