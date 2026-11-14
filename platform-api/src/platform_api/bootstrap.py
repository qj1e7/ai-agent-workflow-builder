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
from platform_api.orchestration.workflows import (
    Finding,
    LiveState,
    LiveWorkflow,
    WorkflowDefinition,
    lint,
    load_all,
    parse,
    placeholders,
    render,
)
from platform_api.settings import BootstrapSettings, bootstrap_settings_from_env

API_KEY_LABEL = "platform-bootstrap"
CREDENTIAL_NAME = "X-Step-Key"
STEP_KEY_HEADER = "X-Step-Key"
CREDENTIAL_PLACEHOLDER = "STEP_KEY_CREDENTIAL_ID"
# Only this exact name is removed: staff build their own workflows in the same n8n (ADR 0027).
OLD_RUN_WORKFLOW = "release_check"
OLD_TEMPLATE = "release_check"
OLD_TASK_KIND = "release"
SHARED_RUN_WORKFLOW = "run"
RETIRED_WORKFLOWS = ("schedule_tick",)
"""Removed by these exact names, as they are the platform's own. Nothing ticks schedules since
E10: each workflow's own n8n workflow has its Schedule Trigger."""
OLD_ENGINE_IN_USE = """
    SELECT EXISTS (
        SELECT 1 FROM builder.use_cases WHERE engine = 'shared_run' AND deleted_at IS NULL
    ) OR EXISTS (
        SELECT 1 FROM orchestration.runs
        WHERE jsonb_typeof(spec -> 'n8n') IS DISTINCT FROM 'object'
          AND state IN ('Pending', 'Working', 'Proposed', 'AwaitingApproval', 'Acting')
    )
"""
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
    findings = lint(definitions)
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
    in_use = old_engine_in_use(settings.owner_database_url)
    error_workflow = next(d for d in definitions if d.is_error_workflow)
    other_workflows = [
        d
        for d in definitions
        if not d.is_error_workflow and (in_use or d.name != SHARED_RUN_WORKFLOW)
    ]
    previous = previous_hashes(settings.owner_database_url)
    recorded = recorded_ids(settings.owner_database_url)
    client = N8nClient(settings.n8n_base_url)
    try:
        client.wait_healthy()
        say("n8n is healthy")
        owner = client.ensure_owner(settings.n8n_owner_email, settings.n8n_owner_password)
        say(f"owner {settings.n8n_owner_email}: {owner.value}")
        removed = client.fresh_api_key(API_KEY_LABEL)
        say(f"api key '{API_KEY_LABEL}': created, {removed} older removed")
        lost = lost_workflows(client, settings.owner_database_url, recorded, say)
        if lost is not None:
            ask_for_restore(settings.owner_database_url, lost, say)
        removed = client.remove_api_keys(PLATFORM_API_KEY_LABEL)
        say(f"api key '{PLATFORM_API_KEY_LABEL}': {removed} removed, platform-api makes its own")
        values = {"PLATFORM_INTERNAL_URL": settings.platform_internal_url}
        credential_id = None
        if any(_needs_step_key(d) for d in (error_workflow, *other_workflows)):
            credential_id = client.create_header_credential(
                CREDENTIAL_NAME, STEP_KEY_HEADER, settings.step_key
            )
            say(f"credential '{CREDENTIAL_NAME}': created {credential_id}")
            values[CREDENTIAL_PLACEHOLDER] = credential_id
        error_id, error_hash = _load(client, error_workflow, values, previous, say)
        values["ERROR_WORKFLOW_ID"] = error_id
        hashes = {error_id: error_hash}
        for d in other_workflows:
            workflow_id, digest = _load(client, d, values, previous, say)
            hashes[workflow_id] = digest
        old = client.find_workflow(OLD_RUN_WORKFLOW)
        if old is not None:
            client.delete_workflow(old.id)
            say(f"workflow {OLD_RUN_WORKFLOW} ({old.id}): removed, every run now goes through run")
        retire_old_engine(client, recorded, in_use, say)
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


def old_engine_in_use(owner_url: str) -> bool:
    """A workflow still on the shared run workflow, or a run of it that has not ended, still needs
    that workflow and its step key. Once neither is left, nothing calls them (ENGINE-PLAN E10)."""
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(OLD_ENGINE_IN_USE).fetchone()
    assert row is not None
    return bool(row[0])


def retire_old_engine(
    client: N8nClient, recorded: Mapping[str, str], in_use: bool, say: Say
) -> None:
    """The schedule tick goes at once. The shared run workflow goes once nothing runs on it, so an
    old deploy's waiting run still finishes there first. Each goes by the id bootstrap recorded
    when it loaded it, never by its name alone, so a workflow staff named the same stays. A run
    left behind by a delete that failed is no longer on record: the release that removes the old
    engine's code removes it by name and content hash."""
    for name in (*RETIRED_WORKFLOWS, *(() if in_use else (SHARED_RUN_WORKFLOW,))):
        workflow_id = recorded.get(name)
        if workflow_id is None:
            continue
        try:
            held = client.read_back(workflow_id)
        except N8nError:
            continue
        if held.name == name:
            client.delete_workflow(workflow_id)
            say(f"workflow {name} ({workflow_id}): removed, every workflow runs as its own in n8n")


def _needs_step_key(definition: WorkflowDefinition) -> bool:
    return CREDENTIAL_PLACEHOLDER in placeholders(definition)


def content_hash_without_credential(
    definition: WorkflowDefinition, values: Mapping[str, str]
) -> str:
    masked = render(definition, {**values, CREDENTIAL_PLACEHOLDER: "<masked>"})
    canonical = json.dumps(masked, sort_keys=True, separators=(",", ":"))
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


OWN_WORKFLOWS = """
    SELECT n8n_workflow_id FROM builder.use_cases
    WHERE engine = 'own' AND n8n_workflow_id IS NOT NULL AND deleted_at IS NULL
      AND deleted_in_n8n_at IS NULL
"""


def lost_workflows(
    client: N8nClient, owner_url: str, recorded: Mapping[str, str], say: Say
) -> list[str] | None:
    """The workflows n8n lost when our records name workflows and n8n holds none of them: its
    database is gone, whatever its owner says, as n8n on Azure makes its owner from its settings
    at every start. None when nothing is lost: before n8n ever held one, while it holds any, and
    while it cannot answer, which is never taken for empty."""
    with psycopg.connect(owner_url) as conn:
        own = [row[0] for row in conn.execute(OWN_WORKFLOWS).fetchall()]
    named = [*recorded.values(), *own]
    if not named:
        return None
    try:
        if any(client.holds(workflow_id) for workflow_id in named):
            return None
    except (N8nError, httpx.HTTPError) as error:
        say(f"could not tell whether n8n kept its workflows, so nothing is restored: {error}")
        return None
    return own


def ask_for_restore(owner_url: str, missing: Sequence[str], say: Say) -> None:
    """n8n holds none of the workflows it held before, and platform-api saves each one again
    from the version it kept (Restore to n8n) as it starts. The ask names the use cases'
    workflows that were missing, so the sweep takes none of those for deleted meanwhile."""
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO builder.n8n_restore (id, asked_at, missing) VALUES (1, now(), %s)"
            " ON CONFLICT (id) DO UPDATE SET asked_at = EXCLUDED.asked_at,"
            " missing = EXCLUDED.missing",
            (list(missing),),
        )
    say("n8n holds none of its workflows: platform-api restores the ones it kept as it starts")


def recorded_ids(owner_url: str) -> dict[str, str]:
    """Each workflow the last bootstrap loaded, by name."""
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT workflows FROM orchestration.engine_status WHERE id = 1"
        ).fetchone()
    workflows: list[dict[str, str]] = [] if row is None else row[0]
    return {w["name"]: w["id"] for w in workflows}


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
