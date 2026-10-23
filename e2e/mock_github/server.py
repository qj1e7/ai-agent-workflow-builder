import json
import re
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO = "langchain-ai/langgraph"
MODES = ("ok", "unavailable")
DEFAULT_PER_PAGE = 30
MAX_PER_PAGE = 100

PLAIN_TAGS = [
    "1.2.16", "1.2.15", "1.2.14", "1.2.13", "1.2.12", "1.2.11", "1.2.10", "1.2.9",
    "1.2.8", "1.2.7", "1.2.6", "1.2.5", "1.2.4", "1.2.3", "1.2.2", "1.2.1", "1.2.0",
    "1.1.9", "1.1.8", "1.1.7", "1.1.6", "1.1.5",
]  # fmt: skip
OTHER_FAMILY_TAGS = {
    3: "cli==0.4.37",
    5: "prebuilt==1.0.5",
    7: "sdk==0.2.4",
    10: "checkpoint==3.0.1",
    13: "cli==0.4.36",
    16: "prebuilt==1.0.4",
    19: "sdk==0.2.3",
    22: "cli==0.4.35",
}
LATEST_PUBLISHED = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


def release_order() -> list[str]:
    plain = iter(PLAIN_TAGS)
    tags: list[str] = []
    while len(tags) < len(PLAIN_TAGS) + len(OTHER_FAMILY_TAGS):
        tags.append(OTHER_FAMILY_TAGS.get(len(tags)) or next(plain))
    return tags


def build_releases() -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    total = len(release_order())
    for index, tag in enumerate(release_order()):
        number = total - index
        published = LATEST_PUBLISHED - timedelta(hours=31 * index)
        stamp = published.strftime("%Y-%m-%dT%H:%M:%SZ")
        base = f"https://api.github.com/repos/{REPO}"
        releases.append(
            {
                "url": f"{base}/releases/{number}",
                "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
                "assets_url": f"{base}/releases/{number}/assets",
                "upload_url": f"https://uploads.github.com/repos/{REPO}/releases/{number}/assets",
                "tarball_url": f"{base}/tarball/{tag}",
                "zipball_url": f"{base}/zipball/{tag}",
                "id": 900_000 + number,
                "node_id": f"RE_mock{number:04d}",
                "tag_name": tag,
                "target_commitish": "main",
                "name": tag,
                "body": f"Release notes for {tag}.",
                "draft": False,
                "prerelease": False,
                "created_at": stamp,
                "published_at": stamp,
                "author": {"login": "github-actions[bot]", "id": 41898282, "type": "Bot"},
                "assets": [],
            }
        )
    return releases


RELEASES = build_releases()
RELEASES_PATH = re.compile(rf"^/repos/{re.escape(REPO)}/releases/?$")


class State:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = "ok"

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        with self._lock:
            self._mode = value


def page_of(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    per_page = min(int(query.get("per_page", [DEFAULT_PER_PAGE])[0]), MAX_PER_PAGE)
    page = max(int(query.get("page", [1])[0]), 1)
    start = (page - 1) * per_page
    return RELEASES[start : start + per_page]


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, body: Any) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/healthz":
                self.send_json(200, {"status": "ok"})
            elif url.path == "/_admin/mode":
                self.send_json(200, {"mode": state.mode})
            elif RELEASES_PATH.match(url.path):
                if state.mode == "unavailable":
                    self.send_json(503, {"message": "Service Unavailable"})
                    return
                try:
                    releases = page_of(parse_qs(url.query))
                except ValueError:
                    self.send_json(422, {"message": "Validation Failed"})
                    return
                self.send_json(200, releases)
            else:
                self.send_json(404, {"message": "Not Found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/_admin/mode":
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
    build_server("0.0.0.0", 8200, State()).serve_forever()
