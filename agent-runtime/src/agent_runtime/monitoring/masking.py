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
    r"sk-ant-[A-Za-z0-9_\-]{8,}",
    # Not glued to a letter, so "task-management-workflow" is a word. An escape that ends in a
    # letter, as \n or = in JSON text, %3D in a URL or =3D in an email, is not a word.
    r"(?:(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})|(?<=[%=][0-9A-Fa-f]{2})|(?<![A-Za-z]))"
    r"sk-[A-Za-z0-9_\-]{16,}",
    r"gh[pousr]_[A-Za-z0-9]{16,}",
    r"github_pat_[A-Za-z0-9_]{16,}",
    r"glpat-[A-Za-z0-9_\-]{16,}",
    r"(?:AKIA|ASIA)[0-9A-Z]{16}",
    r"xox[abeprs]-[A-Za-z0-9\-]{10,}",
    r"xapp-[0-9]-[A-Za-z0-9\-]{10,}",
    r"hooks\.slack\.com/(?:services|triggers|workflows)/[A-Za-z0-9_/\-]+",
    r"webhook\.office\.com/[A-Za-z0-9@_/\-]+",
    r"ATATT[A-Za-z0-9_=\-]{16,}",
    r"AIza[A-Za-z0-9_\-]{35}",
    r"(?i:accountkey|sharedaccesskey)=[A-Za-z0-9+/=]{32,}",
    r"sig=[A-Za-z0-9%+/=_\-]{40,}",
    # A signed token's letters are also the letters around it, as in token_eyJ..., so it is read
    # from where that run of letters starts: after any other mark, or after a backslash. After an
    # escape such as \n or = it starts past the escape, so JSON text stays JSON. Read from
    # each eyJ instead, "eyJ-eyJ-..." would be read again at each one, in quadratic time.
    r"(?:(?<=\\)(?![bfnrt]|u[0-9A-Fa-f]{4})|(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})"
    r"|(?<![A-Za-z0-9_\-\\]))"
    r"(?=[A-Za-z0-9_\-]*?eyJ)[A-Za-z0-9_\-]++\.eyJ[A-Za-z0-9_\-]++\.[A-Za-z0-9_\-]+",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    # A credential after Bearer holds a digit, +, / or =, so "bearer instruments" stays.
    r"(?i:bearer)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}",
    # Basic carries base64 with a digit, +, / or =, so "a basic 2-step-approval-flow" stays.
    r"(?i:basic)\s+(?=[A-Za-z]*[0-9+/=])[A-Za-z0-9+/=]{8,}",
)
"""Each shape of a key the masker knows: OpenAI, Anthropic and Langfuse keys, GitHub and GitLab
tokens, AWS access key ids, Slack tokens, Slack and Teams incoming webhooks, Atlassian and Google
API keys, an Azure storage or Service Bus key and a SAS signature, a signed token, a private key,
and a bearer or basic header. A key is found wherever it sits, after `_`, a digit, a quote, a
backslash or an escape, and only "sk-" glued to a letter is read as part of a word. Each is
distinctive, so a person's plain words never match one, and each runs in linear time.
contracts/fixtures/agent/key-shapes.json carries them, and platform-api refuses every one before
it keeps anything (ADR 0051)."""
KEY_SHAPES: Final = re.compile("|".join(KEY_SHAPE_SOURCES))
"""Refused in a person's words wherever the runtime checks them."""
GLUED_SK_KEY: Final = r"sk-[A-Za-z0-9_\-]{16,}"
"""An sk- key glued to a letter. Words such as "task-management-workflow" have this shape too, so
it is never refused, but the masker hides it: a few hidden letters in a trace cost less than a
leaked key."""
MASKED_SHAPES: Final = re.compile("|".join([*KEY_SHAPE_SOURCES, GLUED_SK_KEY]))
"""What the masker and the eval runner's redaction hide: every key shape, and an sk- key glued to a
letter."""


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
        return re.compile("|".join([*map(re.escape, longest_first), MASKED_SHAPES.pattern]))
