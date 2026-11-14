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
    expected_version_id: str,
    document: Mapping[str, Any],
    live: bool,
) -> Written | ChangedInN8n | N8nNotReady:
    try:
        return await n8n.change(workflow_id, expected_version_id, document, live)
    except (N8nError, httpx.HTTPError) as error:
        log.warning("n8n did not take the change to %s: %s", workflow_id, error)
        if live:
            await put_back(n8n, workflow_id, expected_version_id)
        return N8nNotReady("n8n did not take the change. Nothing changed. Try again.")


async def put_back(n8n: N8nDrafts, workflow_id: str, version_id: str) -> None:
    try:
        await n8n.go_live(workflow_id, version_id)
    except (N8nError, httpx.HTTPError) as error:
        log.error("could not put %s version %s back in n8n: %s", workflow_id, version_id, error)
