import base64
import http.client
import json
import threading
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import Any

import confluence_server as server

BOT = "Basic " + base64.b64encode(f"{server.EMAIL}:{server.TOKEN}".encode()).decode()
INVENTORY = f"/wiki/rest/api/content/{server.INVENTORY}?expand=body.storage,version"


@contextmanager
def running() -> Generator[str]:
    httpd: ThreadingHTTPServer = server.build_server("127.0.0.1", 0, server.State())
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(
    host: str, path: str, auth: str | None = BOT, body: dict[str, Any] | None = None
) -> tuple[int, Any]:
    connection = http.client.HTTPConnection(host, timeout=5)
    headers = {"Authorization": auth} if auth else {}
    try:
        if body is None:
            connection.request("GET", path, headers=headers)
        else:
            connection.request("POST", path, json.dumps(body), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class MockConfluenceTest(unittest.TestCase):
    def test_the_bot_is_known_anyone_else_is_anonymous_or_refused(self) -> None:
        with running() as host:
            self.assertEqual(call(host, "/wiki/rest/api/user/current")[1]["type"], "known")
            self.assertEqual(
                call(host, "/wiki/rest/api/user/current", auth=None)[1], {"type": "anonymous"}
            )
            self.assertEqual(call(host, "/wiki/rest/api/user/current", auth="Basic eDp5")[0], 401)

    def test_the_inventory_is_a_page_in_storage_format_with_its_version(self) -> None:
        with running() as host:
            status, page = call(host, INVENTORY)
            self.assertEqual(status, 200)
            self.assertEqual((page["title"], page["version"]["number"]), ("Software inventory", 7))
            storage = page["body"]["storage"]["value"]
            self.assertIn("<td><p>LangGraph</p></td><td><p>1.2.14</p></td>", storage)
            self.assertEqual(storage.count("<tr>"), 4)

    def test_a_page_needs_the_bot_and_an_unknown_page_is_404(self) -> None:
        with running() as host:
            self.assertEqual(call(host, INVENTORY, auth=None)[0], 401)
            self.assertEqual(call(host, "/wiki/rest/api/content/1")[0], 404)
            self.assertEqual(call(host, f"/wiki/rest/api/content/{server.BOARD_SALARIES}")[0], 200)

    def test_the_reads_are_listed_and_cleared(self) -> None:
        with running() as host:
            call(host, INVENTORY)
            self.assertEqual(call(host, "/_admin/reads")[1], {"reads": [server.INVENTORY]})
            call(host, "/_admin/reads", body={})
            self.assertEqual(call(host, "/_admin/reads")[1], {"reads": []})

    def test_an_outage_answers_503_until_it_is_over(self) -> None:
        with running() as host:
            self.assertEqual(call(host, "/_admin/mode", body={"mode": "unavailable"})[0], 200)
            self.assertEqual(call(host, INVENTORY)[0], 503)
            self.assertEqual(call(host, "/wiki/rest/api/user/current")[0], 503)
            self.assertEqual(call(host, "/_admin/mode", body={"mode": "down"})[0], 400)
            call(host, "/_admin/mode", body={"mode": "ok"})
            self.assertEqual(call(host, INVENTORY)[0], 200)


if __name__ == "__main__":
    unittest.main()
