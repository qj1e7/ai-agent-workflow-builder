import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, LiteralString

import httpx
import psycopg
from psycopg.types.json import Jsonb

from platform_api.auth import ConfigError
from platform_api.migrations import upgrade_all
from platform_api.orchestration.n8n import PLATFORM_API_KEY_LABEL, N8nClient, N8nError
from platform_api.orchestration.workflow_check import (
    ERROR_WORKFLOW,
    PLATFORM_WORKFLOWS_DIR,
    SELF_TEST,
    check_platform,
)
from platform_api.orchestration.workflows import (
    LiveState,
    LiveWorkflow,
    WorkflowDefinition,
    lint,
    load_all,
    parse,
    render,
)
from platform_api.settings import BootstrapSettings, bootstrap_settings_from_env

API_KEY_LABEL = "platform-bootstrap"
CREDENTIAL_NAME = "X-Step-Key"
STEP_KEY_HEADER = "X-Step-Key"
# Only this exact name is removed: staff build their own workflows in the same n8n (ADR 0027).
OLD_RUN_WORKFLOW = "release_check"
OLD_TEMPLATE = "release_check"
OLD_TASK_KIND = "release"
RESET_HINT = (
    "This stack holds data from before the release check was retired, which the platform can "
    "no longer read. Reset a local practice stack with "
    "`docker compose -p <project> -f deploy/compose.yaml down -v`, then start it again."
)

type Say = Callable[[str], None]


@dataclass(frozen=True)
class LoadedWorkflow:
    name: str
    id: str
    active: bool
    sha256: str


def main(env: Mapping[str, str] | None = None) -> int:
    def say(message: str) -> None:
        print(f"bootstrap: {message}", flush=True)

    try:
        settings = bootstrap_settings_from_env(os.environ if env is None else env)
    except ConfigError as error:
        say(str(error))
        return 1
    if not migrate_to_head(settings.owner_database_url, say):
        return _finish(settings, say, [], [], "the database holds old release-check data")
    definitions = load_all()
    findings = [str(finding) for finding in lint(definitions)]
    if findings:
        return _finish(settings, say, [], findings, "the workflow files fail the lint")
    try:
        loaded, findings = load_into_n8n(settings, definitions, say)
    except (N8nError, httpx.HTTPError) as error:
        say(f"could not load the workflows into n8n: {error}")
        detail = _detail_without_message("could not load the workflows into n8n", error)
        return _finish(settings, say, [], [], detail)
    inactive = [w.name for w in loaded if not w.active]
    if inactive:
        return _finish(settings, say, loaded, findings, f"inactive in n8n: {', '.join(inactive)}")
    if findings:
        return _finish(settings, say, loaded, findings, "the live workflows fail the lint")
    return _finish(settings, say, loaded, [], "all workflows loaded, active and linted")


def migrate_to_head(owner_url: str, say: Say) -> bool:
    unreadable = unreadable_data(owner_url)
    if unreadable:
        for line in unreadable:
            say(line)
        say(RESET_HINT)
        return False
    upgrade_all(owner_url)
    say("database migrations are at head")
    return True


def _detail_without_message(what: str, error: Exception) -> str:
    return f"{what} ({type(error).__name__})"


def _finish(
    settings: BootstrapSettings,
    say: Say,
    loaded: list[LoadedWorkflow],
    findings: Sequence[str],
    detail: str,
) -> int:
    for finding in findings:
        say(finding)
    ready = not findings and bool(loaded)
    record_status(settings.owner_database_url, ready=ready, detail=detail, workflows=loaded)
    say(f"{'ready' if ready else 'NOT ready'}: {detail}")
    return 0 if ready else 1


def load_into_n8n(
    settings: BootstrapSettings, definitions: tuple[WorkflowDefinition, ...], say: Say
) -> tuple[list[LoadedWorkflow], list[str]]:
    previous = previous_hashes(settings.owner_database_url)
    client = N8nClient(settings.n8n_base_url)
    try:
        client.wait_healthy()
        say("n8n is healthy")
        owner = client.ensure_owner(settings.n8n_owner_email, settings.n8n_owner_password)
        say(f"owner {settings.n8n_owner_email}: {owner.value}")
        removed = client.fresh_api_key(API_KEY_LABEL)
        say(f"api key '{API_KEY_LABEL}': created, {removed} older removed")
        removed = client.remove_api_keys(PLATFORM_API_KEY_LABEL)
        say(f"api key '{PLATFORM_API_KEY_LABEL}': {removed} removed, platform-api makes its own")
        credential_id = client.create_header_credential(
            CREDENTIAL_NAME, STEP_KEY_HEADER, settings.step_key
        )
        say(f"credential '{CREDENTIAL_NAME}': created {credential_id}")
        platform = load_platform_workflows(client, previous, say)
        values = {
            "PLATFORM_INTERNAL_URL": settings.platform_internal_url,
            "STEP_KEY_CREDENTIAL_ID": credential_id,
            "ERROR_WORKFLOW_ID": platform.error_workflow,
        }
        hashes: dict[str, str] = {}
        for d in definitions:
            workflow_id, digest = _load(client, d, values, previous, say)
            hashes[workflow_id] = digest
        old = client.find_workflow(OLD_RUN_WORKFLOW)
        if old is not None:
            client.delete_workflow(old.id)
            say(f"workflow {OLD_RUN_WORKFLOW} ({old.id}): removed, every run now goes through run")
        stale = [c for c in client.credentials_named(CREDENTIAL_NAME) if c != credential_id]
        for credential in stale:
            client.delete_credential(credential)
        if stale:
            say(f"credential '{CREDENTIAL_NAME}': removed {len(stale)} older")
        records = [client.read_back(workflow_id) for workflow_id in hashes]
    finally:
        client.close()
    loaded = [
        *platform.loaded,
        *(LoadedWorkflow(r.name, r.id, r.active, hashes[r.id]) for r in records),
    ]
    live = LiveState(
        settings.platform_internal_url, {w.name: LiveWorkflow(w.id, w.active) for w in loaded}
    )
    findings = lint((parse(r.document) for r in records), live=live)
    return loaded, [*platform.findings, *(str(finding) for finding in findings)]


@dataclass(frozen=True)
class PlatformLoaded:
    error_workflow: str
    loaded: list[LoadedWorkflow]
    findings: list[str]


def load_platform_workflows(
    client: N8nClient, previous: Mapping[str, str], say: Say
) -> PlatformLoaded:
    """The platform's own n8n workflows, each made active (ENGINE-PLAN 2.8): the error workflow
    first, then the daily self-test, whose failures go to it. Each is checked as n8n holds it."""
    error = platform_document(ERROR_WORKFLOW)
    error_id = _upsert(client, error, _content_hash(error), previous, say)
    self_test = platform_document(SELF_TEST)
    self_test["settings"] = {**self_test["settings"], "errorWorkflow": error_id}
    self_test_id = _upsert(client, self_test, _content_hash(self_test), previous, say)
    loaded: list[LoadedWorkflow] = []
    findings: list[str] = []
    for workflow_id, body in ((error_id, error), (self_test_id, self_test)):
        record = client.read_back(workflow_id)
        loaded.append(LoadedWorkflow(record.name, record.id, record.active, _content_hash(body)))
        findings += [f"{record.name}: {f.text}" for f in check_platform(record.document, error_id)]
    return PlatformLoaded(error_id, loaded, findings)


def platform_document(name: str) -> dict[str, Any]:
    return json.loads((PLATFORM_WORKFLOWS_DIR / f"{name}.n8n.json").read_text())


def _load(
    client: N8nClient,
    definition: WorkflowDefinition,
    values: Mapping[str, str],
    previous: Mapping[str, str],
    say: Say,
) -> tuple[str, str]:
    digest = content_hash_without_credential(definition, values)
    return _upsert(client, render(definition, values), digest, previous, say), digest


def _upsert(
    client: N8nClient, body: dict[str, Any], digest: str, previous: Mapping[str, str], say: Say
) -> str:
    result = client.upsert_workflow(body)
    if result.created:
        change = "created"
    elif previous.get(body["name"]) == digest:
        change = "updated in place, same content as last bootstrap"
    else:
        change = "updated in place, content changed"
    say(f"workflow {body['name']} ({result.id}): {change}")
    return result.id


def content_hash_without_credential(
    definition: WorkflowDefinition, values: Mapping[str, str]
) -> str:
    return _content_hash(render(definition, {**values, "STEP_KEY_CREDENTIAL_ID": "<masked>"}))


def _content_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def unreadable_data(owner_url: str) -> list[str]:
    with psycopg.connect(owner_url) as conn:
        runs = _count_if_table_exists(
            conn, "orchestration.runs", "spec -> 'task' ->> 'kind' = %s", OLD_TASK_KIND
        )
        versions = _count_if_table_exists(
            conn, "builder.use_case_versions", "template = %s", OLD_TEMPLATE
        )
    found: list[str] = []
    if runs:
        found.append(f"orchestration.runs holds {runs} run(s) of the old release check")
    if versions:
        found.append(
            f"builder.use_case_versions holds {versions} version(s) of the old {OLD_TEMPLATE} "
            "template"
        )
    return found


def _count_if_table_exists(
    conn: psycopg.Connection[Any], table: LiteralString, where: LiteralString, value: str
) -> int:
    exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()
    if exists is None or not exists[0]:
        return 0
    row = conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", (value,)).fetchone()
    return 0 if row is None else int(row[0])


def previous_hashes(owner_url: str) -> dict[str, str]:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT workflows FROM orchestration.engine_status WHERE id = 1"
        ).fetchone()
    if row is None:
        return {}
    workflows: list[dict[str, str]] = row[0]
    return {w["name"]: w["sha256"] for w in workflows}


def record_status(
    owner_url: str, *, ready: bool, detail: str, workflows: list[LoadedWorkflow]
) -> None:
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO orchestration.engine_status (id, loaded_at, ready, detail, workflows) "
            "VALUES (1, now(), %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET loaded_at = EXCLUDED.loaded_at, "
            "ready = EXCLUDED.ready, detail = EXCLUDED.detail, workflows = EXCLUDED.workflows",
            (ready, detail, Jsonb([asdict(w) for w in workflows])),
        )


if __name__ == "__main__":
    sys.exit(main())
