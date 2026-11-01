import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol

import httpx

from platform_api.orchestration.runs import Leg
from platform_api.shared import ApprovalId, N8nExecutionId, RunId


@dataclass(frozen=True)
class RetryPolicy:
    delays: tuple[timedelta, ...] = (
        timedelta(seconds=2),
        timedelta(seconds=5),
        timedelta(seconds=15),
        timedelta(seconds=30),
        timedelta(seconds=60),
    )
    operator_retry_delay: timedelta = timedelta(seconds=3)
    tick_interval: timedelta = timedelta(seconds=5)
    lease: timedelta = timedelta(minutes=1)
    """How long a tick holds the outbox rows it took, so another replica does not send them too.
    Longer than any one send, and a row a stopped replica held is sent once it runs out."""

    @property
    def tries(self) -> int:
        return len(self.delays) + 1

    @property
    def dispatch_budget(self) -> timedelta:
        return sum(self.delays, timedelta()) + self.tick_interval * self.tries


RETRY_POLICY = RetryPolicy()


class DispatchFailure(Exception): ...


class WorkflowEngine(Protocol):
    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId: ...


@dataclass(frozen=True)
class AskedStep:
    """One approval step as the card says it: its label, and the names of who may decide it.
    No names means any Approver who is not a party to the run."""

    label: str
    who: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalNotice:
    """What the approval card shows, and nothing else, so no token or key can reach a channel.

    `actions` are the writes in one phrase each, for a sentence. `lines` are the writes one by
    one, as the approval page lists them, for the card. `link` is the approval page's path, for
    the activity log, and `open_url` the same page as an absolute address, for the card's button.
    `digest` is the proposal's digest: a bot that lets Approvers decide inside Teams sends it
    back with the decision, as the approval page does."""

    run_id: RunId
    approval_id: ApprovalId
    use_case_name: str
    actions: tuple[str, ...]
    link: str
    open_url: str
    summary: str = ""
    lines: tuple[str, ...] = ()
    digest: str = ""
    steps: tuple[AskedStep, ...] = ()
    not_deciding: tuple[str, ...] = ()


@dataclass(frozen=True)
class MessageRef:
    """Where an approval request was posted, and which adapter posted it, so the channel can
    show its outcome later, and only the adapter that posted it tries to."""

    channel: str
    id: str
    adapter: str


type OutcomeVerdict = Literal["approved", "declined"]


@dataclass(frozen=True)
class ApprovalOutcome:
    verdict: OutcomeVerdict
    by: tuple[str, ...]
    use_case_name: str
    open_url: str


class ApprovalChannel(Protocol):
    """Teams, or its practice copy. An adapter raises DispatchFailure when the post fails."""

    @property
    def name(self) -> str: ...

    @property
    def adapter(self) -> str:
        """Which adapter this is, such as "practice" or "teams_workflows"."""
        ...

    async def announce(self, notice: ApprovalNotice) -> MessageRef: ...

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None: ...


_ADDRESS = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


def without_addresses(text: str) -> str:
    """text with every web address hidden, for a log line. A webhook's address is a secret."""
    return _ADDRESS.sub("<address hidden>", text)


class N8nWebhooks:
    def __init__(
        self,
        base_url: str,
        path_for: Callable[[str, Leg], str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._path_for = path_for
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        url = f"{self._base_url}/webhook/{self._path_for(workflow, leg)}"
        try:
            response = await self._client.post(url, json={"run_id": run_id})
        except httpx.HTTPError as error:
            raise DispatchFailure(f"n8n did not answer at {url}: {error!r}") from error
        if response.status_code != 202:
            raise DispatchFailure(f"n8n answered {response.status_code} at {url}")
        try:
            execution = str(response.json()["n8n_execution_id"])
        except (ValueError, KeyError, TypeError) as error:
            raise DispatchFailure(f"n8n's 202 carried no execution id: {error!r}") from error
        if not execution:
            raise DispatchFailure("n8n's 202 carried an empty execution id")
        return N8nExecutionId(execution)

    async def close(self) -> None:
        await self._client.aclose()
