"""The words for a run that stopped because a source didn't give a usable answer, and the facts
they are made from (ADR 0056). orchestration builds the facts from n8n's record of the failed
block, and the troubleshooter reads them back from the run's stop, so both say the same.

It reads in nothing but the standard library, so scripts/n8n-guards.sh can load it to check that
n8n's limit a try is the one these words say.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

REQUEST_LIMIT_SECONDS: Final = 30
"""How long a read by n8n's own blocks (GET, HEAD or OPTIONS) waits on a source for each try, as
WAB_REQUEST_TIMEOUT_SECONDS sets it for n8n in deploy/compose.yaml and Terraform. Any other
method keeps n8n's own 300 s, and a block may set a limit of its own."""

NOTHING_READ_YET: Final = "Stopped before it read anything."

type Delay = Literal["no_answer", "refused", "cut_off", "unreachable"]
"""What went wrong with the connection, as far as n8n's words for it tell."""

N8N_DELAYS: Final[Mapping[str, Delay]] = {
    "The connection was aborted, perhaps the server is offline": "no_answer",
    "The service refused the connection - perhaps it is offline": "refused",
    "The connection to the server was closed unexpectedly": "cut_off",
    "The server closed the connection unexpectedly": "cut_off",
    "The connection cannot be established, this usually occurs due to an incorrect host": (
        "unreachable"
    ),
    "The connection timed out": "unreachable",
    "The host is unreachable, perhaps the server is offline": "unreachable",
    "The DNS server returned an error, perhaps the server is offline": "unreachable",
}
"""n8n-workflow 2.42.3's words for each connection error a block's request meets
(errors/abstract/node.error.js): ECONNABORTED, which a try that reaches its limit gives, then
ECONNREFUSED, ECONNRESET, GETADDRINFO, ENOTFOUND, ETIMEDOUT, EHOSTUNREACH and EAI_AGAIN. Each
starts the block's error message."""

SOURCE_UNKNOWN: Final = "The source"

_HAPPENED: Final[Mapping[Delay, str]] = {
    "no_answer": "didn't answer {limit}",
    "refused": "refused the connection",
    "cut_off": "closed the connection",
    "unreachable": "could not be reached",
}
CAUSES: Final[Mapping[Delay, str]] = {
    "no_answer": "Nothing came back in that time, so it may be down, busy or out of reach.",
    "refused": "It may be down, or the block may point at the wrong address.",
    "cut_off": (
        "It ended the connection before a full answer came back, so it may have failed or "
        "restarted."
    ),
    "unreachable": (
        "n8n couldn't reach it, so it may be down, or its address may be wrong or blocked."
    ),
}
"""The likely cause, from what n8n's words show and no further."""


@dataclass(frozen=True)
class SourceStop:
    source: str | None
    """The system or host the block called, or None when nothing names it."""
    delay: Delay
    limit_ms: int | None
    """How long each try waited, which the words say only when nothing came back. None when
    nothing shows it, such as a limit an expression sets."""
    block: str
    tries: int
    """The tries n8n made of the block. Each one failed, and n8n keeps only the last one's
    words, which these facts come from."""


def delay_in(message: str | None) -> Delay | None:
    """What went wrong, from n8n's words for the block's error. None for any other error."""
    if not message:
        return None
    return next((d for words, d in N8N_DELAYS.items() if message.startswith(words)), None)


_UNITS: Final = (("hour", 3_600_000), ("minute", 60_000))


def _within(limit_ms: int | None) -> str:
    """Whole hours or minutes as such, any other limit in seconds."""
    if limit_ms is None:
        return "in time"
    for unit, ms in _UNITS:
        if limit_ms % ms == 0:
            count = limit_ms // ms
            return f"within {count} {unit}" + ("" if count == 1 else "s")
    seconds = limit_ms / 1000
    return f"within {seconds:g} second" + ("" if seconds == 1 else "s")


def headline(stop: SourceStop) -> str:
    """One sentence: the source, what went wrong, the block and the tries."""
    source = stop.source or SOURCE_UNKNOWN
    happened = _HAPPENED[stop.delay].format(limit=_within(stop.limit_ms))
    tries = f" after {stop.tries} tries" if stop.tries > 1 else ""
    return f'{source} {happened}, so "{stop.block}" stopped{tries}.'


def stop_words(stop: SourceStop) -> str:
    return f"{headline(stop)} {CAUSES[stop.delay]}"


_READ: Final = re.compile(
    rf"^(?:{re.escape(NOTHING_READ_YET)} )?(?P<source>.+?) "
    r"(?:(?P<no_answer>didn't answer "
    r"(?:in time|within (?P<count>[0-9.]+) (?P<unit>second|minute|hour)s?))"
    r"|(?P<refused>refused the connection)"
    r"|(?P<cut_off>closed the connection)"
    r"|(?P<unreachable>could not be reached))"
    r', so "(?P<block>.+)" stopped(?: after (?P<tries>[0-9]+) tries)?\. '
)


def read_stop(message: str) -> SourceStop | None:
    """The facts a stop's words were made from, or None when they are no source stop."""
    found = _READ.match(message)
    if found is None:
        return None
    delay: Delay = next(d for d in CAUSES if found.group(d) is not None)
    if not message.endswith(CAUSES[delay]):
        return None
    source = found.group("source")
    count, unit = found.group("count"), found.group("unit")
    per = {"second": 1000, **dict(_UNITS)}
    limit = None if count is None else round(float(count) * per[unit])
    if delay != "no_answer":
        limit = REQUEST_LIMIT_SECONDS * 1000
    return SourceStop(
        None if source == SOURCE_UNKNOWN else source,
        delay,
        limit,
        found.group("block"),
        int(found.group("tries") or 1),
    )
