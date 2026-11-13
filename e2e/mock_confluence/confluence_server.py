"""A tiny stand-in for Confluence's REST API, for the end to end tests.

It holds two pages. Software inventory (424242) is a plain table in Confluence's storage format,
with a paragraph in each cell as Confluence writes it. Board salaries (434343) is a page Confluence
has and the platform may not read.

It takes the platform's bot as Atlassian Cloud does, by email and API token. Anyone else is the
anonymous user, or refused with 401 on a page. GET /_admin/reads lists the pages read, and POST
/_admin/mode with {"mode": "unavailable"} makes every wiki call answer 503, {"mode": "ok"}
restores it.
"""

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

EMAIL = "bot@codesparks.test"
TOKEN = "mock-confluence-token"
INVENTORY = "424242"
BOARD_SALARIES = "434343"
MODES = ("ok", "unavailable")
CONTENT_PATH = re.compile(r"^/wiki/rest/api/content/([^/]+)$")
SOFTWARE = (("LangGraph", "1.2.14"), ("Redis", "8.0.2"), ("FastAPI", "0.115.4"))


def inventory_storage() -> str:
    heads = "".join(f"<th><p><strong>{name}</strong></p></th>" for name in ("Software", "Ours"))
    rows = "".join(
        f"<tr><td><p>{name}</p></td><td><p>{ours}</p></td></tr>" for name, ours in SOFTWARE
    )
    return (
        "<p>The software we run, and our versions.</p>"
        '<table data-layout="default"><colgroup><col /><col /></colgroup>'
        f"<tbody><tr>{heads}</tr>{rows}</tbody></table>"
    )


def page_body(page_id: str, title: str, version: int, storage: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "type": "page",
        "status": "current",
        "title": title,
        "version": {"number": version},
        "body": {"storage": {"value": storage, "representation": "storage"}},
        "_links": {"base": "http://mock-confluence:8400/wiki", "webui": f"/pages/{page_id}"},
    }


def pages() -> dict[str, dict[str, Any]]:
    return {
        INVENTORY: page_body(INVENTORY, "Software inventory", 7, inventory_storage()),
        BOARD_SALARIES: page_body(BOARD_SALARIES, "Board salaries", 2, "<p>Private.</p>"),
    }


def signed_in(header: str | None) -> bool | None:
    """True for the platform's bot, False for a sign-in Confluence refuses, None for nobody."""
    if header is None:
        return None
    wanted = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    return header == f"Basic {wanted}"


class State:
    def __init__(self) -> None:
        self.mode = "ok"
        self.reads: list[str] = []
        self.lock = threading.Lock()


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, body: Any) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/healthz":
                self.send_json(200, {"status": "ok"})
                return
            if path == "/_admin/mode":
                self.send_json(200, {"mode": state.mode})
                return
            if path == "/_admin/reads":
                with state.lock:
                    self.send_json(200, {"reads": list(state.reads)})
                return
            if not path.startswith("/wiki/rest/api/"):
                self.send_json(404, {"message": "Not Found"})
                return
            if state.mode == "unavailable":
                self.send_json(503, {"message": "Service Unavailable"})
                return
            who = signed_in(self.headers.get("Authorization"))
            if path == "/wiki/rest/api/user/current":
                if who is False:
                    self.send_json(401, {"message": "Basic authentication failed"})
                elif who:
                    self.send_json(200, {"type": "known", "accountId": "mock-bot"})
                else:
                    self.send_json(200, {"type": "anonymous"})
                return
            found = CONTENT_PATH.match(path)
            if found is None:
                self.send_json(404, {"message": "Not Found"})
                return
            if not who:
                self.send_json(401, {"message": "Unauthorized"})
                return
            with state.lock:
                state.reads.append(found.group(1))
            page = pages().get(found.group(1))
            if page is None:
                self.send_json(404, {"message": "No content found with id"})
            else:
                self.send_json(200, page)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/_admin/reads":
                with state.lock:
                    state.reads.clear()
                self.send_json(200, {"reads": []})
                return
            if path != "/_admin/mode":
                self.send_json(404, {"message": "Not Found"})
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                mode = json.loads(self.rfile.read(length)).get("mode")
            except ValueError, AttributeError:
                mode = None
            if mode not in MODES:
                self.send_json(400, {"message": f"mode must be one of {list(MODES)}"})
                return
            state.mode = mode
            self.send_json(200, {"mode": mode})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def build_server(host: str, port: int, state: State) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(state))


if __name__ == "__main__":
    build_server("0.0.0.0", 8400, State()).serve_forever()
