"""Every shape of a key the agent runtime's masker knows, platform-api refuses too, in a
person's words, a typed answer and what comes back from n8n, and hides in a report (ADR 0051,
section 5). The two lists are held together by contracts/fixtures/agent/key-shapes.json, which
the runtime writes from its masker."""

import json
import re
import time

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
    "highs_and_lows_of_the_quarter",
    "assign the design=final sign-off",
    "the ASIA PACIFIC region",
]
BEFORE = {
    "space": " ",
    "underscore": "_",
    "digit": "7",
    "letter": "x",
    "escaped newline": "\\n",
    "escaped tab": "\\t",
    "unicode escape": "\\u003d",
    "URL escape": "%3D",
    "equals": "=",
    "colon": ":",
    "quote": '"',
}
"""What may stand just before a key in what a person types or n8n sends back."""
GLUED_TO_A_WORD = ("OpenAI project key", "OpenAI key", "Langfuse secret key")
"""Keys read as part of a word when glued to a letter, as "sk-" is in "task-management-workflow"."""
PLACED = [
    pytest.param(before, key, id=f"{name} after {where}")
    for name, key in KEYS.items()
    for where, before in BEFORE.items()
    if not (where == "letter" and name in GLUED_TO_A_WORD)
]
MAIN_SHAPES = re.compile(
    "|".join(
        (
            r"sk-ant-[A-Za-z0-9_\-]{8,}",
            r"sk-[A-Za-z0-9_\-]{16,}",
            r"gh[pousr]_[A-Za-z0-9]{16,}",
            r"github_pat_[A-Za-z0-9_]{16,}",
            r"(?i:bearer|basic)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}",
            r"sk-ant-[\w-]+",
            r"gh[pousr]_\w{16,}",
            r"github_pat_\w{16,}",
            r"glpat-[\w-]{16,}",
            r"xox[abposr]-[\w-]+",
            r"ATATT[\w=-]{16,}",
            r"AKIA[0-9A-Z]{16}",
            r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+",
            r"(?i:basic)\s+(?=[A-Za-z0-9+/=]*[0-9+/=])[A-Za-z0-9+/=]{8,}",
            r"\b(?i:token|key|secret|sig|password|api[_-]?key)=[^&\s\"']{8,}",
            r"hooks\.slack\.com/services/\S+",
            r"webhook\.office\.com/\S+",
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*",
        )
    )
)
"""platform-api's shapes on main, to show that no key they refused is let through now. Left out on
purpose: 40 hex letters, which a git commit's SHA also is, and a bearer shape that refused "bearer
instruments"."""
MAIN_EXAMPLES = [
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "ghp_" + "a" * 36,
    "Basic dXNlcjpwYXNzd29yZA==",
    "https://hooks.slack.com/services/T0/B0/abcDEF123456",
    "https://acme.webhook.office.com/webhookb2/abc@def/IncomingWebhook/123/456",
    *KEYS.values(),
]
"""The keys main's own tests used, and each key above."""
N = 100_000
HOSTILE = {
    "sk-": "sk-" * (N // 3),
    "xsk-": "xsk-" * (N // 4),
    "eyJ-": "eyJ-" * (N // 4),
    "_eyJ": "_eyJ" * (N // 4),
    "eyJ then letters": "eyJ" + "a" * N,
    "AKIA": "AKIA" * (N // 4),
    "xoxb-": "xoxb-" * (N // 5),
    "sig=": "sig=" * (N // 4),
    "token=": "token=" * (N // 6),
    "BEGIN then letters": "-----BEGIN " + "A " * (N // 2),
    "END then letters": "-----BEGIN PRIVATE KEY-----" + "-----END " + "A" * N,
    "Bearer then spaces": "Bearer" + " " * N + "x",
    "basic ": "basic " * (N // 6),
    "escaped newlines": "\\n" * (N // 2),
    "URL escapes": "%41" * (N // 3),
    "letters": "a" * N,
    "hyphens": "-" * N,
}
"""Long texts that would make a shape read the same letters again and again, if it could."""


def test_platform_api_refuses_every_shape_the_runtime_masks():
    shapes = json.loads((FIXTURES / "agent" / "key-shapes.json").read_text())["shapes"]
    assert shapes, "the runtime writes its masker's shapes"
    assert set(shapes) <= set(KEY_SHAPE_SOURCES)


@pytest.mark.parametrize(("before", "key"), PLACED)
def test_each_shape_is_refused_typed_or_read_back_and_hidden_in_a_report(before: str, key: str):
    placed = before + key
    assert PASTED_KEY.search(f"post it with {placed} please")
    assert _holds_a_key({"name": "x", "nodes": [{"name": "Call", "parameters": {"url": placed}}]})
    hidden = KEY_SHAPE.sub(HIDDEN, f"the words {placed} here")
    assert key not in hidden and key[-8:] not in hidden


def test_nothing_main_refused_is_let_through_wherever_it_sits():
    for example in MAIN_EXAMPLES:
        for where, before in BEFORE.items():
            text = f"post it with {before}{example} please"
            glued = where == "letter" and re.match(r"sk-(?!ant-)", example) is not None
            if MAIN_SHAPES.search(text) and not glued:
                assert PASTED_KEY.search(text), text


@pytest.mark.parametrize("shape", KEY_SHAPE_SOURCES)
def test_each_shape_reads_a_long_hostile_text_in_linear_time(shape: str):
    pattern = re.compile(shape)
    for name, text in HOSTILE.items():
        begun = time.perf_counter()
        pattern.sub(HIDDEN, text)
        took = time.perf_counter() - begun
        assert took < 0.1, f"{name}: {took:.3f}s"


@pytest.mark.parametrize("text", PLAIN_WORDS)
def test_plain_words_are_never_refused_or_hidden(text: str):
    assert PASTED_KEY.search(text) is None
    assert not _holds_a_key({"name": text, "nodes": [{"name": "Note", "parameters": {"t": text}}]})
    assert KEY_SHAPE.sub(HIDDEN, text) == text
