"""Keys kept out of the plan the platform sends for a fix (ADR 0055).

The coordinator and its sub-agents never see a key, and nor does the agent runtime. A key needs no
known shape to be one: a password typed into a block in n8n has none, and masking by shape alone
would send it on. So a value counts as a key by where it stands as well as by its shape: under a
parameter, a header or a query parameter whose name ends as a key's does (`SECRET_NAME_ENDS`),
anything with a key's shape (`KEY_SHAPE`), and an address with a name and password or a key in
it. A text that holds JSON counts when anything in it does.

Each such value becomes `KEPT`, which is no setting's placeholder, so the drafter leaves it where
it stands, and the runtime's scope check refuses a fix that touches it. `kept` lists where each
stood, by block and path, never the value. The stopped version keeps every value, so setting up a
fix puts each back from there (ADR 0055, PR 6). A setting whose placeholder stands in such a
place, or whose value has a key's shape, keeps its value out the same way.

Both stand-in and names are the runtime's, which it writes to
contracts/fixtures/agent/key-shapes.json. A test holds them together. Pure."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
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
_SEPARATORS: Final = re.compile(r"[\s_.\-]")
_URL: Final = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.IGNORECASE)


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
    blocks = [_block(block, kept, secret_settings) for block in plan.blocks]
    settings = [_setting(setting, kept, secret_settings) for setting in plan.settings]
    name = plan.name
    if KEY_SHAPE.search(name):
        name = KEPT
        kept.append(KeptPlace(None, "name"))
    found = plan.model_copy(update={"name": name, "blocks": blocks, "settings": settings})
    return KeptOut(found, tuple(kept))


def _block(block: PlanBlock, kept: list[KeptPlace], secret_settings: set[str]) -> PlanBlock:
    walk = _Walk(block.name, kept, secret_settings)
    parameters = cast(dict[str, Any], walk.value(block.parameters, "", ""))
    return (
        block
        if parameters == block.parameters
        else block.model_copy(update={"parameters": parameters})
    )


def _setting(setting: PlanSetting, kept: list[KeptPlace], secret_settings: set[str]) -> PlanSetting:
    value = setting.value
    if value is None or not (setting.id in secret_settings or KEY_SHAPE.search(value)):
        return setting
    kept.append(KeptPlace(None, f"settings.{setting.id}"))
    return setting.model_copy(update={"value": KEPT})


@dataclass
class _Walk:
    block: str
    kept: list[KeptPlace]
    secret_settings: set[str]

    def value(self, value: Any, path: str, name: str) -> Any:
        match value:
            case dict():
                fields = cast(Mapping[str, Any], value)
                paired = fields.get("name") if "value" in fields else None
                return {
                    key: self.value(
                        inner,
                        f"{path}.{key}" if path else key,
                        str(paired) if key == "value" and isinstance(paired, str) else key,
                    )
                    for key, inner in fields.items()
                }
            case list():
                items = cast(list[Any], value)
                return [self.value(item, f"{path}[{i}]", name) for i, item in enumerate(items)]
            case str() if (setting := PLACEHOLDER.fullmatch(value)) is not None:
                if names_a_secret(name):
                    self.secret_settings.add(setting.group(1))
                return value
            case str() if value and (names_a_secret(name) or _holds_a_key(value)):
                return self._kept(path)
            case int() | float() if not isinstance(value, bool) and names_a_secret(name):
                return self._kept(path)
            case _:
                return value

    def _kept(self, path: str) -> str:
        self.kept.append(KeptPlace(self.block, path))
        return KEPT


def _holds_a_key(text: str) -> bool:
    """A key's shape, an address with a name and password or a key in it, or JSON that holds one
    under a key's name."""
    if KEY_SHAPE.search(text):
        return True
    for found in _URL.finditer(text):
        parts = urlsplit(found.group())
        if parts.username or parts.password:
            return True
        if any(names_a_secret(name) for name, _ in parse_qsl(parts.query)):
            return True
    if text.lstrip().startswith(("{", "[")):
        try:
            inner: object = json.loads(text)
        except ValueError:
            return False
        probe = _Walk("", [], set())
        probe.value(inner, "", "")
        return bool(probe.kept)
    return False
