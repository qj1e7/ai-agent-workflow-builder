import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

import httpx
import psycopg
from psycopg.types.json import Jsonb

from platform_api.auth import ConfigError
from platform_api.migrations import upgrade_all
from platform_api.orchestration.n8n import N8nClient, N8nError
from platform_api.orchestration.workflows import (
    Finding,
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
    upgrade_all(settings.owner_database_url)
    say("database migrations are at head")
    definitions = load_all()
    findings = lint(definitions)
    if findings:
        return _finish(settings, say, [], findings, "the workflow files fail the lint")
    try:
        loaded, findings = load_into_n8n(settings, definitions, say)
    except (N8nError, httpx.HTTPError) as error:
        return _finish(settings, say, [], [], f"could not load the workflows into n8n: {error}")
    inactive = [w.name for w in loaded if not w.active]
    if inactive:
        return _finish(settings, say, loaded, findings, f"inactive in n8n: {', '.join(inactive)}")
    if findings:
        return _finish(settings, say, loaded, findings, "the live workflows fail the lint")
    return _finish(settings, say, loaded, [], "all workflows loaded, active and linted")


def _finish(
    settings: BootstrapSettings,
    say: Say,
    loaded: list[LoadedWorkflow],
    findings: list[Finding],
    detail: str,
) -> int:
    for finding in findings:
        say(str(finding))
    ready = not findings and bool(loaded)
    record_status(settings.owner_database_url, ready=ready, detail=detail, workflows=loaded)
    say(f"{'ready' if ready else 'NOT ready'}: {detail}")
    return 0 if ready else 1


def load_into_n8n(
    settings: BootstrapSettings, definitions: tuple[WorkflowDefinition, ...], say: Say
) -> tuple[list[LoadedWorkflow], list[Finding]]:
    error_workflow = next(d for d in definitions if d.is_error_workflow)
    run_workflows = [d for d in definitions if not d.is_error_workflow]
    previous = previous_hashes(settings.owner_database_url)
    client = N8nClient(settings.n8n_base_url)
    try:
        client.wait_healthy()
        say("n8n is healthy")
        owner = client.ensure_owner(settings.n8n_owner_email, settings.n8n_owner_password)
        say(f"owner {settings.n8n_owner_email}: {owner.value}")
        removed = client.fresh_api_key(API_KEY_LABEL)
        say(f"api key '{API_KEY_LABEL}': created, {removed} older removed")
        credential_id = client.create_header_credential(
            CREDENTIAL_NAME, STEP_KEY_HEADER, settings.step_key
        )
        say(f"credential '{CREDENTIAL_NAME}': created {credential_id}")
        values = {
            "PLATFORM_INTERNAL_URL": settings.platform_internal_url,
            "STEP_KEY_CREDENTIAL_ID": credential_id,
        }
        error_id, error_hash = _load(client, error_workflow, values, previous, say)
        values["ERROR_WORKFLOW_ID"] = error_id
        hashes = {error_id: error_hash}
        for d in run_workflows:
            workflow_id, digest = _load(client, d, values, previous, say)
            hashes[workflow_id] = digest
        stale = [c for c in client.credentials_named(CREDENTIAL_NAME) if c != credential_id]
        for credential in stale:
            client.delete_credential(credential)
        if stale:
            say(f"credential '{CREDENTIAL_NAME}': removed {len(stale)} older")
        records = [client.read_back(workflow_id) for workflow_id in hashes]
    finally:
        client.close()
    live = LiveState(
        settings.platform_internal_url,
        {r.name: LiveWorkflow(r.id, r.active) for r in records},
    )
    findings = lint((parse(r.document) for r in records), live=live)
    loaded = [LoadedWorkflow(r.name, r.id, r.active, hashes[r.id]) for r in records]
    return loaded, findings


def _load(
    client: N8nClient,
    definition: WorkflowDefinition,
    values: Mapping[str, str],
    previous: Mapping[str, str],
    say: Say,
) -> tuple[str, str]:
    body = render(definition, values)
    digest = content_hash_without_credential(definition, values)
    result = client.upsert_workflow(body)
    if result.created:
        change = "created"
    elif previous.get(definition.name) == digest:
        change = "updated in place, same content as last bootstrap"
    else:
        change = "updated in place, content changed"
    say(f"workflow {definition.name} ({result.id}): {change}")
    return result.id, digest


def content_hash_without_credential(
    definition: WorkflowDefinition, values: Mapping[str, str]
) -> str:
    masked = render(definition, {**values, "STEP_KEY_CREDENTIAL_ID": "<masked>"})
    canonical = json.dumps(masked, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
