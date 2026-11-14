"""Nothing calls a route that ENGINE-PLAN E10 deleted (D20): every internal address an n8n
workflow file calls is one the platform serves, and nothing the platform or its contracts hold
asks for the schedule tick."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

import platform_api
from platform_api.app import create_app
from platform_api.orchestration.workflows import PLATFORM_INTERNAL_URL, load_all
from tests.support import FIXTURES, LOCAL_ENV

TICK = "/internal/v1/schedules/" + "tick"
EXPRESSION = re.compile(r"\{\{.*?\}\}")


def served() -> list[re.Pattern[str]]:
    paths: dict[str, object] = create_app(LOCAL_ENV).openapi()["paths"]
    return [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$") for path in paths]


def test_every_internal_address_a_workflow_file_calls_is_served():
    routes = served()
    called = [
        (definition.name, EXPRESSION.sub("x", node.url).split(PLATFORM_INTERNAL_URL, 1)[1])
        for definition in load_all()
        for node in definition.http_nodes.values()
    ]
    assert called, "the workflow files call the platform"
    for name, path in called:
        assert any(route.match(path) for route in routes), f"{name} calls {path}, served by none"


def searched() -> list[Path]:
    """What the platform-api image holds: its own code, and contracts/, which CI mounts. A root
    that is missing fails the test, so it never passes by finding nothing. The rest of the
    repository is searched from the checkout, in CI's checks (e2e) job."""
    roots = [Path(platform_api.__file__).parent, FIXTURES.parent]
    for root in roots:
        assert root.is_dir(), f"{root} is missing, so nothing would be searched"
    files = [
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    assert len(files) > 100, f"only {len(files)} files under {roots}"
    return files


def test_the_schedule_tick_is_gone_and_nothing_asks_for_it():
    answer = TestClient(create_app(LOCAL_ENV)).post(TICK, headers={"X-Step-Key": "step-key"})
    assert answer.status_code == 404
    callers = [path for path in searched() if TICK in path.read_text(errors="ignore")]
    assert callers == []
