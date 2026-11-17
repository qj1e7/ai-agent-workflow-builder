"""Every shape of a key the agent runtime's masker knows, platform-api refuses too, in a
person's words, a typed answer and what comes back from n8n, and hides in a report (ADR 0051,
section 5). The two lists are held together by contracts/fixtures/agent/key-shapes.json, which
the runtime writes from its masker."""

import json

import pytest

from platform_api.builder.drafted_workflows import PASTED_KEY, _holds_a_key
from platform_api.builder.workflow_report import HIDDEN, KEY_SHAPE, KEY_SHAPE_SOURCES
from tests.support import FIXTURES

# Each built at run time, so no secret scanner reads one as leaked.
KEYS = [
    "sk-proj-" + "Ab3dEf9h" * 6,
    "sk-ant-api03-" + "Zx9_" * 10,
    "sk-" + "Q1w2E3r4" * 3,
    "ghp_" + "Zx9" * 12,
    "github_pat_" + "Ab3_" * 6,
    "Bearer " + "abc.123/" * 3,
]


def test_platform_api_refuses_every_shape_the_runtime_masks():
    shapes = json.loads((FIXTURES / "agent" / "key-shapes.json").read_text())["shapes"]
    assert shapes, "the runtime writes its masker's shapes"
    assert set(shapes) <= set(KEY_SHAPE_SOURCES)


@pytest.mark.parametrize("key", KEYS)
def test_each_shape_is_refused_typed_or_read_back_and_hidden_in_a_report(key: str):
    assert PASTED_KEY.search(f"post it with {key} please")
    assert _holds_a_key({"name": "x", "nodes": [{"name": "Call", "parameters": {"url": key}}]})
    assert key not in KEY_SHAPE.sub(HIDDEN, f"the words {key} here")
