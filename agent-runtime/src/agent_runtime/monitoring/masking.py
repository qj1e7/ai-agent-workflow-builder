"""Secrets are masked before a trace leaves the process (ADR 0050)."""

import json
import re
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Mapping
from typing import Final

MASKED: Final = "[masked]"
# Settings whose names end like this hold secrets. A shorter value is too common a string to mask.
SECRET_NAME: Final = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
SHORTEST_SECRET: Final = 8
# A secret handed over with a call stays masked this long after its trace ends, while the trace's
# spans may still wait in the export queue. langfuse_tracing.LONGEST_EXPORT_WAIT is the worst wait.
GRACE_SECONDS: Final = 120.0
# The most secrets held at once, for open traces and in their grace. A trace that would pass it
# goes untraced, so nothing is ever unmasked to make room.
SECRETS_LIMIT: Final = 4096
KEY_SHAPES: Final = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{8,}"
    r"|sk-[A-Za-z0-9_\-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    # A credential after Bearer or Basic holds a digit, +, / or =, so "basic understanding." stays.
    r"|(?i:bearer|basic)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}"
)


type Held = tuple[str, ...]


class Masker:
    """Replaces the exact value of every secret it knows, and anything shaped like a known key,
    with `[masked]`. The settings' secrets are known from the start. A secret handed over with a
    call is held from before the call until its trace ends, then for a grace while the trace's
    spans may still be leaving."""

    def __init__(
        self,
        secrets: Iterable[str] = (),
        grace: float = GRACE_SECONDS,
        limit: int = SECRETS_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fixed = frozenset(s for s in secrets if len(s) >= SHORTEST_SECRET)
        self._grace = grace
        self._limit = limit
        self._clock = clock
        self._held: Counter[str] = Counter()
        # Each released secret with when it may be forgotten. The grace is fixed and the clock only
        # moves forward, so the first entry is always the first to go.
        self._released: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()
        self._pattern: re.Pattern[str] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Masker:
        return cls(value.strip() for name, value in env.items() if SECRET_NAME.search(name))

    @property
    def holding(self) -> int:
        """How many handed-over secrets are masked now, held or in their grace."""
        with self._lock:
            self._forget_expired()
            return len(self._held) + len(self._released)

    def hold(self, *secrets: str | None) -> Held | None:
        """Holds the secrets until `release`. None when holding them would pass the limit: the
        caller must then send nothing."""
        held = tuple(s for s in secrets if s is not None and len(s) >= SHORTEST_SECRET)
        with self._lock:
            self._forget_expired()
            new = {s for s in held if s not in self._held and s not in self._released}
            if len(self._held) + len(self._released) + len(new) > self._limit:
                return None
            for secret in held:
                self._held[secret] += 1
                self._released.pop(secret, None)
            self._pattern = None
        return held

    def release(self, held: Held) -> None:
        """The trace has ended. Its secrets stay masked for the grace."""
        with self._lock:
            forget_at = self._clock() + self._grace
            for secret in held:
                self._held[secret] -= 1
                if self._held[secret] <= 0:
                    del self._held[secret]
                    self._released[secret] = forget_at

    def mask(self, text: str) -> str:
        with self._lock:
            self._forget_expired()
            if self._pattern is None:
                self._pattern = self._compile()
            pattern = self._pattern
        return pattern.sub(MASKED, text)

    def _forget_expired(self) -> None:
        now = self._clock()
        while self._released and next(iter(self._released.values())) <= now:
            self._released.popitem(last=False)
            self._pattern = None

    def _compile(self) -> re.Pattern[str]:
        known = self._fixed | set(self._held) | set(self._released)
        # A secret inside JSON text is written with its quotes and backslashes escaped.
        exact = {form for s in known for form in (s, json.dumps(s)[1:-1])}
        longest_first = sorted(exact, key=len, reverse=True)
        return re.compile("|".join([*map(re.escape, longest_first), KEY_SHAPES.pattern]))
