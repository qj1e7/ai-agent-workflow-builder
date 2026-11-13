import base64
import http.client
import json
import threading
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from http.server import ThreadingHTTPServer
from typing import Any

import confluence_server as server

BOT = "Basic " + base64.b64encode(f"{server.EMAIL}:{server.TOKEN}".encode()).decode()
CERT_LIST = f"/wiki/rest/api/content/{server.CERT_LIST}?expand=body.storage,version"


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

    def test_the_cert_list_is_a_page_in_storage_format_with_its_version(self) -> None:
        with running() as host:
            status, page = call(host, CERT_LIST)
            self.assertEqual(status, 200)
            self.assertEqual((page["title"], page["version"]["number"]), ("Cert List", 7))
            storage = page["body"]["storage"]["value"]
            self.assertIn("<th><p><strong>VALIDITY END</strong></p></th>", storage)
            self.assertEqual(storage.count("<tr>"), 8)

    def test_the_dates_follow_today_so_the_split_never_drifts(self) -> None:
        rows = server.cert_rows(date(2026, 12, 28))
        self.assertEqual(rows[0][2], '<time datetime="2027-01-07" />')
        self.assertEqual(rows[1][2], "11 Feb 2027")
        self.assertEqual(rows[2][2], "23/12/2026")
        self.assertEqual([env for env, _, _ in rows].count(""), 1)

    def test_a_page_needs_the_bot_and_an_unknown_page_is_404(self) -> None:
        with running() as host:
            self.assertEqual(call(host, CERT_LIST, auth=None)[0], 401)
            self.assertEqual(call(host, "/wiki/rest/api/content/1")[0], 404)
            self.assertEqual(call(host, f"/wiki/rest/api/content/{server.BOARD_SALARIES}")[0], 200)

    def test_the_reads_are_listed_and_cleared(self) -> None:
        with running() as host:
            call(host, CERT_LIST)
            self.assertEqual(call(host, "/_admin/reads")[1], {"reads": [server.CERT_LIST]})
            call(host, "/_admin/reads", body={})
            self.assertEqual(call(host, "/_admin/reads")[1], {"reads": []})

    def test_an_outage_answers_503_until_it_is_over(self) -> None:
        with running() as host:
            self.assertEqual(call(host, "/_admin/mode", body={"mode": "unavailable"})[0], 200)
            self.assertEqual(call(host, CERT_LIST)[0], 503)
            self.assertEqual(call(host, "/wiki/rest/api/user/current")[0], 503)
            self.assertEqual(call(host, "/_admin/mode", body={"mode": "down"})[0], 400)
            call(host, "/_admin/mode", body={"mode": "ok"})
            self.assertEqual(call(host, CERT_LIST)[0], 200)


if __name__ == "__main__":
    unittest.main()
