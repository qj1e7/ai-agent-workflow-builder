"""A platform write to a use case's own n8n workflow, under the version compare (ENGINE-PLAN 2.5).
A write n8n did not finish puts the stored version back live, so n8n runs what the records say."""

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from platform_api.builder.n8n_draft import N8nNotReady
from platform_api.orchestration import ChangedInN8n, N8nDrafts, N8nError, Written

log = logging.getLogger(__name__)


async def write_in_n8n(
    n8n: N8nDrafts,
    workflow_id: str,
    expected_draft: str,
    in_use: str,
    document: Mapping[str, Any],
    live: bool,
) -> Written | ChangedInN8n | N8nNotReady:
    """`expected_draft` is n8n's draft as the platform last saw it, which the compare checks.
    `in_use` is the version the records hold live, put back when a live write did not finish. They
    differ once an earlier version was published again, which leaves the draft where it was."""
    try:
        return await n8n.change(workflow_id, expected_draft, document, live)
    except (N8nError, httpx.HTTPError) as error:
        log.warning("n8n did not take the change to %s: %s", workflow_id, error)
        if live:
            await put_back(n8n, workflow_id, in_use)
        return N8nNotReady("n8n did not take the change. Nothing changed. Try again.")


async def put_back(n8n: N8nDrafts, workflow_id: str, version_id: str) -> None:
    try:
        await n8n.go_live(workflow_id, version_id)
    except (N8nError, httpx.HTTPError) as error:
        log.error("could not put %s version %s back in n8n: %s", workflow_id, version_id, error)


async def discard(n8n: N8nDrafts, workflow_id: str) -> None:
    """A workflow the records never came to name is taken off and removed, so it never runs. n8n
    keeps a published workflow, so it is taken off first."""
    try:
        await n8n.go_off(workflow_id)
    except (N8nError, httpx.HTTPError) as error:
        log.warning("could not take %s off in n8n: %s", workflow_id, error)
    await n8n.remove(workflow_id)
