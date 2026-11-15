import http.client
import json
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
def running() -> Generator[tuple[str, int, Path]]:
    """The mock on plain HTTP and on TLS, with its certificate authority's directory."""
    state = server.State()
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


if __name__ == "__main__":
    unittest.main()
