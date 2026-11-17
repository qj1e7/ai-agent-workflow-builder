"""Every shape of a key the agent runtime's masker knows, platform-api refuses too, in a
person's words, a typed answer and what comes back from n8n, and hides in a report (ADR 0051,
section 5). The two lists are held together by contracts/fixtures/agent/key-shapes.json, which
the runtime writes from its masker."""

import json

import pytest

from platform_api.builder.drafted_workflows import PASTED_KEY, _holds_a_key
from platform_api.builder.workflow_report import HIDDEN, KEY_SHAPE, KEY_SHAPE_SOURCES
from tests.support import FIXTURES

UUID = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
# Each built at run time, so no secret scanner reads one as leaked. None is a real key.
KEYS = {
    "OpenAI project key": "sk-proj-" + "Ab3dEf9h" * 6,
    "Anthropic key": "sk-ant-api03-" + "Zx9_" * 10,
    "OpenAI key": "sk-" + "Q1w2E3r4" * 3,
    "Langfuse secret key": "sk-lf-" + UUID,
    "GitHub classic token": "ghp_" + "Zx9" * 12,
    "GitHub OAuth token": "gho_" + "Zx9" * 12,
    "GitHub app token": "ghs_" + "Zx9" * 12,
    "GitHub fine-grained token": "github_pat_" + "Ab3_" * 6,
    "GitLab token": "glpat-" + "Ab3dEf9h" * 3,
    "bearer header": "Bearer " + "abc.123/" * 3,
    "basic header": "Basic " + "dXNlcjpwYXNz=",
    "AWS access key id": "AKIA" + "Z7Q2" * 4,
    "AWS session key id": "ASIA" + "K3V9" * 4,
    "Slack bot token": "xoxb-" + "1234567890-" * 2 + "Ab3dEf9h" * 3,
    "Slack app-level token": "xapp-" + "1-A0B1C2D3E4F-1234567890123-" + "ab3d" * 16,
    "Slack webhook": "https://hooks.slack.com/" + "services/T0AB12CD3/B0EF45GH6/" + "Xy7" * 8,
    "Teams webhook": f"https://contoso.webhook.office.com/webhookb2/{UUID}@{UUID}/IncomingWebhook/"
    + "ab12" * 8,
    "Atlassian API token": "ATATT3" + "xFfGF0" + "Ab3_dEf9-" * 20 + "=1A2B3C4D",
    "Google API key": "AIza" + "Sy" + "Ab3dEf9h" * 4 + "Z",
    "Azure storage key": "AccountKey=" + "Ab3d+Ef9/" * 9 + "Ab==",
    "Azure SAS signature": "sig=" + "Ab3dEf9h%2B" * 4 + "%3D",
    "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "Ab3dEf9h-_" * 3,
    "private key": "-----BEGIN " + "EC PRIVATE" + " KEY-----\nMHcC" + "Ab3d" * 16,
}
PLAIN_WORDS = [
    "langgraph 0.2.34 is out",
    "upgrade node to v22.11.0-rc.1",
    "commit " + "3f2a9c1e" * 5 + " fixed it",
    "short sha 3f2a9c1",
    "run 123e4567-e89b-12d3-a456-426614174000 failed",
    "move MOCK-123 and MOCK-4567 to done",
    "ask the team about this task",
    "set up a task-management-workflow for the risk-assessment-report",
    "a basic understanding.",
    "set up a basic 2-step-approval-flow",
    "bearer instruments",
]


def test_platform_api_refuses_every_shape_the_runtime_masks():
    shapes = json.loads((FIXTURES / "agent" / "key-shapes.json").read_text())["shapes"]
    assert shapes, "the runtime writes its masker's shapes"
    assert set(shapes) <= set(KEY_SHAPE_SOURCES)


@pytest.mark.parametrize("key", KEYS.values(), ids=list(KEYS))
def test_each_shape_is_refused_typed_or_read_back_and_hidden_in_a_report(key: str):
    assert PASTED_KEY.search(f"post it with {key} please")
    assert _holds_a_key({"name": "x", "nodes": [{"name": "Call", "parameters": {"url": key}}]})
    hidden = KEY_SHAPE.sub(HIDDEN, f"the words {key} here")
    assert key not in hidden and key[-8:] not in hidden


@pytest.mark.parametrize("text", PLAIN_WORDS)
def test_plain_words_are_never_refused_or_hidden(text: str):
    assert PASTED_KEY.search(text) is None
    assert not _holds_a_key({"name": text, "nodes": [{"name": "Note", "parameters": {"t": text}}]})
    assert KEY_SHAPE.sub(HIDDEN, text) == text
