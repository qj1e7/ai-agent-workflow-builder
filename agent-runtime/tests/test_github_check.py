import importlib.util
import os
import threading
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_runtime.api import Runtime, Settings, create_app
from agent_runtime.contract import GitHubProblem, GitHubWorking
from agent_runtime.github import GitHubConnection
from tests.test_api import make_runtime

MOCK_DIR = Path(
    os.environ.get("MOCK_GITHUB_DIR") or Path(__file__).resolve().parents[2] / "e2e" / "mock_github"
)
KEY = "test-agent-key-not-a-secret"
SETTINGS = Settings.from_env(
    {"AGENT_API_KEY": KEY, "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000"}
)


def load_mock() -> ModuleType:
    path = MOCK_DIR / "server.py"
    if not path.exists():
        pytest.fail(f"{path} is missing. Mount e2e/mock_github and set MOCK_GITHUB_DIR.")
    spec = importlib.util.spec_from_file_location("mock_github_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Mock:
    server: ModuleType
    state: Any
    base: str


@pytest.fixture
def mock() -> Generator[Mock]:
    server = load_mock()
    state = server.State()
    httpd = server.build_server("127.0.0.1", 0, state)
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Mock(server, state, f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_good_token_works_and_has_no_end_date(mock: Mock):
    result = GitHubConnection(mock.base, token=mock.server.GOOD_TOKEN).check()
    assert result == GitHubWorking(using_token=True, expires_at=None)


def test_an_expiring_token_works_and_says_when_it_ends(mock: Mock):
    result = GitHubConnection(mock.base, token=mock.server.EXPIRING_TOKEN).check()
    assert result == GitHubWorking(
        using_token=True, expires_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    )


def test_a_refused_token_is_a_problem_that_does_not_quote_the_token(mock: Mock):
    token = "ghp_a_token_github_does_not_know"
    result = GitHubConnection(mock.base, token=token).check()
    assert isinstance(result, GitHubProblem)
    assert result.reason == "token_refused"
    assert token not in result.message


def test_no_token_is_read_anonymously(mock: Mock):
    assert GitHubConnection(mock.base).check() == GitHubWorking(using_token=False)


def test_github_being_down_is_unreachable_and_recovers(mock: Mock):
    connection = GitHubConnection(mock.base, token=mock.server.GOOD_TOKEN)
    mock.state.mode = "unavailable"
    down = connection.check()
    mock.state.mode = "ok"
    assert isinstance(down, GitHubProblem) and down.reason == "unreachable"
    assert connection.check().status == "working"


@pytest.mark.parametrize(
    ("header", "ends"),
    [
        ("2026-11-14 09:00:00 UTC", datetime(2026, 11, 14, 9, 0, tzinfo=UTC)),
        ("2026-11-14 17:00:00 +0800", datetime(2026, 11, 14, 9, 0, tzinfo=UTC)),
        ("2026-11-14 04:30:00 -0430", datetime(2026, 11, 14, 9, 0, tzinfo=UTC)),
        ("someday", None),
    ],
)
def test_the_expiry_header_may_carry_an_offset_and_is_read_as_utc(
    header: str, ends: datetime | None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={}, headers={"github-authentication-token-expiration": header}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = GitHubConnection("http://github.test", token="t", client=client).check()
    assert result == GitHubWorking(using_token=True, expires_at=ends)


def test_no_answer_at_all_is_unreachable():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    result = GitHubConnection("http://github.test", token="t", client=client).check()
    assert isinstance(result, GitHubProblem) and result.reason == "unreachable"


def test_a_token_never_travels_anywhere_but_the_authorization_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    GitHubConnection("http://github.test", token="ghp_secret_value", client=client).check()
    assert seen[0].url.path == "/rate_limit"
    assert "ghp_secret_value" not in str(seen[0].url)
    assert seen[0].headers["authorization"] == "Bearer ghp_secret_value"


def app_for(connection: GitHubConnection) -> TestClient:
    runtime = make_runtime()
    runtime = Runtime(
        checker=runtime.checker,
        planner=runtime.planner,
        clock=runtime.clock,
        callbacks=runtime.callbacks,
        github=connection,
    )
    return TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})


def test_the_route_answers_the_check_behind_the_agent_key(mock: Mock):
    app = app_for(GitHubConnection(mock.base, token=mock.server.EXPIRING_TOKEN))
    response = app.post("/v1/connections/github/check")
    assert response.status_code == 200
    assert response.json() == {
        "status": "working",
        "using_token": True,
        "expires_at": "2026-11-14T09:00:00Z",
    }
    assert TestClient(app.app).post("/v1/connections/github/check").status_code == 401


def test_the_route_reports_a_refused_token(mock: Mock):
    response = app_for(GitHubConnection(mock.base, token="ghp_unknown")).post(
        "/v1/connections/github/check"
    )
    assert response.json()["status"] == "problem"
    assert response.json()["reason"] == "token_refused"
