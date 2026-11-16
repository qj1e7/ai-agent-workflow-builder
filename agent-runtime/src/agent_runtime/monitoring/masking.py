"""Secrets are masked before a trace leaves the process (ADR 0050)."""

import json
import re
import threading
from collections import Counter, OrderedDict
from collections.abc import Iterable, Mapping
from typing import Final

MASKED: Final = "[masked]"
# Settings whose names end like this hold secrets. A shorter value is too common a string to mask.
SECRET_NAME: Final = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
SHORTEST_SECRET: Final = 8
# A secret handed over with a call stays masked for this many more releases after its trace left,
# in case a late span names it. While its trace is open it is never dropped.
RECENTLY_RELEASED: Final = 256
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
    call is held from before the call until its trace has left the process, however many other
    calls arrive meanwhile."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._fixed = frozenset(s for s in secrets if len(s) >= SHORTEST_SECRET)
        self._held: Counter[str] = Counter()
        self._released: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self._pattern: re.Pattern[str] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Masker:
        return cls(value.strip() for name, value in env.items() if SECRET_NAME.search(name))

    def hold(self, *secrets: str | None) -> Held:
        held = tuple(s for s in secrets if s is not None and len(s) >= SHORTEST_SECRET)
        with self._lock:
            for secret in held:
                self._held[secret] += 1
                self._released.pop(secret, None)
            self._pattern = None
        return held

    def release(self, held: Held) -> None:
        with self._lock:
            for secret in held:
                self._held[secret] -= 1
                if self._held[secret] > 0:
                    continue
                del self._held[secret]
                self._released[secret] = None
                if len(self._released) > RECENTLY_RELEASED:
                    self._released.popitem(last=False)
            self._pattern = None

    def mask(self, text: str) -> str:
        with self._lock:
            if self._pattern is None:
                self._pattern = self._compile()
            pattern = self._pattern
        return pattern.sub(MASKED, text)

    def _compile(self) -> re.Pattern[str]:
        known = self._fixed | set(self._held) | set(self._released)
        # A secret inside JSON text is written with its quotes and backslashes escaped.
        exact = {form for s in known for form in (s, json.dumps(s)[1:-1])}
        longest_first = sorted(exact, key=len, reverse=True)
        return re.compile("|".join([*map(re.escape, longest_first), KEY_SHAPES.pattern]))
