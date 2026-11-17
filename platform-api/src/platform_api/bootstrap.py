import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, LiteralString

import httpx
import psycopg
from psycopg.types.json import Jsonb

from platform_api.auth import ConfigError
from platform_api.migrations import upgrade_all
from platform_api.n8n_guard import (
    DEPRECATED,
    PROBED,
    deployed_findings,
    deprecated_probe,
    loaded_findings,
    shown_findings,
)
from platform_api.orchestration.n8n import PLATFORM_API_KEY_LABEL, N8nClient, N8nError
from platform_api.orchestration.workflow_check import (
    ERROR_WORKFLOW,
    SELF_TEST,
    check_platform,
    platform_document,
)
from platform_api.settings import BootstrapSettings, bootstrap_settings_from_env

API_KEY_LABEL = "platform-bootstrap"
CREDENTIAL_NAME = "X-Step-Key"
# Only this exact name is removed: staff build their own workflows in the same n8n (ADR 0027).
OLD_RUN_WORKFLOW = "release_check"
OLD_TEMPLATE = "release_check"
OLD_TASK_KIND = "release"
RETIRED_WORKFLOWS = ("schedule_tick", "run")
"""Removed by these exact names, as they are the platform's own. Nothing ticks schedules since
E10: each workflow's own n8n workflow has its Schedule Trigger. The shared run workflow is made of
Webhook, HTTP Request and Respond to Webhook blocks, which the class file doesn't let run (E11), and
platform-api ends any run still on it as it starts."""
GUARDS_FAIL = "n8n's blocks or settings fail the check"
RESET_HINT = (
    "This stack holds data from before the release check was retired, which the platform can "
    "no longer read. Reset a local practice stack with "
    "`docker compose -p <project> -f deploy/compose.yaml down -v`, then start it again."
)

type Say = Callable[[str], None]


@dataclass(frozen=True)
class N8nLoad:
    """What bootstrap did to n8n and found there."""

    workflows: list[LoadedWorkflow]
    findings: list[str]
    """Where the platform's own workflows are out of place or fail the lint."""
    guards: list[str] = field(default_factory=list[str])
    """Where n8n's blocks or settings let a workflow's code or files reach n8n's secrets
    (`platform_api.n8n_guard`)."""
    version: str | None = None
    """The n8n version n8n says it runs."""


@dataclass(frozen=True)
class LoadedWorkflow:
    name: str
    id: str
    active: bool
    sha256: str
    project: str | None = None


class NotThePlatforms(Exception):
    """Bootstrap cannot tell which n8n workflow is the platform's own. The words name workflows
    and ids only."""


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
    try:
        load = load_into_n8n(settings, say)
    except NotThePlatforms as error:
        return _finish(settings, say, [], [], str(error))
    except (N8nError, httpx.HTTPError) as error:
        say(f"could not load the workflows into n8n: {error}")
        detail = _detail_without_message("could not load the workflows into n8n", error)
        return _finish(settings, say, [], [], detail)
    loaded, findings = load.workflows, [*load.guards, *load.findings]
    inactive = [w.name for w in loaded if not w.active]
    if load.guards:
        detail = GUARDS_FAIL
    elif inactive:
        detail = f"inactive in n8n: {', '.join(inactive)}"
    elif findings:
        detail = "the live workflows fail the lint"
    else:
        detail = "all workflows loaded, active and linted"
    return _finish(settings, say, loaded, findings, detail, load.version)


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
    n8n_version: str | None = None,
) -> int:
    for finding in findings:
        say(finding)
    ready = not findings and bool(loaded)
    record_status(
        settings.owner_database_url,
        ready=ready,
        detail=detail,
        workflows=loaded,
        n8n_version=n8n_version,
    )
    say(f"{'ready' if ready else 'NOT ready'}: {detail}")
    return 0 if ready else 1


def load_into_n8n(settings: BootstrapSettings, say: Say) -> N8nLoad:
    previous = _previous(settings.owner_database_url)
    recorded = {w["name"]: w["id"] for w in previous}
    client = N8nClient(settings.n8n_base_url)
    try:
        client.wait_healthy()
        say("n8n is healthy")
        owner = client.ensure_owner(settings.n8n_owner_email, settings.n8n_owner_password)
        say(f"owner {settings.n8n_owner_email}: {owner.value}")
        loaded_types = client.node_types()
        say(f"n8n loads {len(loaded_types)} node types")
        shown = client.settings()
        version = str(shown.get("versionCli") or "") or None
        say(f"n8n runs version {version or 'unknown'}")
        removed = client.fresh_api_key(API_KEY_LABEL)
        say(f"api key '{API_KEY_LABEL}': created, {removed} older removed")
        took = [t for t in DEPRECATED if client.runs_by_hand(deprecated_probe(t), PROBED)]
        lost = lost_workflows(client, settings.owner_database_url, recorded, say)
        if lost is not None:
            ask_for_restore(settings.owner_database_url, lost, say)
        removed = client.remove_api_keys(PLATFORM_API_KEY_LABEL)
        say(f"api key '{PLATFORM_API_KEY_LABEL}': {removed} removed, platform-api makes its own")
        place = Place(
            client,
            client.platform_project(),
            recorded,
            {w["name"]: w["sha256"] for w in previous},
            say,
        )
        platform = load_platform_workflows(place, settings.team_time_zone.key)
        for old in client.workflows_named(OLD_RUN_WORKFLOW):
            if old.project == place.project:
                client.delete_workflow(old.id)
                say(f"workflow {OLD_RUN_WORKFLOW} ({old.id}): removed")
        retire_old_engine(place)
        stale = client.credentials_named(CREDENTIAL_NAME)
        for credential in stale:
            client.delete_credential(credential)
        if stale:
            say(f"credential '{CREDENTIAL_NAME}': removed {len(stale)}")
    finally:
        client.close()
    findings = [
        *platform.findings,
        *(
            f"{w.name} ({w.id}) is not in the platform's n8n project"
            for w in platform.loaded
            if w.project != place.project
        ),
    ]
    guards = [
        *loaded_findings(loaded_types),
        *deployed_findings(settings.n8n_settings),
        *shown_findings(shown),
        *(
            f"n8n runs a workflow with {t} by hand, which NODES_EXCLUDE must leave out, and "
            "which runs code in n8n's own process"
            for t in took
        ),
    ]
    return N8nLoad(platform.loaded, findings, guards, version)


@dataclass(frozen=True)
class Place:
    """The owner's own n8n project, where the platform keeps its workflows, and what the last
    bootstrap recorded of them."""

    client: N8nClient
    project: str
    recorded: Mapping[str, str]
    """Each workflow's id, by name."""
    hashes: Mapping[str, str]
    say: Say

    def target(self, name: str) -> str | None:
        """The workflow this name is the platform's for: the one recorded, else the only one of
        that name in the platform's project, else none yet. A workflow of that name in a
        member's project is never it."""
        recorded = self.recorded.get(name)
        held = None if recorded is None else self.client.workflow(recorded)
        if held is not None and held.project != self.project:
            raise NotThePlatforms(f"{name} ({held.id}) is no longer in the platform's n8n project")
        if held is not None:
            return held.id
        named = self.client.workflows_named(name)
        for unplaced in (w for w in named if w.project is None):
            raise NotThePlatforms(
                f"n8n listed {name} ({unplaced.id}) without its project, so bootstrap cannot tell "
                "whose it is"
            )
        ours = [w.id for w in named if w.project == self.project]
        if len(ours) > 1:
            raise NotThePlatforms(
                f"{len(ours)} workflows named {name} are in the platform's n8n project: "
                f"{', '.join(ours)}"
            )
        return ours[0] if ours else None


@dataclass(frozen=True)
class PlatformLoaded:
    error_workflow: str
    loaded: list[LoadedWorkflow]
    findings: list[str]


def load_platform_workflows(place: Place, time_zone: str) -> PlatformLoaded:
    """The platform's own n8n workflows, each made active (ENGINE-PLAN 2.8): the error workflow
    first, then the daily self-test, whose failures go to it and which runs on the team time zone.
    Each is checked as n8n holds it."""
    error = platform_document(ERROR_WORKFLOW, None, time_zone)
    error_id = _upsert(place, error, _content_hash(error))
    self_test = platform_document(SELF_TEST, error_id, time_zone)
    self_test_id = _upsert(place, self_test, _content_hash(self_test))
    loaded: list[LoadedWorkflow] = []
    findings: list[str] = []
    for workflow_id, body in ((error_id, error), (self_test_id, self_test)):
        record = place.client.read_back(workflow_id)
        digest = _content_hash(body)
        loaded.append(LoadedWorkflow(record.name, record.id, record.active, digest, record.project))
        checked = check_platform(record.document, error_id, time_zone)
        findings += [f"{record.name}: {f.text}" for f in checked]
    return PlatformLoaded(error_id, loaded, findings)


def _upsert(place: Place, body: dict[str, Any], digest: str) -> str:
    name = str(body["name"])
    result = place.client.save_workflow(body, place.target(name))
    if result.created:
        change = "created"
    elif place.hashes.get(name) == digest:
        change = "updated in place, same content as last bootstrap"
    else:
        change = "updated in place, content changed"
    place.say(f"workflow {name} ({result.id}): {change}")
    return result.id


def retire_old_engine(place: Place) -> None:
    """The schedule tick and the shared run workflow go. Each is found as the platform finds its
    own, by the id recorded, in the platform's n8n project, so a workflow staff named the same
    stays. A run left behind by a delete that failed is no longer on record: the release that
    removes the old engine's code removes it by name and content hash."""
    for name in RETIRED_WORKFLOWS:
        workflow_id = place.target(name)
        if workflow_id is not None:
            place.client.delete_workflow(workflow_id)
            place.say(f"workflow {name} ({workflow_id}): removed, every workflow runs as its own")


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


def previous_hashes(owner_url: str) -> dict[str, str]:
    return {w["name"]: w["sha256"] for w in _previous(owner_url)}


def _previous(owner_url: str) -> list[dict[str, str]]:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT workflows FROM orchestration.engine_status WHERE id = 1"
        ).fetchone()
    return [] if row is None else row[0]


def record_status(
    owner_url: str,
    *,
    ready: bool,
    detail: str,
    workflows: list[LoadedWorkflow],
    n8n_version: str | None = None,
) -> None:
    """A bootstrap that loaded nothing keeps the workflows the last one recorded, so the next
    bootstrap still knows the platform's own by id. platform-api trusts them only while ready.
    One that could not read n8n's version keeps the last one too, and writes no version at all,
    as a bootstrap that stopped before the migrations can't."""
    workflows_json = Jsonb([asdict(w) for w in workflows])
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO orchestration.engine_status (id, loaded_at, ready, detail, workflows) "
            "VALUES (1, now(), %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET loaded_at = EXCLUDED.loaded_at, "
            "ready = EXCLUDED.ready, detail = EXCLUDED.detail, workflows = CASE "
            "WHEN EXCLUDED.workflows = '[]'::jsonb THEN orchestration.engine_status.workflows "
            "ELSE EXCLUDED.workflows END",
            (ready, detail, workflows_json),
        )
        if n8n_version is not None:
            conn.execute(
                "UPDATE orchestration.engine_status SET n8n_version = %s WHERE id = 1",
                (n8n_version,),
            )


if __name__ == "__main__":
    sys.exit(main())
