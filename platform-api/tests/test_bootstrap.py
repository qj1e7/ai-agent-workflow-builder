import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import TypeAdapter

from platform_api import bootstrap, migrate
from platform_api.app import create_app
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
from tests.support import LOCAL_ENV, NOW, SPEC

N8N = "http://n8n.test"
TRUNK_HEADS = {"monitoring": "0001", "orchestration": "0004", "builder": "0003"}
READY = (True, "all workflows loaded, active and linted")
OWNER_EXISTS = "Instance owner already setup"


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
    for context in MIGRATION_ORDER:
        downgrade(context, postgres.owner, TRUNK_HEADS[context])
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
    def __init__(self, existing: list[str], owner_exists: bool = False) -> None:
        self.owner_exists = owner_exists
        self.unreadable = False
        """Every read of one workflow fails, as when n8n is still starting."""
        self.workflows: dict[str, dict[str, Any]] = {
            f"W{n}": {"id": f"W{n}", "name": name, "active": True, "nodes": [], "settings": {}}
            for n, name in enumerate(existing, start=1)
        }
        self.deleted: list[str] = []
        self.credentials: list[str] = []
        self.unpublishing: set[str] = set()
        self.calls: list[str] = []
        self.scopes: list[str] = []
        self.next_id = len(existing) + 1
        self.api_keys = [
            {"id": "k1", "label": "platform-api"},
            {"id": "k2", "label": "Alice's own key"},
        ]

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else None
        if path == "/healthz/readiness":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/rest/owner/setup" and self.owner_exists:
            return httpx.Response(400, json={"message": OWNER_EXISTS})
        if path in ("/rest/owner/setup", "/rest/login"):
            return httpx.Response(200, json={"data": {"id": "1"}})
        if path == "/rest/api-keys" and method == "GET":
            return httpx.Response(200, json={"data": {"items": self.api_keys}})
        if path.startswith("/rest/api-keys/") and method == "DELETE":
            gone = path.removeprefix("/rest/api-keys/")
            self.api_keys = [key for key in self.api_keys if key["id"] != gone]
            return httpx.Response(200, json={"data": True})
        if path == "/rest/api-keys" and method == "POST":
            self.scopes = list(body["scopes"])
            return httpx.Response(200, json={"data": {"rawApiKey": "key"}})
        if path == "/api/v1/credentials" and method == "POST":
            self.credentials.append("cred1")
            return httpx.Response(200, json={"id": "cred1"})
        if path == "/api/v1/credentials" and method == "GET":
            listed = [{"id": c, "name": "X-Step-Key"} for c in self.credentials]
            return httpx.Response(200, json={"data": listed})
        if path.startswith("/api/v1/credentials/") and method == "DELETE":
            self.credentials.remove(path.removeprefix("/api/v1/credentials/"))
            return httpx.Response(200, json={})
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
            if method == "GET" and self.unreadable:
                return httpx.Response(503, json={"message": "starting"})
            if method == "GET" and workflow_id not in self.workflows:
                return httpx.Response(404, json={"message": "Not Found"})
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


@pytest.fixture
def fresh_url(postgres: PostgresUrls) -> Iterator[str]:
    fresh = f"{PLATFORM_DATABASE}_fresh"
    with psycopg.connect(postgres.superuser, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(fresh)))
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(fresh), sql.Identifier(ROLE_OWNER)
            )
        )
    try:
        yield postgres.owner.rsplit("/", 1)[0] + f"/{fresh}"
    finally:
        with psycopg.connect(postgres.superuser, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(fresh))
            )


def test_a_fresh_database_passes_the_check_and_is_migrated(
    postgres: PostgresUrls, fresh_url: str, monkeypatch: pytest.MonkeyPatch
):
    serve(monkeypatch, FakeN8n([]))
    assert unreadable_data(fresh_url) == []
    assert main(env_for(fresh_url)) == 0
    assert migration_heads(fresh_url) == migration_heads(postgres.owner)
    assert engine_status(fresh_url) == READY


def columns(owner_url: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = ANY(%s) ORDER BY 1, 2, 3",
            (list(MIGRATION_ORDER),),
        ).fetchall()
    return [(str(s), str(t), str(c)) for s, t, c in rows]


def test_migrate_brings_an_empty_database_to_head_and_a_second_run_changes_nothing(
    postgres: PostgresUrls, fresh_url: str
):
    env = {"DATABASE_URL_OWNER": fresh_url}

    assert migrate.main(env) == 0
    heads, schema = migration_heads(fresh_url), columns(fresh_url)
    assert heads == migration_heads(postgres.owner)
    assert migrate.main(env) == 0

    assert (migration_heads(fresh_url), columns(fresh_url)) == (heads, schema)
    with psycopg.connect(fresh_url) as conn:
        assert conn.execute("SELECT count(*) FROM orchestration.engine_status").fetchone() == (0,)


@pytest.mark.usefixtures("at_trunk_heads")
def test_old_release_data_stops_migrate_before_any_migration(
    postgres: PostgresUrls, capsys: pytest.CaptureFixture[str]
):
    insert_old_run(postgres.owner)
    assert migrate.main({"DATABASE_URL_OWNER": postgres.owner}) == 1
    assert migration_heads(postgres.owner) == TRUNK_HEADS
    assert RESET_HINT in capsys.readouterr().out


def settings_for(owner_url: str) -> BootstrapSettings:
    return BootstrapSettings(
        owner_database_url=owner_url,
        n8n_base_url=N8N,
        n8n_owner_email="owner@example.com",
        n8n_owner_password="Aa1secret",
        step_key="step-key",
        platform_internal_url="http://platform-api:8000",
    )


def names_in(n8n: FakeN8n) -> list[str]:
    return sorted(w["name"] for w in n8n.workflows.values())


def recorded(owner_url: str, ids: dict[str, str]) -> None:
    """What the last bootstrap loaded, as it records it."""
    loaded = [{"name": name, "id": id, "active": True, "sha256": "x"} for name, id in ids.items()]
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.engine_status (id, loaded_at, ready, detail, workflows)"
            " VALUES (1, now(), true, 'loaded', %s)",
            (json.dumps(loaded),),
        )


def test_while_a_workflow_runs_on_the_shared_run_workflow_bootstrap_keeps_it(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run", "schedule_tick"]))
    recorded(postgres.owner, {"run": "W1", "schedule_tick": "W2"})
    insert_use_case(postgres.owner, "uc_cards", "agent_cards")

    loaded, findings = load_into_n8n(settings_for(postgres.owner), load_all(), lambda _: None)

    assert findings == []
    assert sorted(w.name for w in loaded) == ["run", "run_failure_reporter"]
    assert names_in(n8n) == ["run", "run_failure_reporter"], "the schedule tick goes at once"
    assert n8n.credentials == ["cred1"], "the run workflow's steps still need the step key"


def test_a_run_that_has_not_ended_keeps_the_shared_run_workflow(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """Its workflow was deleted, but its yes may still come, and its write runs there."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run"]))
    recorded(postgres.owner, {"run": "W1"})
    spec = TypeAdapter(RunSpec).dump_python(replace(SPEC, n8n=None), mode="json")
    insert_run(postgres.owner, "run_waiting", spec)
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("UPDATE orchestration.runs SET state = 'AwaitingApproval'")

    load_into_n8n(settings_for(postgres.owner), load_all(), lambda _: None)

    assert names_in(n8n) == ["run", "run_failure_reporter"]


def test_once_nothing_runs_on_it_bootstrap_removes_the_shared_run_and_tick_workflows(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run", "schedule_tick", "Staff access review", "run"]))
    recorded(postgres.owner, {"run": "W1", "schedule_tick": "W2"})
    insert_use_case(postgres.owner, "uc_moved", "agent_cards")
    insert_run(postgres.owner, "run_done", TypeAdapter(RunSpec).dump_python(SPEC, mode="json"))
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("UPDATE builder.use_cases SET engine = 'own', n8n_workflow_id = 'wf_moved'")
    said: list[str] = []

    loaded, _ = load_into_n8n(settings_for(postgres.owner), load_all(), said.append)

    assert [w.name for w in loaded] == ["run_failure_reporter"]
    assert names_in(n8n) == ["Staff access review", "run", "run_failure_reporter"]
    assert "W4" in n8n.workflows, "a staff workflow named run is not the platform's"
    assert any(line.startswith("workflow run (W1): removed") for line in said)
    assert n8n.credentials == ["cred1"], "kept while the error workflow still reports with it"


def test_bootstrap_removes_the_old_run_workflow_by_its_exact_name_and_nothing_else(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(
        monkeypatch, FakeN8n([OLD_RUN_WORKFLOW, "Staff access review", f"{OLD_RUN_WORKFLOW} copy"])
    )
    said: list[str] = []

    loaded, findings = load_into_n8n(settings_for(postgres.owner), load_all(), said.append)

    assert findings == []
    assert sorted(w.name for w in loaded) == ["run_failure_reporter"]
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
        "run_failure_reporter",
    ]
    assert "workflow:delete" in n8n.scopes
    assert any(line.startswith(f"workflow {OLD_RUN_WORKFLOW} (W1): removed") for line in said)
    assert n8n.api_keys == [{"id": "k2", "label": "Alice's own key"}], "platform-api makes its own"


def restore_pending(owner_url: str) -> bool:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT 1 FROM builder.n8n_restore").fetchone()
    return row is not None


def own_use_case(owner_url: str, use_case_id: str, workflow_id: str) -> None:
    insert_use_case(owner_url, use_case_id, "agent_cards")
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE builder.use_cases SET engine = 'own', n8n_workflow_id = %s"
            " WHERE use_case_id = %s",
            (workflow_id, use_case_id),
        )


def test_an_n8n_that_kept_its_owner_but_lost_every_workflow_asks_for_a_restore(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """On Azure n8n makes its owner from its settings on every start, so an emptied n8n still
    has one. What tells is that n8n holds none of the workflows our records name."""
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n([], owner_exists=True))
    recorded(postgres.owner, {"run_failure_reporter": "W7"})
    own_use_case(postgres.owner, "uc_own", "wf_gone")
    assert main(env_for(postgres.owner)) == 0
    assert restore_pending(postgres.owner)


def test_an_n8n_that_holds_a_workflow_our_records_name_asks_for_no_restore(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n(["run_failure_reporter"], owner_exists=True))
    recorded(postgres.owner, {"run_failure_reporter": "W1"})
    own_use_case(postgres.owner, "uc_own", "wf_staff_deleted")
    assert main(env_for(postgres.owner)) == 0
    assert not restore_pending(postgres.owner)


def test_an_n8n_that_cannot_be_read_is_never_taken_for_empty(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([], owner_exists=True))
    n8n.unreadable = True
    own_use_case(postgres.owner, "uc_own", "wf_somewhere")
    main(env_for(postgres.owner))
    assert not restore_pending(postgres.owner)


def test_a_new_n8n_with_nothing_on_record_asks_for_no_restore(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n([]))
    assert main(env_for(postgres.owner)) == 0
    assert not restore_pending(postgres.owner)


SECRET_ADDRESS = "wab-secret-host.internal.example"


def n8n_unreachable(*args: object) -> None:
    raise httpx.ConnectError(f"Failed to reach http://{SECRET_ADDRESS}:5678/rest/login")


def test_a_failure_logs_its_error_but_readiness_names_only_its_class(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    truncate_all(postgres.owner)
    monkeypatch.setattr(bootstrap, "load_into_n8n", n8n_unreachable)

    assert main(env_for(postgres.owner)) == 1

    assert SECRET_ADDRESS in capsys.readouterr().out
    assert engine_status(postgres.owner) == (
        False,
        "could not load the workflows into n8n (ConnectError)",
    )
    app_env = {
        **LOCAL_ENV,
        "DATABASE_URL_BUILDER": postgres.contexts.builder,
        "DATABASE_URL_ORCHESTRATION": postgres.contexts.orchestration,
        "DATABASE_URL_MONITORING": postgres.contexts.monitoring,
    }
    with TestClient(create_app(app_env)) as client:
        ready = client.get("/healthz/ready")
    assert ready.status_code == 503
    assert SECRET_ADDRESS not in ready.text
