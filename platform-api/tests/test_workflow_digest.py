"""The digest that binds a set-up approval to one exact workflow version (ADR 0051, section 3)."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from platform_api.orchestration import workflow_digest

GOLDEN = Path(__file__).parent / "golden" / "n8n"
DOCUMENTS = [p for p in sorted(GOLDEN.glob("*.json")) if p.stem != "served_types"]


def document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def as_n8n_gives_it_back(sent: dict[str, Any]) -> dict[str, Any]:
    """What n8n adds or moves of its own: new ids, other positions, the nodes in another order,
    and a whole number written without its point."""
    back = deepcopy(sent)
    back.update({"id": "wf123", "versionId": "v9", "createdAt": "2026-11-17T01:00:00.000Z"})
    for number, node in enumerate(back["nodes"]):
        node["id"] = f"n8n-{number}"
        node["position"] = [number * 7, 3]
        if node.get("typeVersion") == 1.0:
            node["typeVersion"] = 1
    back["nodes"].reverse()
    back["meta"] = {"templateCredsSetupCompleted": True}
    return back


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: p.stem)
def test_n8n_s_own_fields_and_the_layout_do_not_change_the_digest(path: Path):
    sent = document(path)

    assert workflow_digest(as_n8n_gives_it_back(sent)) == workflow_digest(sent)


def test_a_sticky_note_does_not_count():
    sent = document(GOLDEN / "release_check.json")
    noted = deepcopy(sent)
    note = next(n for n in noted["nodes"] if n["type"] == "n8n-nodes-base.stickyNote")
    note["parameters"]["content"] = "Edited in n8n."

    assert workflow_digest(noted) == workflow_digest(sent)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["nodes"][-1]["parameters"].update({"anything": "new"}),
        lambda d: d["nodes"][-1].update({"disabled": True}),
        lambda d: d["nodes"][-1].update({"onError": "continueRegularOutput"}),
        lambda d: d["settings"].update({"timezone": "UTC"}),
        lambda d: d.update({"name": "Another name"}),
        lambda d: d["connections"].clear(),
        lambda d: d.update({"pinData": {"Read release": [{"json": {}}]}}),
        lambda d: d["nodes"][-1].update({"credentials": {"jiraApi": {"id": "x", "name": "x"}}}),
    ],
)
def test_every_other_change_makes_a_new_digest(change: Any):
    sent = document(GOLDEN / "release_check.json")
    changed = deepcopy(sent)
    change(changed)

    assert workflow_digest(changed) != workflow_digest(sent)
