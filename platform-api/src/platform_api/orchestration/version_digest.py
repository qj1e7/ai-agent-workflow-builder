"""The digest of one workflow version, which a set-up approval binds to (ADR 0051, section 3).

It is a hash of the whole document in a canonical form. It drops only where each block sits, the
Sticky Notes, and the fields n8n adds of its own. Every other field counts, a field the checker
doesn't read included, so a field n8n adds in a later release can't slip past it. `same_as_sent`
compares in one direction and skips the pins, so it is not this."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final, cast

STICKY_NOTE: Final = "n8n-nodes-base.stickyNote"
N8N_OWN: Final = frozenset(
    {"id", "meta", "versionId", "activeVersionId", "createdAt", "updatedAt", "versionCounter"}
)
N8N_OWN_ON_BLOCKS: Final = frozenset({"id", "webhookId", "position"})


def workflow_digest(document: Mapping[str, Any]) -> str:
    kept = {k: v for k, v in document.items() if k not in N8N_OWN}
    nodes = [cast(dict[str, Any], n) for n in cast(list[Any], kept.get("nodes") or [])]
    kept["nodes"] = sorted(
        (
            {k: v for k, v in node.items() if k not in N8N_OWN_ON_BLOCKS}
            for node in nodes
            if node.get("type") != STICKY_NOTE
        ),
        key=lambda node: str(node.get("name")),
    )
    canonical = json.dumps(
        _whole_numbers(kept), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _whole_numbers(value: Any) -> Any:
    """n8n gives 1.0 back as 1, so a whole number counts the same either way."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _whole_numbers(v) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [_whole_numbers(v) for v in cast(list[Any], value)]
    return value
