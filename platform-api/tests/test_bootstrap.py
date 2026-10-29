import json
from typing import Any

import httpx
import psycopg
import pytest

from platform_api import bootstrap
from platform_api.bootstrap import (
    OLD_RUN_WORKFLOW,
    OLD_TASK_KIND,
    OLD_TEMPLATE,
    RESET_HINT,
    load_into_n8n,
    main,
)
from platform_api.orchestration.n8n import N8nClient
from platform_api.orchestration.workflows import load_all
from platform_api.settings import BootstrapSettings
from tests.conftest import PostgresUrls, truncate_all
from tests.support import NOW

N8N = "http://n8n.test"


def env_for(postgres: PostgresUrls) -> dict[str, str]:
    return {
        "DATABASE_URL_OWNER": postgres.owner,
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
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, "
            "started_by, started_at, updated_at, version, state, state_data, deadline_at, "
            "retried_by, carry_forward) VALUES ('run_old', 'uc_old', 'key-old', %s, 'alice', "
            "%s, %s, 1, 'Succeeded', %s, NULL, '[]', NULL)",
            (
                json.dumps(spec),
                NOW,
                NOW,
                json.dumps({"run_id": "run_old", "outcome": "nothing_to_write", "written": []}),
            ),
        )


def insert_old_use_case(owner_url: str) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version) "
            "VALUES ('uc_old', 'alice', %s, 1)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at) VALUES ('uc_old', 1, %s, 'n', 'i', '{}', %s)",
            (OLD_TEMPLATE, NOW),
        )


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
def test_old_release_data_stops_bootstrap_before_n8n_and_deletes_nothing(
    postgres: PostgresUrls, capsys: pytest.CaptureFixture[str], plant: Any, named: str
):
    truncate_all(postgres.owner)
    plant(postgres.owner)
    assert main(env_for(postgres)) == 1
    said = capsys.readouterr().out
    assert named in said and RESET_HINT in said
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
            if path.endswith("/activate"):
                self.workflows[workflow_id]["active"] = True
            elif method == "PUT":
                self.workflows[workflow_id].update(body)
            elif method == "DELETE":
                self.deleted.append(workflow_id)
                del self.workflows[workflow_id]
            return httpx.Response(200, json=self.workflows.get(workflow_id, {}))
        return httpx.Response(404, json={"message": f"no fake for {method} {path}"})


def test_bootstrap_removes_the_old_run_workflow_by_its_exact_name_and_nothing_else(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = FakeN8n([OLD_RUN_WORKFLOW, "Staff access review", f"{OLD_RUN_WORKFLOW} copy"])
    monkeypatch.setattr(
        bootstrap,
        "N8nClient",
        lambda base_url: N8nClient(
            base_url, transport=httpx.MockTransport(n8n.handle), sleep=lambda _: None
        ),
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
    assert sorted(w["name"] for w in n8n.workflows.values()) == [
        "Staff access review",
        f"{OLD_RUN_WORKFLOW} copy",
        "run",
        "run_failure_reporter",
        "schedule_tick",
    ]
    assert "workflow:delete" in n8n.scopes
    assert any(line.startswith(f"workflow {OLD_RUN_WORKFLOW} (W1): removed") for line in said)
