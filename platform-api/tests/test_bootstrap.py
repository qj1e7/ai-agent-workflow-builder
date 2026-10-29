import json
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from psycopg import sql
from pydantic import TypeAdapter

from platform_api import bootstrap
from platform_api.bootstrap import (
    OLD_RUN_WORKFLOW,
    OLD_TASK_KIND,
    OLD_TEMPLATE,
    RESET_HINT,
    load_into_n8n,
    main,
    unreadable_data,
)
from platform_api.db import PLATFORM_DATABASE, ROLE_OWNER
from platform_api.migrations import MIGRATION_ORDER, downgrade, upgrade_all
from platform_api.orchestration.n8n import N8nClient
from platform_api.orchestration.spec import RunSpec
from platform_api.orchestration.workflows import load_all
from platform_api.settings import BootstrapSettings
from tests.conftest import PostgresUrls, truncate_all
from tests.support import NOW, SPEC

N8N = "http://n8n.test"
TRUNK_HEADS = {"monitoring": "0001", "orchestration": "0004", "builder": "0003"}
READY = (True, "all workflows loaded, active and linted")


def env_for(owner_url: str) -> dict[str, str]:
    return {
        "DATABASE_URL_OWNER": owner_url,
        "N8N_BASE_URL": N8N,
        "N8N_OWNER_EMAIL": "owner@example.com",
        "N8N_OWNER_PASSWORD": "Aa1secret",
        "STEP_KEY": "step-key",
        "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
    }


def engine_status(owner_url: str) -> tuple[bool, str]:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT ready, detail FROM orchestration.engine_status").fetchone()
    assert row is not None
    return bool(row[0]), str(row[1])


def migration_heads(owner_url: str) -> dict[str, str]:
    heads: dict[str, str] = {}
    with psycopg.connect(owner_url) as conn:
        for schema in MIGRATION_ORDER:
            query = sql.SQL("SELECT version_num FROM {}.alembic_version").format(
                sql.Identifier(schema)
            )
            row = conn.execute(query).fetchone()
            assert row is not None
            heads[schema] = str(row[0])
    return heads


def insert_run(owner_url: str, run_id: str, spec: dict[str, Any]) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, "
            "started_by, started_at, updated_at, version, state, state_data, deadline_at, "
            "retried_by, carry_forward) VALUES (%s, %s, %s, %s, 'alice', %s, %s, 1, "
            "'Succeeded', %s, NULL, '[]', NULL)",
            (
                run_id,
                spec["use_case_id"],
                f"key-{run_id}",
                json.dumps(spec),
                NOW,
                NOW,
                json.dumps({"run_id": run_id, "outcome": "nothing_to_write", "written": []}),
            ),
        )


def insert_use_case(owner_url: str, use_case_id: str, template: str) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version) "
            "VALUES (%s, 'alice', %s, 1)",
            (use_case_id, NOW),
        )
        conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at) VALUES (%s, 1, %s, 'n', 'i', '{}', %s)",
            (use_case_id, template, NOW),
        )


def insert_old_run(owner_url: str) -> None:
    spec = {
        "use_case_id": "uc_old",
        "use_case_version": 1,
        "use_case_name": "LangGraph releases",
        "owner": "alice",
        "workflow": OLD_RUN_WORKFLOW,
        "instruction": "Check langchain-ai/langgraph for new releases.",
        "task": {
            "kind": OLD_TASK_KIND,
            "repo": "langchain-ai/langgraph",
            "tag_pattern": r"^\d+\.\d+\.\d+$",
            "last_known_tag": "1.2.14",
        },
        "bindings": {},
        "approval_policy": {"steps": [{"label": "Team approver", "eligible": {}}]},
    }
    insert_run(owner_url, "run_old", spec)


def insert_old_use_case(owner_url: str) -> None:
    insert_use_case(owner_url, "uc_old", OLD_TEMPLATE)


@pytest.fixture
def at_trunk_heads(postgres: PostgresUrls) -> Iterator[None]:
    truncate_all(postgres.owner)
    downgrade("orchestration", postgres.owner, TRUNK_HEADS["orchestration"])
    downgrade("builder", postgres.owner, TRUNK_HEADS["builder"])
    try:
        yield
    finally:
        truncate_all(postgres.owner)
        upgrade_all(postgres.owner)


@pytest.mark.parametrize(
    ("plant", "named"),
    [
        (insert_old_run, "orchestration.runs holds 1 run(s) of the old release check"),
        (
            insert_old_use_case,
            f"builder.use_case_versions holds 1 version(s) of the old {OLD_TEMPLATE} template",
        ),
    ],
    ids=["run", "use case"],
)
@pytest.mark.usefixtures("at_trunk_heads")
def test_old_release_data_stops_bootstrap_before_any_migration_or_n8n_and_deletes_nothing(
    postgres: PostgresUrls, capsys: pytest.CaptureFixture[str], plant: Any, named: str
):
    plant(postgres.owner)
    assert main(env_for(postgres.owner)) == 1
    assert migration_heads(postgres.owner) == TRUNK_HEADS
    said = capsys.readouterr().out
    assert named in said and RESET_HINT in said
    assert "migrations" not in said
    assert "n8n" not in said.replace("n8n.test", "")
    assert engine_status(postgres.owner) == (False, "the database holds old release-check data")
    with psycopg.connect(postgres.owner) as conn:
        runs = conn.execute("SELECT count(*) FROM orchestration.runs").fetchone()
        versions = conn.execute("SELECT count(*) FROM builder.use_case_versions").fetchone()
    assert runs is not None and versions is not None
    assert runs[0] + versions[0] == 1


class FakeN8n:
    def __init__(self, existing: list[str]) -> None:
        self.workflows: dict[str, dict[str, Any]] = {
            f"W{n}": {"id": f"W{n}", "name": name, "active": True, "nodes": [], "settings": {}}
            for n, name in enumerate(existing, start=1)
        }
        self.deleted: list[str] = []
        self.unpublishing: set[str] = set()
        self.calls: list[str] = []
        self.scopes: list[str] = []
        self.next_id = len(existing) + 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else None
        if path == "/healthz/readiness":
            return httpx.Response(200, json={"status": "ok"})
        if path in ("/rest/owner/setup", "/rest/login"):
            return httpx.Response(200, json={"data": {"id": "1"}})
        if path == "/rest/api-keys" and method == "GET":
            return httpx.Response(200, json={"data": {"items": []}})
        if path == "/rest/api-keys" and method == "POST":
            self.scopes = list(body["scopes"])
            return httpx.Response(200, json={"data": {"rawApiKey": "key"}})
        if path == "/api/v1/credentials" and method == "POST":
            return httpx.Response(200, json={"id": "cred1"})
        if path == "/api/v1/credentials" and method == "GET":
            return httpx.Response(200, json={"data": [{"id": "cred1", "name": "X-Step-Key"}]})
        if path == "/api/v1/workflows" and method == "GET":
            wanted = request.url.params.get("name")
            listed = [w for w in self.workflows.values() if wanted in (None, w["name"])]
            return httpx.Response(200, json={"data": listed})
        if path == "/api/v1/workflows" and method == "POST":
            workflow_id = f"W{self.next_id}"
            self.next_id += 1
            self.workflows[workflow_id] = {**body, "id": workflow_id, "active": False}
            return httpx.Response(200, json=self.workflows[workflow_id])
        if path.startswith("/api/v1/workflows/"):
            workflow_id = path.split("/")[4]
            self.calls.append(f"{method} {path.removeprefix('/api/v1/workflows/')}")
            if path.endswith("/activate"):
                self.workflows[workflow_id]["active"] = True
            elif path.endswith("/deactivate"):
                if self.workflows[workflow_id]["active"]:
                    self.workflows[workflow_id]["active"] = False
                    self.unpublishing.add(workflow_id)
            elif method == "PUT":
                self.workflows[workflow_id].update(body)
            elif method == "DELETE":
                if self.workflows[workflow_id]["active"]:
                    return httpx.Response(
                        409,
                        json={
                            "message": "Cannot delete a published workflow. "
                            "Unpublish it before deleting."
                        },
                    )
                if workflow_id in self.unpublishing:
                    self.unpublishing.discard(workflow_id)
                    return httpx.Response(
                        409,
                        json={
                            "message": "Workflow is still being unpublished. "
                            "Please try again in a few moments."
                        },
                    )
                self.deleted.append(workflow_id)
                del self.workflows[workflow_id]
            return httpx.Response(200, json=self.workflows.get(workflow_id, {}))
        return httpx.Response(404, json={"message": f"no fake for {method} {path}"})


def serve(monkeypatch: pytest.MonkeyPatch, n8n: FakeN8n) -> FakeN8n:
    monkeypatch.setattr(
        bootstrap,
        "N8nClient",
        lambda base_url: N8nClient(
            base_url, transport=httpx.MockTransport(n8n.handle), sleep=lambda _: None
        ),
    )
    return n8n


def test_watchlist_runs_and_card_use_cases_pass_the_check(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n([]))
    insert_run(postgres.owner, "run_watch", TypeAdapter(RunSpec).dump_python(SPEC, mode="json"))
    insert_use_case(postgres.owner, "uc_watch", "software_watchlist")
    insert_use_case(postgres.owner, "uc_cards", "agent_cards")

    assert unreadable_data(postgres.owner) == []
    assert main(env_for(postgres.owner)) == 0
    assert engine_status(postgres.owner) == READY


def test_a_fresh_database_passes_the_check_and_is_migrated(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    serve(monkeypatch, FakeN8n([]))
    fresh = f"{PLATFORM_DATABASE}_fresh"
    fresh_url = postgres.owner.rsplit("/", 1)[0] + f"/{fresh}"
    with psycopg.connect(postgres.superuser, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(fresh)))
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(fresh), sql.Identifier(ROLE_OWNER)
            )
        )
    try:
        assert unreadable_data(fresh_url) == []
        assert main(env_for(fresh_url)) == 0
        assert migration_heads(fresh_url) == migration_heads(postgres.owner)
        assert engine_status(fresh_url) == READY
    finally:
        with psycopg.connect(postgres.superuser, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(fresh))
            )


def test_bootstrap_removes_the_old_run_workflow_by_its_exact_name_and_nothing_else(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(
        monkeypatch, FakeN8n([OLD_RUN_WORKFLOW, "Staff access review", f"{OLD_RUN_WORKFLOW} copy"])
    )
    settings = BootstrapSettings(
        owner_database_url=postgres.owner,
        n8n_base_url=N8N,
        n8n_owner_email="owner@example.com",
        n8n_owner_password="Aa1secret",
        step_key="step-key",
        platform_internal_url="http://platform-api:8000",
    )
    said: list[str] = []

    loaded, findings = load_into_n8n(settings, load_all(), said.append)

    assert findings == []
    assert sorted(w.name for w in loaded) == ["run", "run_failure_reporter", "schedule_tick"]
    assert all(w.active for w in loaded)
    assert n8n.deleted == ["W1"]
    assert [c for c in n8n.calls if c.split()[1].split("/")[0] == "W1"] == [
        "POST W1/deactivate",
        "DELETE W1",
        "DELETE W1",
    ]
    assert sorted(w["name"] for w in n8n.workflows.values()) == [
        "Staff access review",
        f"{OLD_RUN_WORKFLOW} copy",
        "run",
        "run_failure_reporter",
        "schedule_tick",
    ]
    assert "workflow:delete" in n8n.scopes
    assert any(line.startswith(f"workflow {OLD_RUN_WORKFLOW} (W1): removed") for line in said)
