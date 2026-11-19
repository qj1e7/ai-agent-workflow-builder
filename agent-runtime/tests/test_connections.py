"""n8n's exits and inputs of each block, read from the catalogue the pinned image serves (ADR 0051,
section 8, as amended). CI mounts contracts/ into the test image, where it is /contracts."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.catalogue import Catalogue
from agent_runtime.connections import BY_HAND, RULES, digest

CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "n8n" / "catalogue.json"

type Json = dict[str, Any]


@pytest.fixture(scope="module")
def raw() -> Json:
    return json.loads(CATALOGUE.read_bytes())


@pytest.fixture(scope="module")
def catalogue(raw: Json) -> Catalogue:
    return Catalogue(raw)


def group_of(raw: Json, node_type: str, version: float) -> Json:
    return next(g for g in raw["blocks"][node_type]["versions"] if version in g["versions"])


def test_the_catalogue_holds_n8n_s_outputs_their_names_and_inputs(raw: Json):
    check = group_of(raw, "n8n-nodes-base.if", 2.3)
    assert (check["inputs"], check["outputs"], check["outputNames"]) == (
        ["main"],
        ["main", "main"],
        ["true", "false"],
    )
    compare = group_of(raw, "n8n-nodes-base.compareDatasets", 2.3)
    assert compare["inputNames"] == ["Input A", "Input B"]
    model = group_of(raw, "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.3)
    assert (model["inputs"], model["outputs"]) == ([], ["ai_languageModel"])
    assert group_of(raw, "n8n-nodes-base.merge", 3.2)["inputs"].startswith("={{")
    assert group_of(raw, "n8n-nodes-base.switch", 3.4)["outputs"].startswith("={{")


def computed(raw: Json) -> dict[str, set[str]]:
    """Each expression n8n computes a block's inputs or outputs with, by its digest, with the
    blocks and versions that use it."""
    found: dict[str, set[str]] = {}
    for name, block in raw["blocks"].items():
        for group in block["versions"]:
            for key in ("inputs", "outputs"):
                if isinstance(group.get(key), str):
                    found.setdefault(digest(group[key]), set()).add(f"{name} {group['versions']}")
    return found


def test_code_resolves_or_keeps_by_hand_each_computed_link_the_image_serves(raw: Json):
    """A new pin that changes one of n8n's expressions fails here until someone reads it again
    and writes its rule."""
    found = computed(raw)

    assert {d: sorted(b) for d, b in found.items() if d not in RULES and d not in BY_HAND} == {}
    assert set(RULES) | set(BY_HAND) <= set(found), "a rule for an expression n8n no longer serves"
    assert not set(RULES) & set(BY_HAND)


@pytest.mark.parametrize(
    ("node_type", "version", "values", "exits"),
    [
        ("n8n-nodes-base.if", 2.3, {}, [("main", "true"), ("main", "false")]),
        ("n8n-nodes-base.filter", 2.3, {}, [("main", "Kept")]),
        ("n8n-nodes-base.splitInBatches", 3, {}, [("main", "done"), ("main", "loop")]),
        ("n8n-nodes-base.splitInBatches", 2, {}, [("main", "loop"), ("main", "done")]),
        ("CUSTOM.wabReportFailure", 1, {}, []),
        ("n8n-nodes-base.switch", 3.4, {}, [("main", "0")]),
        (
            "n8n-nodes-base.switch",
            3.4,
            {"mode": "expression", "numberOutputs": 2},
            [("main", "0"), ("main", "1")],
        ),
        (
            "n8n-nodes-base.switch",
            2,
            {"rules": {"rules": [{"outputKey": "x"}, {}]}},
            [("main", "x"), ("main", "1")],
        ),
        ("n8n-nodes-base.webhook", 2.1, {"httpMethod": "POST"}, [("main", "POST")]),
        (
            "n8n-nodes-base.webhook",
            2.1,
            {"multipleMethods": True},
            [("main", "GET"), ("main", "POST")],
        ),
        ("n8n-nodes-base.respondToWebhook", 1.5, {}, [("main", None)]),
        (
            "n8n-nodes-base.respondToWebhook",
            1.5,
            {"enableResponseOutput": True},
            [("main", "Input Data"), ("main", "Response")],
        ),
        (
            "@n8n/n8n-nodes-langchain.textClassifier",
            1.1,
            {"categories": {"categories": [{"category": "Bug"}]}, "options": {"fallback": "other"}},
            [("main", "Bug"), ("main", "Other")],
        ),
        (
            "@n8n/n8n-nodes-langchain.sentimentAnalysis",
            1.1,
            {},
            [("main", "Positive"), ("main", "Neutral"), ("main", "Negative")],
        ),
        ("@n8n/n8n-nodes-langchain.guardrails", 2, {}, [("main", "Pass"), ("main", "Fail")]),
        ("@n8n/n8n-nodes-langchain.guardrails", 2, {"operation": "sanitize"}, [("main", None)]),
        (
            "n8n-nodes-base.evaluation",
            4.8,
            {"operation": "checkIfEvaluating"},
            [("main", "Evaluation"), ("main", "Normal")],
        ),
        (
            "@n8n/n8n-nodes-langchain.vectorStoreInMemory",
            1.3,
            {},
            [("ai_vectorStore", "Vector Store")],
        ),
        ("@n8n/n8n-nodes-langchain.vectorStoreInMemory", 1.3, {"mode": "insert"}, [("main", None)]),
    ],
)
def test_exits_are_n8n_s_outputs_with_their_names(
    catalogue: Catalogue,
    node_type: str,
    version: float,
    values: Json,
    exits: list[tuple[str, str | None]],
):
    assert [(e.kind, e.name) for e in catalogue.exits(node_type, version, values)] == exits


@pytest.mark.parametrize(
    ("node_type", "version", "values", "inputs"),
    [
        ("n8n-nodes-base.scheduleTrigger", 1.4, {}, []),
        ("n8n-nodes-base.merge", 2.1, {}, [("main", "Input 1"), ("main", "Input 2")]),
        ("n8n-nodes-base.merge", 3.2, {}, [("main", "Input 1"), ("main", "Input 2")]),
        (
            "n8n-nodes-base.merge",
            3.2,
            {"numberInputs": 3},
            [("main", "Input 1"), ("main", "Input 2"), ("main", "Input 3")],
        ),
        ("@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.3, {}, []),
        (
            "@n8n/n8n-nodes-langchain.vectorStoreInMemory",
            1.3,
            {"mode": "insert"},
            [("ai_embedding", "Embedding"), ("main", None), ("ai_document", "Document")],
        ),
        (
            "@n8n/n8n-nodes-langchain.guardrails",
            2,
            {"guardrails": {"jailbreak": {}}},
            [("main", None), ("ai_languageModel", "Chat Model")],
        ),
    ],
)
def test_inputs_are_n8n_s_with_their_names(
    catalogue: Catalogue,
    node_type: str,
    version: float,
    values: Json,
    inputs: list[tuple[str, str | None]],
):
    found = catalogue.inputs(node_type, version, values)

    assert [(i.kind, i.name) for i in found.links] == inputs
    assert not found.any_ai


def test_an_ai_agent_s_inputs_are_kept_by_hand_one_main_input_and_any_ai_wire(
    catalogue: Catalogue,
):
    found = catalogue.inputs("@n8n/n8n-nodes-langchain.agent", 3.1, {})

    assert [i.kind for i in found.links] == ["main"]
    assert found.any_ai


def test_describe_gives_the_exits_and_inputs_a_wire_names(catalogue: Catalogue):
    compare = catalogue.describe_block("n8n-nodes-base.compareDatasets", 2.3)
    assert compare["exits"] == ["In A only", "Same", "Different", "In B only"]
    assert compare["inputs"] == ["Input A", "Input B"]

    check = catalogue.describe_block("n8n-nodes-base.if", 2.3)
    assert (check["exits"], check["inputs"]) == (["true", "false"], ["main"])
    model = catalogue.describe_block("@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.3)
    assert (model["exits"], model["inputs"]) == (["ai_languageModel"], [])
    switch = catalogue.describe_block("n8n-nodes-base.switch", 3.4)
    assert "output key" in switch["exits"]
    merge = catalogue.describe_block("n8n-nodes-base.merge", 3.2)
    assert "numberInputs" in merge["inputs"]
