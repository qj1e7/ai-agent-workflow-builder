"""How our API starts a run of a use case's own n8n workflow, and how it asks n8n to retry one
(ENGINE-PLAN 2.3.2, 2.3.3 and 2.3.10).

Each start names a nonce our API issued for exactly one pending run. Run now sends it signed to
the workflow's Start from the Portal trigger, which n8n runs as mode webhook. A test run hands it
to n8n's run of the draft as the trigger's output, so the draft runs without being published. The
first block's call links the execution to the run by that nonce (2.3), never by the start alone.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

from platform_api.db import Database
from platform_api.orchestration.dispatch import DispatchFailure
from platform_api.orchestration.n8n import N8nApi, N8nError, RetryRefused, StillRetrying
from platform_api.orchestration.n8n_call_book import CallBook
from platform_api.orchestration.n8n_calls import StartKind, start_signature
from platform_api.orchestration.spec import N8nTarget
from platform_api.shared import N8nExecutionId, RunId


@dataclass(frozen=True)
class SignedStart:
    """What the Portal's start sends to the trigger: the body, and its X-Wab-Signature."""

    body: Mapping[str, str | int]
    signature: str


async def issue_start(
    db: Database,
    secret: str,
    run_id: RunId,
    kind: StartKind,
    workflow_id: str,
    webhook_id: str,
) -> SignedStart:
    """A start for one pending run of one workflow, signed for that workflow's trigger."""
    async with db.transaction("orchestration") as uow:
        start = await CallBook().issue_start(uow, run_id, kind, workflow_id)
    expires = int(start.expires_at.timestamp())
    signature = start_signature(secret, workflow_id, webhook_id, start.nonce, kind, expires)
    return SignedStart({"nonce": start.nonce, "kind": kind, "expires": expires}, signature)


def _words(error: Exception) -> str:
    """n8n's own words, or only the kind of a transport error, which may name an address."""
    return str(error) if isinstance(error, N8nError) else type(error).__name__


class RunStarts(Protocol):
    """Where the orchestrator's outbox starts and retries the runs of own n8n workflows."""

    async def start(
        self, run_id: RunId, target: N8nTarget, kind: StartKind
    ) -> N8nExecutionId | None:
        """The execution of a test run, which n8n names at once. None for a start sent to the
        trigger, whose execution the first block's call names. Raises DispatchFailure when n8n
        did not take it, to be tried again with a new nonce."""
        ...

    async def retry(self, execution_id: N8nExecutionId, workflow_id: str) -> RetryRefused | None:
        """None once n8n shows a retry of the execution. Raises DispatchFailure when n8n could
        not be asked, or has not shown one yet, to be tried again."""
        ...


class N8nStarts:
    def __init__(
        self,
        db: Database,
        api: N8nApi,
        base_url: str,
        start_secret: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._db = db
        self._api = api
        self._base_url = base_url.rstrip("/")
        self._secret = start_secret
        self._client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)

    async def start(
        self, run_id: RunId, target: N8nTarget, kind: StartKind
    ) -> N8nExecutionId | None:
        if kind == "test":
            return await self._run_draft(run_id, target)
        if self._secret is None:
            raise DispatchFailure("WAB_START_SECRET is not set, so no start can be signed")
        if target.webhook_id is None:
            raise DispatchFailure("the workflow has no Start from the Portal block to start it")
        signed = await issue_start(
            self._db, self._secret, run_id, kind, target.workflow_id, target.webhook_id
        )
        url = f"{self._base_url}/webhook/{target.webhook_id}/start"
        try:
            response = await self._client.post(
                url, json=dict(signed.body), headers={"X-Wab-Signature": signed.signature}
            )
        except httpx.HTTPError as error:
            raise DispatchFailure(f"n8n did not answer the start: {_words(error)}") from None
        if response.status_code != 200:
            raise DispatchFailure(f"n8n answered the start with {response.status_code}")
        return None

    async def _run_draft(self, run_id: RunId, target: N8nTarget) -> N8nExecutionId:
        """The draft runs by hand, with the start item as the trigger's output (P7 Q3). It needs
        no signature: n8n never runs the trigger's own check, and our API checks the nonce."""
        async with self._db.transaction("orchestration") as uow:
            start = await CallBook().issue_start(uow, run_id, "test", target.workflow_id)
        item = {"nonce": start.nonce, "kind": "test", "workflow_id": target.workflow_id}
        try:
            return N8nExecutionId(await self._api.run_draft(target.workflow_id, item))
        except (N8nError, httpx.HTTPError) as error:
            raise DispatchFailure(f"n8n did not run the draft: {_words(error)}") from None

    async def retry(self, execution_id: N8nExecutionId, workflow_id: str) -> RetryRefused | None:
        """A retry n8n did not answer in time counts only once n8n lists it, so a refusal n8n
        gave slowly never reads as taken. A try that finds one listed already asks n8n nothing,
        so a slow retry is never sent twice."""
        try:
            if await self._retried(execution_id, workflow_id):
                return None
            answer = await self._api.retry(execution_id)
            if not isinstance(answer, StillRetrying):
                return answer
            if await self._retried(execution_id, workflow_id):
                return None
        except (N8nError, httpx.HTTPError) as error:
            raise DispatchFailure(f"n8n did not answer the retry: {_words(error)}") from None
        raise DispatchFailure("n8n did not answer the retry in time and lists no retry of it")

    async def _retried(self, execution_id: N8nExecutionId, workflow_id: str) -> bool:
        listed = await self._api.executions(workflow_id)
        return any(record.retry_of == execution_id for record in listed)

    async def close(self) -> None:
        await self._client.aclose()
