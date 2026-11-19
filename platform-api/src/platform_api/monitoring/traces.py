"""What the platform adds to the Planner's traces in Langfuse (ADR 0050): each typed turn's trace
id, the pseudonym that names the person, and the code flags the platform writes on a trace.

A flag is written only when it is true. Writing one never waits on Langfuse and never fails the
turn: a write that fails is logged by its kind, and the flag is lost.
"""

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol

import httpx

from platform_api.shared import UserId

log = logging.getLogger(__name__)

TYPED_AGAIN_WITHIN: Final = timedelta(seconds=60)
"""ADR 0050's flag_typed_again: the person sent another message in the same chat within 60 s,
measured from the earlier message to this one."""
SCORE_TIMEOUT_SECONDS: Final = 5.0
TRACE_ID: Final = re.compile(r"[0-9a-f]{32}")
TAG_MASK: Final = (1 << 62) - 1
EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

type FlagName = Literal["flag_typed_again"]


@dataclass(frozen=True)
class TraceFlag:
    """A code flag on one trace. `at` is when the trace was made, so the flag's score id and time
    are the same every time it is sent, and Langfuse updates the one score."""

    trace_id: str
    name: FlagName
    at: datetime

    @property
    def score_id(self) -> str:
        return f"{self.trace_id}-{self.name}"


class TraceIds:
    """Makes each typed turn's trace id, and tells whether an id was made for a given person.

    An id is a version 7 UUID. Its time is when the turn came in, and its last 62 bits are an
    HMAC of that time and the person. So a person can flag only their own earlier turn as typed
    again, never someone else's, and the platform keeps nothing to check it."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def new(self, person: UserId, now: datetime | None = None) -> str:
        made = now or datetime.now(UTC)
        ms = (made - EPOCH) // timedelta(milliseconds=1)
        rand_a = secrets.randbits(12)
        value = (
            (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | self._tag(person, ms, rand_a)
        )
        return uuid.UUID(int=value).hex

    def made_for(self, trace_id: str, person: UserId) -> datetime | None:
        """When the id was made, if the platform made it for this person. None otherwise."""
        if TRACE_ID.fullmatch(trace_id) is None:
            return None
        made = uuid.UUID(hex=trace_id)
        if made.version != 7 or made.variant != uuid.RFC_4122:
            return None
        ms, rand_a, tag = made.int >> 80, (made.int >> 64) & 0xFFF, made.int & TAG_MASK
        if not hmac.compare_digest(tag.to_bytes(8), self._tag(person, ms, rand_a).to_bytes(8)):
            return None
        return EPOCH + timedelta(milliseconds=ms)

    def _tag(self, person: UserId, ms: int, rand_a: int) -> int:
        signed = f"trace-id:{person}:{ms}:{rand_a}".encode()
        return int.from_bytes(hmac.new(self._key, signed, hashlib.sha256).digest()[:8]) & TAG_MASK


def pseudonym(key: str, person: UserId) -> str:
    """Names the person in a trace, never by their email or name."""
    return hmac.new(key.encode(), person.encode(), hashlib.sha256).hexdigest()


def typed_again(trace_id: str, now: datetime, ids: TraceIds, person: UserId) -> TraceFlag | None:
    """The flag for this person's earlier turn whose next message came at `now`, when that is
    within 60 s."""
    made = ids.made_for(trace_id, person)
    if made is None or not timedelta(0) <= now - made <= TYPED_AGAIN_WITHIN:
        return None
    return TraceFlag(trace_id=trace_id, name="flag_typed_again", at=made)


class TraceScores(Protocol):
    def send(self, flag: TraceFlag) -> None:
        """Starts the write and returns at once."""
        ...

    async def close(self) -> None:
        """Waits for the writes still under way."""
        ...


class NoTraceScores:
    """Tracing is off, so no flag goes anywhere."""

    def send(self, flag: TraceFlag) -> None:
        return None

    async def close(self) -> None:
        return None


class LangfuseScores:
    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        environment: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"{base_url}/api/public/scores"
        self._auth = httpx.BasicAuth(public_key, secret_key)
        self._environment = environment
        self._client = client or httpx.AsyncClient(timeout=SCORE_TIMEOUT_SECONDS)
        self._writes: set[asyncio.Task[None]] = set()

    def send(self, flag: TraceFlag) -> None:
        write = asyncio.create_task(self._write(flag))
        self._writes.add(write)
        write.add_done_callback(self._writes.discard)

    async def close(self) -> None:
        await asyncio.gather(*self._writes, return_exceptions=True)
        await self._client.aclose()

    async def _write(self, flag: TraceFlag) -> None:
        score: dict[str, object] = {
            "id": flag.score_id,
            "traceId": flag.trace_id,
            "name": flag.name,
            "value": 1,
            "dataType": "BOOLEAN",
            "timestamp": flag.at.isoformat(timespec="milliseconds"),
        }
        if self._environment is not None:
            score["environment"] = self._environment
        try:
            # Langfuse takes a list of scores and answers 207 when it rejects any of them.
            response = await self._client.post(self._url, json=[score], auth=self._auth)
        except httpx.HTTPError as error:
            log.warning("Langfuse took no %s score: %s", flag.name, type(error).__name__)
            return
        if response.status_code == 207:
            log.warning("Langfuse rejected the %s score", flag.name)
        elif response.status_code >= 300:
            log.warning("Langfuse answered %d to the %s score", response.status_code, flag.name)
