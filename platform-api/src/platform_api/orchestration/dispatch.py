import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, NewType, Protocol
from urllib.parse import urlsplit

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
    """How long a tick holds an outbox row, so another replica does not send it too. Each row's
    lease is renewed just before it is sent, and one send takes far less: every client's
    timeout is 10 seconds. A row a stopped replica held is sent once its lease runs out."""
    batch: int = 10
    """The most rows one tick takes, so a tick with a slow Teams does not hold many for long."""

    @property
    def tries(self) -> int:
        return len(self.delays) + 1

    @property
    def dispatch_budget(self) -> timedelta:
        return sum(self.delays, timedelta()) + self.tick_interval * self.tries


RETRY_POLICY = RetryPolicy()


@dataclass(frozen=True)
class WakePolicy:
    """A wake waits for n8n longer than other sends, so an n8n outage never loses a yes
    (ENGINE-PLAN 2.4). After a day the run is lost."""

    delays: tuple[timedelta, ...] = RETRY_POLICY.delays
    then_every: timedelta = timedelta(minutes=5)
    give_up_after: timedelta = timedelta(hours=24)

    def next_try(self, failures: int, first_at: datetime, now: datetime) -> datetime | None:
        """When to try again after this many failed tries, or None to give up."""
        if now - first_at >= self.give_up_after:
            return None
        delay = self.delays[failures - 1] if failures <= len(self.delays) else self.then_every
        return now + delay


WAKE_POLICY = WakePolicy()

type WakeDecision = Literal["yes", "no", "no_answer"]


def wake_mac(
    node_key: str, execution: N8nExecutionId, request: ApprovalId, decision: WakeDecision
) -> str:
    """The mac Ask for a yes checks: HMAC-SHA256 with WAB_NODE_KEY over the execution id, our
    request id and the decision, one per line (n8n-node-pack/README.md)."""
    message = "\n".join((execution, request, decision))
    return hmac.new(node_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def resume_path(url: str, execution: N8nExecutionId) -> str | None:
    """The path and query of n8n's resume address for this execution, or None when the address
    is not one. Only these go to n8n, at our own address for it, so no node call can point a
    wake anywhere else."""
    parts = urlsplit(url)
    path = f"/webhook-waiting/{execution}"
    if parts.scheme not in ("http", "https") or not parts.path.endswith(path):
        return None
    return f"{path}?{parts.query}" if parts.query else path


@dataclass(frozen=True)
class HeldWait:
    """A waiting n8n execution, and the resume address it gave, sealed at rest because its
    query holds n8n's signature."""

    execution_id: N8nExecutionId
    sealed_url: str


@dataclass(frozen=True)
class Delivered:
    pass


@dataclass(frozen=True)
class Gone:
    """n8n answered 409, because something else resumed the execution or it has finished."""


type WakeAnswer = Delivered | Gone


class Waker(Protocol):
    async def wake(
        self, held: HeldWait, request_id: ApprovalId, decision: WakeDecision
    ) -> WakeAnswer:
        """Raises DispatchFailure when n8n did not take it, to be tried again."""
        ...


class WakeLanding(Protocol):
    async def landed(self, execution_id: N8nExecutionId) -> bool:
        """Whether n8n shows the execution running or finished."""
        ...


class Sealer(Protocol):
    def seal(self, key: str) -> str: ...

    def open(self, sealed: str) -> str | None: ...


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
    owner_name: str = ""


Identity = NewType("Identity", str)
PRACTICE: Final = Identity("practice")


def identity_of(adapter: str, *parts: str) -> Identity:
    fingerprint = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]
    return Identity(f"{adapter}:{fingerprint}")


@dataclass(frozen=True)
class MessageRef:
    channel: str
    id: str
    identity: Identity


type OutcomeVerdict = Literal["approved", "declined"]


@dataclass(frozen=True)
class ApprovalOutcome:
    verdict: OutcomeVerdict
    by: tuple[str, ...]
    use_case_name: str
    open_url: str
    approved_first: tuple[str, ...] = ()
    """On a decline, who said yes to the steps before it, in step order."""
    reason: str | None = None
    """On a decline, the reason the Approver gave, if any."""


class ApprovalChannel(Protocol):
    """Teams, or its practice copy. An adapter raises DispatchFailure when the post fails."""

    @property
    def name(self) -> str: ...

    @property
    def identity(self) -> Identity: ...

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


class N8nWaker:
    """Sends a decision to the execution that waits for it. Its errors name no address, because
    the resume address carries n8n's signature."""

    def __init__(
        self,
        base_url: str,
        node_key: str,
        box: Sealer,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._node_key = node_key
        self._box = box
        self._client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)

    async def wake(
        self, held: HeldWait, request_id: ApprovalId, decision: WakeDecision
    ) -> WakeAnswer:
        url = self._box.open(held.sealed_url)
        path = None if url is None else resume_path(url, held.execution_id)
        if path is None:
            raise DispatchFailure("the resume address could not be opened")
        mac = wake_mac(self._node_key, held.execution_id, request_id, decision)
        body = {
            "execution_id": held.execution_id,
            "request_id": request_id,
            "decision": decision,
            "mac": mac,
        }
        try:
            response = await self._client.post(f"{self._base_url}{path}", json=body)
        except httpx.HTTPError as error:
            raise DispatchFailure(f"n8n did not answer the wake ({type(error).__name__})") from None
        if response.status_code == 409:
            return Gone()
        if not 200 <= response.status_code < 300:
            raise DispatchFailure(f"n8n answered the wake with {response.status_code}")
        return Delivered()

    async def close(self) -> None:
        await self._client.aclose()
