import os
import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app, readiness_of
from platform_api.bootstrap import record_status
from platform_api.db import Database
from platform_api.orchestration.approvals import Refusal
from platform_api.orchestration.service import DecisionRefused, RetryLater
from tests.conftest import PostgresUrls
from tests.support import LOCAL_ENV as LOCAL

ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/healthz/ready"),
    ("GET", "/api/v1/dev/users"),
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/home"),
    ("GET", "/api/v1/templates"),
    ("POST", "/api/v1/use-cases"),
    ("GET", "/api/v1/use-cases"),
    ("POST", "/api/v1/use-cases/suggest"),
    ("GET", "/api/v1/use-cases/{use_case_id}"),
    ("POST", "/api/v1/use-cases/{use_case_id}/runs"),
    ("POST", "/api/v1/use-cases/{use_case_id}/pause"),
    ("POST", "/api/v1/use-cases/{use_case_id}/resume"),
    ("PUT", "/api/v1/use-cases/{use_case_id}/schedule"),
    ("DELETE", "/api/v1/use-cases/{use_case_id}"),
    ("POST", "/api/v1/use-cases/{use_case_id}/restore"),
    ("PUT", "/api/v1/drafts/{draft_id}"),
    ("GET", "/api/v1/drafts"),
    ("DELETE", "/api/v1/drafts/{draft_id}"),
    ("GET", "/api/v1/tools"),
    ("GET", "/api/v1/agent-cards"),
    ("POST", "/api/v1/agent-cards"),
    ("POST", "/api/v1/agent-cards/check"),
    ("GET", "/api/v1/agent-cards/{card_id}"),
    ("PUT", "/api/v1/agent-cards/{card_id}"),
    ("POST", "/api/v1/builder/plan"),
    ("POST", "/api/v1/builder/understand"),
    ("POST", "/api/v1/agent-use-cases"),
    ("GET", "/api/v1/watchlist"),
    ("POST", "/api/v1/watchlist/software"),
    ("PUT", "/api/v1/watchlist/schedule"),
    ("DELETE", "/api/v1/watchlist/schedule"),
    ("DELETE", "/api/v1/watchlist/software/{software_id}"),
    ("POST", "/api/v1/watchlist/software/{software_id}/restore"),
    ("GET", "/api/v1/runs"),
    ("GET", "/api/v1/runs/{run_id}"),
    ("POST", "/api/v1/runs/{run_id}/retry"),
    ("GET", "/api/v1/runs/{run_id}/events"),
    ("GET", "/api/v1/runs/{run_id}/troubleshoot"),
    ("GET", "/api/v1/approvals/{approval_id}"),
    ("POST", "/api/v1/approvals/{approval_id}/decisions"),
    ("GET", "/api/v1/teams-stub/messages"),
    ("GET", "/api/v1/mock-jira/tickets"),
    ("POST", "/api/v1/mock-jira/tickets/{key}/done"),
    ("POST", "/internal/v1/runs/{run_id}/steps/{step}"),
    ("POST", "/internal/v1/runs/{run_id}/agent-events"),
    ("GET", "/internal/v1/runs/{run_id}/jira/tickets"),
    ("GET", "/internal/v1/runs/{run_id}/jira/tickets/{key}"),
    ("POST", "/internal/v1/schedules/tick"),
    ("POST", "/internal/v1/workflow-failures"),
    ("GET", "/api/v1/settings/model"),
    ("PUT", "/api/v1/settings/model"),
    ("DELETE", "/api/v1/settings/model"),
    ("POST", "/api/v1/settings/model/connect"),
    ("POST", "/api/v1/settings/model/address-decision"),
    ("GET", "/api/v1/settings/history"),
    ("GET", "/api/v1/people"),
    ("POST", "/api/v1/people"),
    ("PUT", "/api/v1/people/{person_id}/operator"),
    ("POST", "/api/v1/people/{person_id}/approver"),
    ("DELETE", "/api/v1/people/{person_id}/approver"),
    ("DELETE", "/api/v1/people/{person_id}"),
    ("GET", "/api/v1/confirmations"),
    ("POST", "/api/v1/confirmations/{confirmation_id}/decisions"),
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(LOCAL))


def test_openapi_lists_every_route(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    listed = {(method.upper(), path) for path, ops in paths.items() for method in ops}
    assert listed == ROUTES


def test_with_practice_systems_off_no_practice_jira_route_is_served():
    client = TestClient(create_app({**LOCAL, "PRACTICE_SYSTEMS": "off"}))
    paths = client.get("/openapi.json").json()["paths"]
    assert [path for path in paths if "mock-jira" in path] == []
    assert "/api/v1/teams-stub/messages" in paths
    alice = {"X-Dev-User": "alice"}
    assert client.get("/api/v1/mock-jira/tickets", headers=alice).status_code == 404
    assert client.post("/api/v1/mock-jira/tickets/MOCK-1/done", headers=alice).status_code == 404


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/healthz", {}, 200),
        ("/api/v1/dev/users", {}, 200),
        ("/api/v1/runs", {}, 401),
        ("/no/such/route", {}, 404),
        ("/openapi.json", {}, 200),
    ],
)
def test_every_response_forbids_content_sniffing(
    client: TestClient, path: str, headers: dict[str, str], status: int
):
    response = client.get(path, headers=headers)
    assert response.status_code == status
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_trailing_slash_is_not_found_and_never_redirects(client: TestClient):
    response = client.get("/api/v1/runs/", headers={"X-Dev-User": "alice"}, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers


def test_healthz(client: TestClient):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_events_route_documents_both_content_types(client: TestClient):
    op = client.get("/openapi.json").json()["paths"]["/api/v1/runs/{run_id}/events"]["get"]
    assert set(op["responses"]["200"]["content"]) == {"application/json", "text/event-stream"}
    assert {p["name"] for p in op["parameters"]} >= {"after", "Last-Event-ID"}


def test_step_route_refuses_a_bad_step_name():
    app = create_app(LOCAL)
    app.state.orchestrator = None
    client = TestClient(app)
    r = client.post(
        "/internal/v1/runs/run_01JD1Z7K9Q3M5N8P2R4T6V8W0X/steps/delete_everything",
        headers={"X-Step-Key": LOCAL["STEP_KEY"], "X-N8N-Execution": "1"},
    )
    assert r.status_code == 422


@pytest.mark.anyio
async def test_readiness_names_a_copier_that_is_not_listening(db: Database):
    readiness = await readiness_of(db, True, copying=False)
    assert [(c.name, c.ok) for c in readiness.checks][:2] == [
        ("activity_log", True),
        ("activity_copy", False),
    ]
    assert readiness.ready is False


@pytest.mark.anyio
async def test_readiness_says_the_copy_is_behind_and_stays_ready(
    db: Database, postgres: PostgresUrls
):
    record_status(postgres.owner, ready=True, detail="all workflows loaded", workflows=[])

    readiness = await readiness_of(db, True, copying=True, copy_behind=True)

    copy = readiness.checks[1]
    assert (copy.name, copy.ok, readiness.ready) == ("activity_copy", True, True)
    assert copy.detail == (
        "listening for events to copy to Cosmos DB, but the copy is behind and retrying"
    )


@pytest.mark.anyio
async def test_readiness_is_not_ready_before_bootstrap(db: Database):
    readiness = await readiness_of(db, True)
    assert readiness.ready is False
    assert [(c.name, c.ok) for c in readiness.checks] == [
        ("activity_log", True),
        ("workflows", False),
    ]


class RefusingOrchestrator:
    async def decide(self, *args: object) -> DecisionRefused:
        return DecisionRefused(Refusal.OWN_WORK)

    async def on_step(self, *args: object) -> None:
        raise RetryLater("n8n is still starting")


@pytest.fixture
def refusing_client() -> TestClient:
    app = create_app(LOCAL)
    app.state.orchestrator = RefusingOrchestrator()
    return TestClient(app)


def test_a_refused_decision_answers_the_documented_refusal_body(refusing_client: TestClient):
    r = refusing_client.post(
        "/api/v1/approvals/apr_1/decisions",
        headers={"X-Dev-User": "alice"},
        json={"step": 0, "verdict": "approve", "digest": "sha256:" + "0" * 64},
    )
    assert r.status_code == 403
    assert r.json() == {
        "refusal": "own_work",
        "message": "This run is your own work, so another Approver must decide.",
    }


# The shape new_id("run") makes: run_ and 26 characters of Crockford's base 32.
A_RUN_ID = "run_01JD1Z7K9Q3M5N8P2R4T6V8W0X"


def test_a_step_told_to_retry_answers_the_documented_retry_body(refusing_client: TestClient):
    r = refusing_client.post(
        f"/internal/v1/runs/{A_RUN_ID}/steps/run_agents",
        headers={"X-Step-Key": LOCAL["STEP_KEY"], "X-N8N-Execution": "1"},
    )
    assert r.status_code == 503
    assert r.json() == {"detail": "n8n is still starting", "retryable": True}


@pytest.mark.parametrize(
    "run_id",
    [
        "run_1",
        A_RUN_ID[:-1],
        A_RUN_ID + "X",
        A_RUN_ID.lower(),
        A_RUN_ID[:-1] + "O",
        "apr_" + A_RUN_ID.removeprefix("run_"),
        "run_01JD1Z7K9Q3M5N8P2R4T6V8W0X#",
    ],
)
def test_step_route_refuses_a_run_id_that_is_not_one(refusing_client: TestClient, run_id: str):
    """n8n's run workflow takes run_id from a webhook that anyone may call while the editor is
    open (ADR 0034). The step key is real, so the route checks the id's shape before the
    orchestrator sees it. The refusing orchestrator would answer 503."""
    r = refusing_client.post(
        f"/internal/v1/runs/{run_id.replace('#', '%23')}/steps/run_agents",
        headers={"X-Step-Key": LOCAL["STEP_KEY"], "X-N8N-Execution": "1"},
    )
    assert r.status_code == 422
    assert r.json() == {"detail": "Not a run id"}


def test_a_bad_step_key_is_refused_before_the_run_id_is_looked_at(refusing_client: TestClient):
    r = refusing_client.post(
        "/internal/v1/runs/run_1/steps/run_agents",
        headers={"X-Step-Key": "wrong", "X-N8N-Execution": "1"},
    )
    assert r.status_code == 401


# The image's command, `uvicorn platform_api.app:create_app --factory`: uvicorn sets up its own
# loggers, then builds the app. The script then ticks a held schedule and a paused one.
UNDER_UVICORN = """
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import uvicorn

from platform_api.app import create_app
from platform_api.orchestration import NotOn, SavedSchedule, Schedule, ScheduleTicker
from platform_api.shared import Role, UseCaseId, UserId

uvicorn.Config("platform_api.app:create_app", factory=True).load()
create_app()

NOW = datetime(2026, 11, 9, 1, 1, tzinfo=UTC)


def saved(use_case, owner, roles):
    return SavedSchedule(
        UseCaseId(use_case), Schedule("monday", "09:00"), UserId(owner), owner.title(),
        NOW - timedelta(days=1), None, roles,
    )


class Book:
    async def all(self):
        return [saved("uc_held", "carol", None), saved("uc_paused", "alice", {Role.OPERATOR})]

    async def use_up_slot(self, use_case_id, slot):
        pass


class Specs:
    async def check_spec(self, use_case_id):
        return NotOn("paused")


class Conn:
    async def execute(self, *args):
        pass


class Clock:
    def clock(self):
        return NOW

    @asynccontextmanager
    async def transaction(self, context):
        # The tick holds the workflow's lock around a start (#56).
        yield SimpleNamespace(conn=Conn())


asyncio.run(ScheduleTicker(Clock(), Book(), Specs(), None).tick())
logging.getLogger("uvicorn.error").info("uvicorn's own line")
logging.getLogger("uvicorn.access").info(
    '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "POST", "/internal/v1/schedules/tick", "1.1", 200
)
"""
STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} "
# CI points COSMOS_ENDPOINT at the emulator for the Cosmos DB tests, with no COSMOS_KEY.
WITHOUT_COSMOS = {name: v for name, v in os.environ.items() if not name.startswith("COSMOS_")}


def test_the_app_under_uvicorn_logs_each_skipped_scheduled_check_once():
    done = subprocess.run(
        [sys.executable, "-c", UNDER_UVICORN],
        env={**WITHOUT_COSMOS, **LOCAL},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr

    errors = done.stderr.splitlines()
    skips = [re.sub(f"^{STAMP}", "", line) for line in errors if "skipped" in line]
    logger = "platform_api.orchestration.schedule_store"
    assert skips == [
        f"INFO {logger}: skipped the scheduled check of uc_held, because its owner carol has "
        "left the People list",
        f"INFO {logger}: skipped the scheduled check of uc_paused, which is paused",
    ]
    assert errors.count("INFO:     uvicorn's own line") == 1
    access = 'INFO:     127.0.0.1:5000 - "POST /internal/v1/schedules/tick HTTP/1.1" 200 OK'
    assert done.stdout.splitlines().count(access) == 1
    assert access not in done.stderr
