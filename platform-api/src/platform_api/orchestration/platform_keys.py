"""Which key of the platform's each of n8n's own blocks runs with (ADR 0045, ENGINE-PLAN E16).

The platform makes one key a system, with a fixed id, in its own n8n project, and never lends it
into a member's space. Each block for that system names that key, by the n8n credential type its
parameters pick. A workflow that comes back from a member's space has every block's key put back
by the block's type (`attach_keys`), whatever the member's editor kept or dropped, and every key
named on any other block taken off. A block set to do what its class turns off, such as a Slack
delete, gets no key, so it cannot run with the platform's.

Pure.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from platform_api.orchestration.node_classes import NODE_CLASSES, On, Runs
from platform_api.settings import KeySystem


@dataclass(frozen=True)
class KeySpec:
    system: KeySystem
    id: str
    """The id the platform gives the key in n8n, the same each time it makes it."""
    on: On
    node_type: str
    name: str
    """What n8n's editor calls it."""
    said: str
    """The system in a person's words."""
    picks: str
    """The block's parameter that picks which credential type it asks for."""
    picked: str
    """n8n's default for that parameter, when the block leaves it out."""
    by_kind: Mapping[str, str]
    """For each credential type the platform's key may be, the value that parameter takes."""


KEYS: Mapping[KeySystem, KeySpec] = {
    "jira": KeySpec(
        "jira",
        "wab-jira-read",
        "read",
        "n8n-nodes-base.jira",
        "The platform's Jira key, reads only",
        "Jira",
        "jiraVersion",
        "cloud",
        {"jiraSoftwareServerPatApi": "serverPat", "jiraSoftwareCloudApi": "cloud"},
    ),
    "github": KeySpec(
        "github",
        "wab-github-read",
        "read",
        "n8n-nodes-base.github",
        "The platform's GitHub key, reads only",
        "GitHub",
        "authentication",
        "accessToken",
        {"githubApi": "accessToken"},
    ),
    "slack": KeySpec(
        "slack",
        "wab-slack-send",
        "notice",
        "n8n-nodes-base.slack",
        "The platform's Slack key, posts only",
        "Slack",
        "authentication",
        "accessToken",
        {"slackApi": "accessToken"},
    ),
}
KEY_FOR_TYPE: Mapping[str, KeySpec] = {spec.node_type: spec for spec in KEYS.values()}


def attach_keys(document: Mapping[str, Any], made: Mapping[str, str]) -> dict[str, Any]:
    """The document with each block for a system naming the platform's key for it, and its
    parameters asking for that key's type, and every other key taken off. `made` is each key
    the platform made, by id, with its n8n credential type. A block whose system has no key,
    or that is set to do anything but what its key is for, names none, so it cannot run."""
    attached: dict[str, Any] = deepcopy(dict(document))
    for node in cast(list[dict[str, Any]], attached.get("nodes") or []):
        spec = KEY_FOR_TYPE.get(str(node.get("type")))
        kind = None if spec is None else made.get(spec.id)
        if spec is None or kind is None or kind not in spec.by_kind or not _keyed(node, spec):
            node.pop("credentials", None)
            continue
        node["credentials"] = {kind: {"id": spec.id, "name": spec.name}}
        parameters = node.setdefault("parameters", {})
        # Safe to change without a finding: it picks only which credential type the block asks
        # for, such as Jira Cloud or Data Center. What the block does, its resource and
        # operation, was checked above and stays as it is.
        if parameters.get(spec.picks, spec.picked) != spec.by_kind[kind]:
            parameters[spec.picks] = spec.by_kind[kind]
    return attached


def _keyed(node: Mapping[str, Any], spec: KeySpec) -> bool:
    """The block does what the platform's key is for: a Jira or GitHub read, a Slack post."""
    verdict = NODE_CLASSES.verdict(
        str(node.get("type")), node.get("typeVersion"), node.get("parameters") or {}
    )
    return isinstance(verdict, Runs) and verdict.on == spec.on
