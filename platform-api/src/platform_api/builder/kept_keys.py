"""Keys kept out of the plan the platform sends for a fix (ADR 0055).

The coordinator and its sub-agents never see a key, and nor does the agent runtime. A key needs no
known shape to be one: a password typed into a block in n8n has none, and masking by shape alone
would send it on. So a value counts as a key by where it stands as well as by its shape:

- under a parameter, a header or a query parameter whose name ends as a key's does
  (`SECRET_NAME_ENDS`), or anywhere under one;
- in code or a free-text body (`CARRIES_KEYS`), which can hold anything, so it is kept out whole;
- with a key's shape (`KEY_SHAPE`), or after a key's name, as in token=abc or "Authorization":
  "Basic abc";
- in an address with a user name or a password, or a key in its query;
- in JSON text that holds one, also inside an expression.

Each such value becomes `KEPT`, which is no setting's placeholder, so the drafter leaves it where
it stands, and the runtime's scope check refuses a fix that touches it. `kept` lists where each
stood, by block and path, never the value. The stopped version keeps every value, so setting up a
fix puts each back from there (ADR 0055, PR 6).

A setting's placeholder can stand in a key's place too, whole or in a longer text: after Bearer,
a key's name or an address's name and password, or in JSON under a key's name. Such a setting,
and one that fills a parameter named as a key, keeps its value out the same way.

The stand-in and the names are the runtime's, which it writes to
contracts/fixtures/agent/key-shapes.json. A test holds them together. Pure."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast
from urllib.parse import parse_qsl, urlsplit

from platform_api.builder.drafted_settings import PLACEHOLDER
from platform_api.builder.workflow_report import KEY_SHAPE
from platform_api.orchestration import PlanBlock, PlanSetting, WorkflowPlan

KEPT: Final = "<<kept by the platform>>"
SECRET_NAME_ENDS: Final = (
    "apikey",
    "accesskey",
    "privatekey",
    "secret",
    "password",
    "passwd",
    "passphrase",
    "token",
    "bearer",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "signature",
    "sessionid",
)
"""How a name that holds a key ends, once its case and separators are gone: accessToken,
x-api-key and Authorization all do."""
CARRIES_KEYS: Final = frozenset(
    {"jsCode", "pythonCode", "functionCode", "code", "body", "jsonBody", "rawBody"}
)
"""Code and free-text bodies. Anything can stand in them, a key included, so each is kept out
whole."""
_SEPARATORS: Final = re.compile(r"[\s_.\-]")
_URL: Final = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.IGNORECASE)
_NAME_VALUE: Final = re.compile(r"[\"']?([A-Za-z0-9_.\-]+)[\"']?\s*[:=]\s*(?!<<)[\"']?[^\s\"',}&/]")
"""A name, then : or =, then a value that isn't a setting's placeholder."""
_NAME_BEFORE: Final = re.compile(r"[\"']?([A-Za-z0-9_.\-]+)[\"']?\s*[:=]\s*[\"']?$")
_SCHEME_BEFORE: Final = re.compile(r"(?i)\b(?:bearer|basic|digest|token)\s+$")


def names_a_secret(name: str) -> bool:
    return _SEPARATORS.sub("", name).lower().endswith(SECRET_NAME_ENDS)


@dataclass(frozen=True)
class KeptPlace:
    """Where a key stood: a block's parameter path, or a setting's value when `block` is None."""

    block: str | None
    path: str


@dataclass(frozen=True)
class KeptOut:
    plan: WorkflowPlan
    kept: tuple[KeptPlace, ...]


def keys_kept_out(plan: WorkflowPlan) -> KeptOut:
    """The plan with `KEPT` wherever a key stood, and where each stood."""
    kept: list[KeptPlace] = []
    secret_settings: set[str] = set()
    walks = [_Walk(block.name, kept, secret_settings) for block in plan.blocks]
    blocks = [_block(block, walk) for block, walk in zip(plan.blocks, walks, strict=True)]
    names = {(walk.block, path): name for walk in walks for path, name in walk.names.items()}
    for setting in plan.settings:
        for fill in setting.fills:
            named = names.get((fill.block, fill.parameter)) or _last_name(fill.parameter)
            if names_a_secret(named):
                secret_settings.add(setting.id)
    settings = [_setting(setting, kept, secret_settings) for setting in plan.settings]
    name = plan.name
    if KEY_SHAPE.search(name):
        name = KEPT
        kept.append(KeptPlace(None, "name"))
    found = plan.model_copy(update={"name": name, "blocks": blocks, "settings": settings})
    return KeptOut(found, tuple(kept))


def _block(block: PlanBlock, walk: _Walk) -> PlanBlock:
    parameters = cast(dict[str, Any], walk.value(block.parameters, "", "", False))
    if parameters == block.parameters:
        return block
    return block.model_copy(update={"parameters": parameters})


def _setting(setting: PlanSetting, kept: list[KeptPlace], secret_settings: set[str]) -> PlanSetting:
    value = setting.value
    if value is None or not (setting.id in secret_settings or KEY_SHAPE.search(value)):
        return setting
    kept.append(KeptPlace(None, f"settings.{setting.id}"))
    return setting.model_copy(update={"value": KEPT})


def _last_name(path: str) -> str:
    parts = [part for part in re.split(r"[.\[\]]", path) if part and not part.isdigit()]
    return parts[-1] if parts else path


def _carries(name: str) -> bool:
    return names_a_secret(name) or name in CARRIES_KEYS


@dataclass
class _Walk:
    block: str
    kept: list[KeptPlace]
    secret_settings: set[str]
    names: dict[str, str] = field(default_factory=dict[str, str])
    """The name each value goes by, by its path."""

    def value(self, value: Any, path: str, name: str, secret: bool) -> Any:
        """The value with each key in it kept out. `secret` says a key's name, or code, is
        above it."""
        match value:
            case dict():
                fields = cast(Mapping[str, Any], value)
                paired = fields.get("name") if "value" in fields else None
                found: dict[str, Any] = {}
                for key, inner in fields.items():
                    said = str(paired) if key == "value" and isinstance(paired, str) else key
                    inside = f"{path}.{key}" if path else key
                    found[key] = self.value(inner, inside, said, secret or _carries(said))
                return found
            case list():
                items = cast(list[Any], value)
                return [
                    self.value(item, f"{path}[{i}]", name, secret) for i, item in enumerate(items)
                ]
            case str():
                self.names[path] = name
                return self._text(value, path, secret)
            case int() | float() if not isinstance(value, bool) and secret:
                return self._kept(path)
            case _:
                return value

    def _text(self, text: str, path: str, secret: bool) -> str:
        placed = list(PLACEHOLDER.finditer(text))
        for found in placed:
            if secret or _key_around(text, found):
                self.secret_settings.add(found.group(1))
        if not text or PLACEHOLDER.fullmatch(text):
            return text
        if secret or self._holds_a_key(text):
            self.secret_settings.update(found.group(1) for found in placed)
            return self._kept(path)
        return text

    def _holds_a_key(self, text: str) -> bool:
        """A key's shape, a key's name with a value after it, an address with a user name, a
        password or a key in it, or JSON that holds one."""
        if KEY_SHAPE.search(text):
            return True
        if any(names_a_secret(found.group(1)) for found in _NAME_VALUE.finditer(text)):
            return True
        for found in _URL.finditer(text):
            parts = urlsplit(found.group())
            if (parts.username and not PLACEHOLDER.fullmatch(parts.username)) or (
                parts.password and not PLACEHOLDER.fullmatch(parts.password)
            ):
                return True
            if any(
                names_a_secret(name) and not PLACEHOLDER.fullmatch(said)
                for name, said in parse_qsl(parts.query)
            ):
                return True
        inner = _json_in(text)
        if inner is None:
            return False
        probe = _Walk(self.block, [], self.secret_settings)
        probe.value(inner, "", "", False)
        return bool(probe.kept)

    def _kept(self, path: str) -> str:
        self.kept.append(KeptPlace(self.block, path))
        return KEPT


def _key_around(text: str, found: re.Match[str]) -> bool:
    """Whether a placeholder stands where a key goes: after Bearer or a key's name, or as an
    address's password."""
    before, after = text[: found.start()], text[found.end() :]
    if _SCHEME_BEFORE.search(before):
        return True
    if (named := _NAME_BEFORE.search(before)) is not None and names_a_secret(named.group(1)):
        return True
    return after.startswith("@") and "://" in before


def _json_in(text: str) -> object | None:
    """The JSON a text holds, once an expression's mark and braces are taken off, or None."""
    inner = text.strip()
    if inner.startswith("="):
        inner = inner[1:].strip()
    if inner.startswith("{{") and inner.endswith("}}"):
        inner = inner[2:-2].strip()
    if not inner.startswith(("{", "[")):
        return None
    try:
        return cast(object, json.loads(inner))
    except ValueError:
        return None
