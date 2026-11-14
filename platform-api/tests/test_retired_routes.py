"""Nothing calls a route that ENGINE-PLAN E10 deleted (D20): every internal address an n8n
workflow file calls is one the platform serves, and no code, script or stack file asks for the
schedule tick. Only the design records under docs/ still name it."""

import re
import subprocess

from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.orchestration.workflows import PLATFORM_INTERNAL_URL, load_all
from tests.support import LOCAL_ENV, REPO

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


def test_the_schedule_tick_is_gone_and_nothing_asks_for_it():
    answer = TestClient(create_app(LOCAL_ENV)).post(TICK, headers={"X-Step-Key": "step-key"})
    assert answer.status_code == 404
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    callers = [
        path
        for path in listed
        if not path.startswith("docs/")
        and (REPO / path).is_file()
        and TICK in (REPO / path).read_text(errors="ignore")
    ]
    assert callers == []
