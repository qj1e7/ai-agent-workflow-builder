import http.client
import json
import secrets
import ssl
import tempfile
import threading
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import server


@contextmanager
def running(state: server.State | None = None) -> Generator[tuple[str, int, Path]]:
    """The mock on plain HTTP and on TLS, with its certificate authority's directory."""
    state = state or server.State()
    with tempfile.TemporaryDirectory() as tmp:
        ca_dir, keys_dir = Path(tmp) / "ca", Path(tmp) / "keys"
        cert, key = server.certificates(ca_dir, keys_dir)
        plain = server.build_server("127.0.0.1", 0, state)
        tls = server.serve_tls(state, 0, cert, key)
        for httpd in (plain, tls):
            threading.Thread(
                target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
            ).start()
        try:
            yield f"127.0.0.1:{plain.server_address[1]}", tls.server_address[1], ca_dir
        finally:
            for httpd in (plain, tls):
                httpd.shutdown()
                httpd.server_close()


def call(
    host: str, method: str, path: str, token: str | None, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, str], Any]:
    connection = http.client.HTTPConnection(host, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(
        method, path, body=None if body is None else json.dumps(body), headers=headers
    )
    response = connection.getresponse()
    return (
        response.status,
        {k.lower(): v for k, v in response.getheaders()},
        json.loads(response.read()),
    )


class MockSlack(unittest.TestCase):
    def test_the_stack_s_key_posts_and_says_its_scopes(self) -> None:
        with running() as (host, _, _):
            _, headers, body = call(host, "POST", "/api/auth.test", server.TOKEN)
            self.assertTrue(body["ok"])
            self.assertEqual(headers["x-oauth-scopes"], server.SCOPES)
            _, _, refused = call(host, "POST", "/api/auth.test", "someone-else")
            self.assertEqual(refused, {"ok": False, "error": "invalid_auth"})

    def test_the_stack_s_key_lists_its_channels(self) -> None:
        with running() as (host, _, _):
            path = "/api/conversations.list?types=public_channel"
            _, _, listed = call(host, "GET", path, server.TOKEN)
            self.assertEqual(
                [(c["name"], c["is_member"]) for c in listed["channels"]],
                [("support", True), ("eng-housekeeping", True), ("random", False)],
            )
            private = "/api/conversations.list?types=public_channel,private_channel"
            _, _, refused = call(host, "GET", private, server.TOKEN)
            self.assertEqual(refused["error"], "missing_scope", "the key has no groups:read")

    def test_every_message_is_recorded_with_the_key_it_came_with(self) -> None:
        with running() as (host, _, _):
            call(
                host, "POST", "/api/chat.postMessage", server.TOKEN, {"channel": "C1", "text": "hi"}
            )
            call(host, "POST", "/api/chat.delete", "hers", {"channel": "C1", "ts": "1"})
            _, _, sent = call(host, "GET", "/_sent", None)
            self.assertEqual(
                [(m["method"], m["token"], m["channel"]) for m in sent["sent"]],
                [("chat.postMessage", server.TOKEN, "C1"), ("chat.delete", "hers", "C1")],
            )

    def test_it_answers_as_slack_com_over_tls_to_a_client_that_trusts_its_authority(self) -> None:
        with running() as (_, port, ca_dir):
            context = ssl.create_default_context(cafile=str(ca_dir / "ca.pem"))
            connection = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
            context.check_hostname = False
            connection.request(
                "GET", "/api/users.profile.get", headers={"Authorization": f"Bearer {server.TOKEN}"}
            )
            self.assertTrue(json.loads(connection.getresponse().read())["ok"])

    def test_a_key_made_up_at_the_start_takes_the_place_of_the_test_key(self) -> None:
        """The simulation n8n's stack makes up mock Slack's key at each start (ADR 0054)."""
        made_up = secrets.token_hex(16)
        with running(server.State(made_up)) as (host, _, _):
            _, _, body = call(host, "POST", "/api/auth.test", made_up)
            self.assertTrue(body["ok"])
            _, _, refused = call(host, "POST", "/api/auth.test", server.TOKEN)
            self.assertEqual(refused, {"ok": False, "error": "invalid_auth"})


if __name__ == "__main__":
    unittest.main()
