"""Secrets are masked before a trace leaves the process (ADR 0050)."""

import json
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from typing import Final

MASKED: Final = "[masked]"
# Settings whose names end like this hold secrets. A shorter value is too common a string to mask.
SECRET_NAME: Final = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
SHORTEST_SECRET: Final = 8
# Secrets handed over per call, such as a task's callback token, are kept this many at a time.
# Spans leave within seconds of ending, long before this many newer calls arrive.
KEPT_LIMIT: Final = 256
KEY_SHAPES: Final = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{8,}"
    r"|sk-[A-Za-z0-9_\-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    # A credential after Bearer or Basic holds a digit, +, / or =, so "basic understanding." stays.
    r"|(?i:bearer|basic)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}"
)


class Masker:
    """Replaces the exact value of every secret it knows, and anything shaped like a known key,
    with `[masked]`. The settings' secrets are known from the start. A secret handed over with
    a call is kept before the call."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._fixed = frozenset(s for s in secrets if len(s) >= SHORTEST_SECRET)
        self._kept: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self._pattern: re.Pattern[str] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Masker:
        return cls(value.strip() for name, value in env.items() if SECRET_NAME.search(name))

    def keep(self, secret: str | None) -> None:
        if secret is None or len(secret) < SHORTEST_SECRET:
            return
        with self._lock:
            if secret in self._kept:
                self._kept.move_to_end(secret)
                return
            self._kept[secret] = None
            if len(self._kept) > KEPT_LIMIT:
                self._kept.popitem(last=False)
            self._pattern = None

    def mask(self, text: str) -> str:
        with self._lock:
            if self._pattern is None:
                self._pattern = self._compile()
            pattern = self._pattern
        return pattern.sub(MASKED, text)

    def _compile(self) -> re.Pattern[str]:
        # A secret inside JSON text is written with its quotes and backslashes escaped.
        exact = {form for s in self._fixed | set(self._kept) for form in (s, json.dumps(s)[1:-1])}
        longest_first = sorted(exact, key=len, reverse=True)
        return re.compile("|".join([*map(re.escape, longest_first), KEY_SHAPES.pattern]))
