"""Secrets are masked before a trace leaves the process (ADR 0050)."""

import json
import re
import threading
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, cast

from pydantic import BaseModel

MASKED: Final = "[masked]"
# Settings whose names end like this hold secrets. A shorter value is too common a string to mask.
SECRET_NAME: Final = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CONNECTION_STRING)$")
SHORTEST_SECRET: Final = 8
KEY_SHAPE_SOURCES: Final = (
    # A key starts a word, so "task-management-workflow" never reads as "sk-...".
    r"\bsk-ant-[A-Za-z0-9_\-]{8,}",
    r"\bsk-[A-Za-z0-9_\-]{16,}",
    r"\bgh[pousr]_[A-Za-z0-9]{16,}",
    r"\bgithub_pat_[A-Za-z0-9_]{16,}",
    r"\bglpat-[A-Za-z0-9_\-]{16,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"\bxox[abeprs]-[A-Za-z0-9\-]{10,}",
    r"\bxapp-[0-9]-[A-Za-z0-9\-]{10,}",
    r"hooks\.slack\.com/(?:services|triggers|workflows)/[A-Za-z0-9_/\-]+",
    r"webhook\.office\.com/[A-Za-z0-9@_/\-]+",
    r"\bATATT[A-Za-z0-9_=\-]{16,}",
    r"\bAIza[A-Za-z0-9_\-]{35}",
    r"(?i:accountkey|sharedaccesskey)=[A-Za-z0-9+/=]{32,}",
    r"\bsig=[A-Za-z0-9%+/=_\-]{40,}",
    r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    # A credential after Bearer holds a digit, +, / or =, so "bearer instruments" stays.
    r"(?i:bearer)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}",
    # Basic carries base64 with a digit, +, / or =, so "a basic 2-step-approval-flow" stays.
    r"(?i:basic)\s+(?=[A-Za-z]*[0-9+/=])[A-Za-z0-9+/=]{8,}",
)
"""Each shape of a key the masker knows: OpenAI, Anthropic and Langfuse keys, GitHub and GitLab
tokens, AWS access key ids, Slack tokens, Slack and Teams incoming webhooks, Atlassian and Google
API keys, an Azure storage or Service Bus key and a SAS signature, a signed token, a private key,
and a bearer or basic header. Each is distinctive, so a person's plain words never match one, and
none repeats a group, so each runs in linear time. contracts/fixtures/agent/key-shapes.json
carries them, and platform-api refuses every one before it keeps anything (ADR 0051)."""
KEY_SHAPES: Final = re.compile("|".join(KEY_SHAPE_SOURCES))


type Held = tuple[str, ...]


class Masker:
    """Replaces the exact value of every secret it knows, and anything shaped like a known key,
    with `[masked]`. The settings' secrets are known from the start. A secret handed over with a
    call is known while some trace holds it."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._fixed = frozenset(s for s in secrets if len(s) >= SHORTEST_SECRET)
        self._held: Counter[str] = Counter()
        self._lock = threading.Lock()
        self._pattern: re.Pattern[str] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Masker:
        return cls(value.strip() for name, value in env.items() if SECRET_NAME.search(name))

    def hold(self, *secrets: str | None) -> Held:
        held = tuple(s for s in secrets if s is not None and len(s) >= SHORTEST_SECRET)
        with self._lock:
            self._held.update(held)
            self._pattern = None
        return held

    def release(self, held: Held) -> None:
        with self._lock:
            self._held.subtract(held)
            self._held = +self._held
            self._pattern = None

    def mask(self, text: str) -> str:
        with self._lock:
            if self._pattern is None:
                self._pattern = self._compile()
            pattern = self._pattern
        return pattern.sub(MASKED, text)

    def mask_data(self, data: Any) -> Any:
        """The same data with every string in it masked, for a span's input, output or metadata
        before the span holds it."""
        match data:
            case str():
                return self.mask(data)
            case BaseModel():
                return self.mask_data(data.model_dump(mode="json"))
            case Mapping():
                fields = cast(Mapping[object, Any], data)
                return {key: self.mask_data(value) for key, value in fields.items()}
            case list() | tuple():
                return [self.mask_data(item) for item in cast(Sequence[Any], data)]
            case _:
                return data

    def _compile(self) -> re.Pattern[str]:
        known = self._fixed | set(self._held)
        # A secret inside JSON text is written with its quotes and backslashes escaped.
        exact = {form for s in known for form in (s, json.dumps(s)[1:-1])}
        longest_first = sorted(exact, key=len, reverse=True)
        return re.compile("|".join([*map(re.escape, longest_first), KEY_SHAPES.pattern]))
