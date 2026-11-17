import json
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import TypeAdapter

from platform_api import bootstrap, migrate, old_runs
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
from platform_api.n8n_guard import DEPRECATED, SAFE
from platform_api.orchestration.n8n import N8nClient
from platform_api.orchestration.n8n_blocks import LEFT_OUT
from platform_api.orchestration.node_classes import NODE_CLASSES
from platform_api.orchestration.spec import RunSpec
from platform_api.settings import BootstrapSettings
from tests.conftest import PostgresUrls, truncate_all
from tests.support import LOCAL_ENV, NOW, SPEC

N8N = "http://n8n.test"
TRUNK_HEADS = {"monitoring": "0001", "orchestration": "0004", "builder": "0003"}
READY = (True, "all workflows loaded, active and linted")
GUARDS_FAIL = (False, "n8n's blocks or settings fail the check")
OWNER_EXISTS = "Instance owner already setup"
N8N_VERSION = "2.42.6"
SHOWN: dict[str, Any] = {
    "versionCli": N8N_VERSION,
    "allowedModules": {},
    "security": {"blockFileAccessToN8nFiles": True},
    "excludeNodes": sorted(LEFT_OUT),
    "communityNodesEnabled": False,
}
"""What n8n 2.42.6 shows at /rest/settings with the platform's settings, cut down."""


def env_for(owner_url: str) -> dict[str, str]:
    return {
        "DATABASE_URL_OWNER": owner_url,
        "N8N_BASE_URL": N8N,
        "N8N_OWNER_EMAIL": "owner@example.com",
        "N8N_OWNER_PASSWORD": "Aa1secret",
        "STEP_KEY": "step-key",
        "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
        **SAFE,
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


PLATFORM_PROJECT = "P-owner"
MEMBER_PROJECT = "P-alice"


def in_project(project: str) -> list[dict[str, str]]:
    """How n8n's public API names a workflow's home project."""
    return [{"role": "workflow:owner", "projectId": project}]


class FakeN8n:
    """`existing` sit in the platform's project, the owner's own, and `theirs` in a member's."""

    def __init__(
        self, existing: list[str], theirs: list[str] | None = None, owner_exists: bool = False
    ) -> None:
        self.owner_exists = owner_exists
        self.unreadable = False
        """Every read of one workflow fails, as when n8n is still starting."""
        placed = [(name, PLATFORM_PROJECT) for name in existing]
        placed += [(name, MEMBER_PROJECT) for name in theirs or []]
        self.workflows: dict[str, dict[str, Any]] = {
            f"W{n}": {
                "id": f"W{n}",
                "name": name,
                "active": True,
                "nodes": [],
                "settings": {},
                "shared": in_project(project),
            }
            for n, (name, project) in enumerate(placed, start=1)
        }
        self.deleted: list[str] = []
        self.credentials: list[str] = []
        self.unpublishing: set[str] = set()
        self.calls: list[str] = []
        self.scopes: list[str] = []
        self.next_id = len(placed) + 1
        self.api_keys = [
            {"id": "k1", "label": "platform-api"},
            {"id": "k2", "label": "Alice's own key"},
        ]
        self.node_types = [*NODE_CLASSES.names(), "n8n-nodes-base.airtable"]
        """What n8n loaded: every built-in block, cut down to the ones the class file names
        and one more."""
        self.settings = deepcopy(SHOWN)
        self.env_run = "refused"
        """How a run that reads `$env` goes: "refused", as n8n refuses it while
        N8N_BLOCK_ENV_ACCESS_IN_NODE is on; "open", as with it off; "never_starts", as when n8n
        doesn't know the block's version; "never_ends"; or "breaks", with another error."""
        self.fields_work = True
        """Edit Fields gives back what it was given, as on a pin that still has version 3.4."""
        self.python_run = "ok"
        """How a Python Code run goes: "ok", as with the external task runner connected;
        "down", with none; or "never_ends"."""
        self.executions: dict[str, dict[str, Any]] = {}
        self.runs_deprecated = False
        """n8n runs a workflow with a deprecated block by hand, as when NODES_EXCLUDE leaves it in
        and N8N_DEPRECATED_NODES_BLOCK is false. Either way n8n saves it, as it saves a block it
        doesn't load."""

    def ran(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        last = nodes[-1]
        parameters = last.get("parameters", {})
        name = last["name"]
        if "$env" in json.dumps(parameters):
            match self.env_run:
                case "open":
                    return ran_ok(name, {"home": "/home/node"})
                case "never_ends":
                    return {"status": "running"}
                case "breaks":
                    return ran_into(name, "Cannot read properties of undefined (reading 'x')")
                case _:
                    return ran_into(name, "access to env vars denied")
        if parameters.get("language") == "pythonNative":
            match self.python_run:
                case "ok":
                    return ran_ok(name, {"ran": "python"})
                case "never_ends":
                    return {"status": "running"}
                case _:
                    return ran_into(name, "Python runner unavailable")
        if last["type"] == "n8n-nodes-base.set":
            if not self.fields_work:
                return ran_ok(name, {"home": None})
            assigned = parameters["assignments"]["assignments"]
            return ran_ok(name, {a["name"]: str(a["value"]).removeprefix("=") for a in assigned})
        return ran_ok(name, {})

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else None
        if path == "/healthz/readiness":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/rest/owner/setup" and self.owner_exists:
            return httpx.Response(400, json={"message": OWNER_EXISTS})
        if path in ("/rest/owner/setup", "/rest/login"):
            return httpx.Response(200, json={"data": {"id": "1"}})
        if path == "/types/nodes.json":
            return httpx.Response(200, json=[{"name": t, "version": 1} for t in self.node_types])
        if path == "/rest/settings":
            return httpx.Response(200, json={"data": self.settings})
        if path.startswith("/rest/workflows/") and path.endswith("/run"):
            held = self.workflows[path.split("/")[3]]
            deprecated = [n["type"] for n in held["nodes"] if n["type"] in DEPRECATED]
            if deprecated and not self.runs_deprecated:
                return httpx.Response(
                    400, json={"message": f"Unrecognized node type: {deprecated[0]}"}
                )
            if self.env_run == "never_starts" and "$env" in json.dumps(held["nodes"]):
                return httpx.Response(
                    400, json={"message": "Node type set is not available in version 3.4"}
                )
            execution_id = f"E{len(self.executions) + 1}"
            self.executions[execution_id] = self.ran(held["nodes"])
            return httpx.Response(200, json={"data": {"executionId": execution_id}})
        if path.startswith("/api/v1/executions/") and method == "GET":
            return httpx.Response(200, json=self.executions[path.split("/")[4]])
        if path == "/rest/projects/personal":
            return httpx.Response(200, json={"data": {"id": PLATFORM_PROJECT, "type": "personal"}})
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
            created = {**body, "id": workflow_id, "active": False}
            self.workflows[workflow_id] = {**created, "shared": in_project(PLATFORM_PROJECT)}
            return httpx.Response(200, json=self.workflows[workflow_id])
        if path.startswith("/api/v1/workflows/"):
            workflow_id = path.split("/")[4]
            if method == "GET" and self.unreadable:
                return httpx.Response(503, json={"message": "starting"})
            if method == "GET" and workflow_id not in self.workflows:
                return httpx.Response(404, json={"message": "Not Found"})
            self.calls.append(f"{method} {path.removeprefix('/api/v1/workflows/')}")
            if workflow_id not in self.workflows:
                return httpx.Response(404, json={"message": "Not Found"})
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


def ran_ok(node: str, item: dict[str, Any]) -> dict[str, Any]:
    run = {"data": {"main": [[{"json": item}]]}}
    return {"status": "success", "data": {"resultData": {"runData": {node: [run]}}}}


def ran_into(node: str, message: str) -> dict[str, Any]:
    run = {"error": {"message": message}}
    return {"status": "error", "data": {"resultData": {"runData": {node: [run]}}}}


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
        n8n_settings=dict(SAFE),
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


def test_a_workflow_still_on_the_shared_run_workflow_with_no_open_run_lets_it_go(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """The allow list turns its blocks off, and the workflow moves to its own as platform-api
    starts (ENGINE-PLAN E10)."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run", "schedule_tick"]))
    n8n.credentials = ["cred0"]
    recorded(postgres.owner, {"run": "W1", "schedule_tick": "W2"})
    insert_use_case(postgres.owner, "uc_cards", "agent_cards")

    assert main(env_for(postgres.owner)) == 0

    assert names_in(n8n) == ["run_failure_reporter", "self_test_failure"]
    assert n8n.credentials == [], "nothing needs the step key"
    assert engine_status(postgres.owner) == READY


def test_a_run_on_the_shared_run_workflow_that_has_not_ended_leaves_bootstrap_ready(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """No block it needs can run under the allow list, so the shared run workflow goes, and
    platform-api ends the run as it starts, saying so (ENGINE-PLAN E11). On Azure the apps
    change before bootstrap runs, so a stop here could only hold every workflow back."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run"]))
    recorded(postgres.owner, {"run": "W1"})
    spec = TypeAdapter(RunSpec).dump_python(replace(SPEC, n8n=None), mode="json")
    insert_run(postgres.owner, "run_waiting", spec)
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("UPDATE orchestration.runs SET state = 'AwaitingApproval'")

    assert main(env_for(postgres.owner)) == 0

    assert engine_status(postgres.owner) == READY
    assert names_in(n8n) == ["run_failure_reporter", "self_test_failure"]
    assert old_runs.main({"DATABASE_URL_OWNER": postgres.owner}) == 0
    listed = capsys.readouterr().out
    assert f"run_waiting\t{SPEC.use_case_id}\tAwaitingApproval\tstarted " in listed, listed
    assert listed.endswith("1 run(s) on the shared run workflow have not ended.\n")


@pytest.mark.parametrize(
    ("loads", "says"),
    [
        (
            [t for t in NODE_CLASSES.names() if t != "n8n-nodes-base.httpRequest"],
            "n8n does not load 1 block(s) the class file names, n8n-nodes-base.httpRequest: "
            "NODES_INCLUDE must be unset, so n8n loads every built-in block",
        ),
        (
            [*NODE_CLASSES.names(), "n8n-nodes-base.executeCommand"],
            "n8n loads n8n-nodes-base.executeCommand, which NODES_EXCLUDE must leave out",
        ),
        (
            [*NODE_CLASSES.names(), "n8n-nodes-community.anything"],
            "n8n loads 1 block(s) that are not n8n's own or ours, n8n-nodes-community.anything",
        ),
    ],
    ids=["an-allow-list", "a-block-left-out", "a-community-node"],
)
def test_bootstrap_is_not_ready_unless_n8n_loads_every_built_in_block_but_the_two(
    postgres: PostgresUrls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    loads: list[str],
    says: str,
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.node_types = loads

    assert main(env_for(postgres.owner)) == 1

    assert says in capsys.readouterr().out
    assert engine_status(postgres.owner) == GUARDS_FAIL


@pytest.mark.parametrize(
    ("deployed", "shown", "says"),
    [
        ({"N8N_RUNNERS_MODE": "internal"}, {}, "N8N_RUNNERS_MODE must be external"),
        ({"N8N_BLOCK_ENV_ACCESS_IN_NODE": None}, {}, "N8N_BLOCK_ENV_ACCESS_IN_NODE must be true"),
        ({"N8N_RESTRICT_FILE_ACCESS_TO": ""}, {}, "N8N_RESTRICT_FILE_ACCESS_TO is empty"),
        ({"N8N_RUNNERS_INSECURE_MODE": "true"}, {}, "N8N_RUNNERS_INSECURE_MODE must be unset"),
        ({}, {"allowedModules": {"builtIn": ["*"]}}, "NODE_FUNCTION_ALLOW_BUILTIN set"),
        ({}, {"security": {"blockFileAccessToN8nFiles": False}}, "reach its own folders"),
        (
            {"NODES_EXCLUDE": '["n8n-nodes-base.executeCommand"]'},
            {},
            "NODES_EXCLUDE must leave out",
        ),
        ({}, {"excludeNodes": ["n8n-nodes-base.executeCommand"]}, "n8n's NODES_EXCLUDE leaves in"),
    ],
    ids=[
        "internal-runner",
        "env-open",
        "files-open",
        "insecure",
        "modules",
        "n8n-files",
        "exclude-deployed",
        "exclude-shown",
    ],
)
def test_bootstrap_is_not_ready_when_n8n_s_settings_break_a_guard(
    postgres: PostgresUrls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deployed: dict[str, str | None],
    shown: dict[str, Any],
    says: str,
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.settings.update(shown)
    env = {**env_for(postgres.owner), **deployed}

    assert main({k: v for k, v in env.items() if v is not None}) == 1

    assert says in capsys.readouterr().out
    assert engine_status(postgres.owner) == GUARDS_FAIL


def test_bootstrap_is_not_ready_when_n8n_runs_a_deprecated_block_and_removes_what_it_saved(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.runs_deprecated = True

    assert main(env_for(postgres.owner)) == 1

    said = capsys.readouterr().out
    for node_type in DEPRECATED:
        assert f"n8n runs a workflow with {node_type} by hand, which NODES_EXCLUDE must" in said
    assert names_in(n8n) == ["run_failure_reporter", "self_test_failure"], "it took none back"
    assert engine_status(postgres.owner) == GUARDS_FAIL


@pytest.mark.parametrize(
    ("env_run", "said"),
    [
        ("open", "n8n read $env in an expression on a run by hand"),
        ("never_starts", "n8n's $env check didn't start"),
        ("never_ends", "n8n's $env check didn't end in time"),
        ("breaks", "n8n's $env check ended in an error other than"),
    ],
)
def test_bootstrap_is_not_ready_unless_the_running_n8n_refuses_env(
    postgres: PostgresUrls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_run: str,
    said: str,
):
    """The deploy's settings can say one thing and n8n run with another, so bootstrap asks n8n.
    Only n8n's own refusal shows `$env` is closed: a run that never starts, never ends or fails
    for another reason shows nothing."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.env_run = env_run

    assert main(env_for(postgres.owner)) == 1

    assert said in capsys.readouterr().out
    assert engine_status(postgres.owner) == GUARDS_FAIL


def test_bootstrap_is_not_ready_when_edit_fields_doesn_t_run_as_the_env_check_expects(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The control: the same block with a plain expression must give back what it was given,
    or the `$env` run's refusal could come from a block that no longer works on this pin."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.fields_work = False

    assert main(env_for(postgres.owner)) == 1

    assert "n8n's Edit Fields check gave back something else" in capsys.readouterr().out
    assert engine_status(postgres.owner) == GUARDS_FAIL


@pytest.mark.parametrize(
    ("python_run", "said"),
    [
        ("down", "n8n's Python check ended with status error"),
        ("never_ends", "n8n's Python check didn't end in time"),
    ],
)
def test_bootstrap_is_not_ready_unless_the_external_runner_runs_python(
    postgres: PostgresUrls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    python_run: str,
    said: str,
):
    """n8n's image has no Python, so a Python Code block runs only in the external runner."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    n8n.python_run = python_run

    assert main(env_for(postgres.owner)) == 1

    assert said in capsys.readouterr().out
    assert engine_status(postgres.owner) == GUARDS_FAIL


def test_bootstrap_records_the_n8n_version_it_checked(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """The workflow drafter's catalogue names the n8n it was made from, and drafting pauses
    while the two differ (ADR 0051, section 8)."""
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n([]))

    assert main(env_for(postgres.owner)) == 0

    with psycopg.connect(postgres.owner) as conn:
        row = conn.execute("SELECT n8n_version FROM orchestration.engine_status").fetchone()
    assert row == (N8N_VERSION,)


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

    loaded = load_into_n8n(settings_for(postgres.owner), said.append).workflows

    assert [w.name for w in loaded] == ["run_failure_reporter", "self_test_failure"]
    assert names_in(n8n) == [
        "Staff access review",
        "run",
        "run_failure_reporter",
        "self_test_failure",
    ]
    assert "W4" in n8n.workflows, "a staff workflow named run is not the platform's"
    assert any(line.startswith("workflow run (W1): removed") for line in said)
    assert n8n.credentials == [], "nothing loaded names the step key, so it goes"


def test_bootstrap_removes_the_old_run_workflow_by_its_exact_name_and_nothing_else(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(
        monkeypatch, FakeN8n([OLD_RUN_WORKFLOW, "Staff access review", f"{OLD_RUN_WORKFLOW} copy"])
    )
    said: list[str] = []

    load = load_into_n8n(settings_for(postgres.owner), said.append)
    loaded = load.workflows

    assert load.findings == [] and load.guards == []
    assert sorted(w.name for w in loaded) == ["run_failure_reporter", "self_test_failure"]
    assert all(w.active for w in loaded)
    assert [w for w in n8n.deleted if w in ("W1", "W2", "W3")] == ["W1"], (
        "of what n8n held, only W1. The rest are bootstrap's own probes"
    )
    assert [c for c in n8n.calls if c.split()[1].split("/")[0] == "W1"] == [
        "POST W1/deactivate",
        "DELETE W1",
        "DELETE W1",
    ]
    assert sorted(w["name"] for w in n8n.workflows.values()) == [
        "Staff access review",
        f"{OLD_RUN_WORKFLOW} copy",
        "run_failure_reporter",
        "self_test_failure",
    ]
    assert "workflow:delete" in n8n.scopes
    assert any(line.startswith(f"workflow {OLD_RUN_WORKFLOW} (W1): removed") for line in said)
    assert n8n.api_keys == [{"id": "k2", "label": "Alice's own key"}], "platform-api makes its own"


def restore_pending(owner_url: str) -> list[str] | None:
    """The workflows the restore was asked for, or None when none was asked."""
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT missing FROM builder.n8n_restore").fetchone()
    return None if row is None else list(row[0])


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
    assert restore_pending(postgres.owner) == ["wf_gone"]


def test_an_n8n_that_holds_a_workflow_our_records_name_asks_for_no_restore(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n(["run_failure_reporter"], owner_exists=True))
    recorded(postgres.owner, {"run_failure_reporter": "W1"})
    own_use_case(postgres.owner, "uc_own", "wf_staff_deleted")
    assert main(env_for(postgres.owner)) == 0
    assert restore_pending(postgres.owner) is None


def test_an_n8n_that_cannot_be_read_is_never_taken_for_empty(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([], owner_exists=True))
    n8n.unreadable = True
    own_use_case(postgres.owner, "uc_own", "wf_somewhere")
    main(env_for(postgres.owner))
    assert restore_pending(postgres.owner) is None


def test_a_new_n8n_with_nothing_on_record_asks_for_no_restore(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    serve(monkeypatch, FakeN8n([]))
    assert main(env_for(postgres.owner)) == 0
    assert restore_pending(postgres.owner) is None


def loaded_names(owner_url: str) -> dict[str, str]:
    """The workflows bootstrap recorded, by name, as platform-api reads them."""
    with psycopg.connect(owner_url) as conn:
        row = conn.execute("SELECT workflows FROM orchestration.engine_status").fetchone()
    assert row is not None
    return {w["name"]: w["id"] for w in row[0]}


def test_the_error_workflow_and_the_self_test_are_loaded_active_and_every_failure_goes_there(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    insert_use_case(postgres.owner, "uc_cards", "agent_cards")

    assert main(env_for(postgres.owner)) == 0

    held = {w["name"]: w for w in n8n.workflows.values()}
    assert all(w["active"] for w in held.values()), "n8n skips an inactive error workflow"
    reporter = held["run_failure_reporter"]
    assert [n["type"] for n in reporter["nodes"]] == [
        "n8n-nodes-base.errorTrigger",
        "CUSTOM.wabReportFailure",
    ], "Report a failure, not an HTTP node"
    assert reporter["settings"]["callerPolicy"] == "any"
    assert held["self_test_failure"]["settings"]["errorWorkflow"] == reporter["id"]
    assert engine_status(postgres.owner) == READY
    recorded = loaded_names(postgres.owner)
    assert recorded["run_failure_reporter"] == reporter["id"]
    assert recorded["self_test_failure"] == held["self_test_failure"]["id"]


@pytest.mark.parametrize(
    ("setting", "zone"), [(None, "Asia/Singapore"), ("Europe/London", "Europe/London")]
)
def test_the_self_test_runs_on_the_team_time_zone(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, setting: str | None, zone: str
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    env = env_for(postgres.owner) | ({} if setting is None else {"TEAM_TIME_ZONE": setting})

    assert main(env) == 0

    [self_test] = by_name(n8n, "self_test_failure")
    assert self_test["settings"]["timezone"] == zone
    assert engine_status(postgres.owner) == READY


class DropsCallerPolicy(FakeN8n):
    """An n8n that does not keep the error workflow's callerPolicy."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        response = super().handle(request)
        for workflow in self.workflows.values():
            workflow.get("settings", {}).pop("callerPolicy", None)
        return response


def test_bootstrap_is_not_ready_when_n8n_holds_the_error_workflow_out_of_shape(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    truncate_all(postgres.owner)
    serve(monkeypatch, DropsCallerPolicy([]))

    assert main(env_for(postgres.owner)) == 1

    assert (
        "run_failure_reporter: Its setting callerPolicy must be 'any'." in capsys.readouterr().out
    )
    assert engine_status(postgres.owner) == (False, "the live workflows fail the lint")


def by_name(n8n: FakeN8n, name: str) -> list[dict[str, Any]]:
    return [w for w in n8n.workflows.values() if w["name"] == name]


def test_a_same_name_workflow_in_a_member_s_project_is_left_alone(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """A member could name a workflow of their own after the error workflow or the self-test.
    Bootstrap never takes it for the platform's, and never writes to it or removes it."""
    truncate_all(postgres.owner)
    theirs = ["run_failure_reporter", "self_test_failure", "run", "schedule_tick"]
    n8n = serve(monkeypatch, FakeN8n([], theirs=theirs))
    insert_use_case(postgres.owner, "uc_cards", "agent_cards")
    untouched = json.loads(json.dumps(n8n.workflows))

    assert main(env_for(postgres.owner)) == 0

    assert {k: n8n.workflows[k] for k in untouched} == untouched
    recorded = loaded_names(postgres.owner)
    for name in ("run_failure_reporter", "self_test_failure"):
        [ours] = [w for w in by_name(n8n, name) if w["shared"] == in_project(PLATFORM_PROJECT)]
        assert recorded[name] == ours["id"] not in untouched, name


def test_two_workflows_of_one_name_in_the_platform_project_stop_bootstrap(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n(["run_failure_reporter", "run_failure_reporter"]))
    before = json.loads(json.dumps(n8n.workflows))

    assert main(env_for(postgres.owner)) == 1

    said = "2 workflows named run_failure_reporter are in the platform's n8n project: W1, W2"
    assert said in capsys.readouterr().out
    assert engine_status(postgres.owner) == (False, said)
    assert n8n.workflows == before, "bootstrap wrote to neither"


def test_a_recorded_workflow_moved_out_of_the_platform_project_stops_bootstrap(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    assert main(env_for(postgres.owner)) == 0
    reporter = loaded_names(postgres.owner)["run_failure_reporter"]
    n8n.workflows[reporter]["shared"] = in_project(MEMBER_PROJECT)

    moved = (False, f"run_failure_reporter ({reporter}) is no longer in the platform's n8n project")
    assert main(env_for(postgres.owner)) == 1
    assert engine_status(postgres.owner) == moved
    assert main(env_for(postgres.owner)) == 1, "it stays stopped until a person puts it back"
    assert engine_status(postgres.owner) == moved


class ListsWithoutProjects(FakeN8n):
    """An n8n whose list of workflows does not say which project each belongs to."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        response = super().handle(request)
        if request.url.path != "/api/v1/workflows" or request.method != "GET":
            return response
        listed = [{k: v for k, v in w.items() if k != "shared"} for w in response.json()["data"]]
        return httpx.Response(200, json={"data": listed})


def test_bootstrap_stops_when_n8n_lists_a_same_name_workflow_without_its_project(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    """Else a second workflow of the name would pass unseen, and the guard against two never
    fires."""
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, ListsWithoutProjects(["run_failure_reporter"]))
    before = json.loads(json.dumps(n8n.workflows))

    assert main(env_for(postgres.owner)) == 1

    assert engine_status(postgres.owner) == (
        False,
        "n8n listed run_failure_reporter (W1) without its project, so bootstrap cannot tell "
        "whose it is",
    )
    assert n8n.workflows == before


def test_bootstrap_keeps_to_the_workflow_it_recorded_over_a_copy_of_the_same_name(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    n8n = serve(monkeypatch, FakeN8n([]))
    assert main(env_for(postgres.owner)) == 0
    first = loaded_names(postgres.owner)
    copy = {**n8n.workflows[first["self_test_failure"]], "id": "W99"}
    n8n.workflows["W99"] = copy

    assert main(env_for(postgres.owner)) == 0

    assert loaded_names(postgres.owner) == first


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
