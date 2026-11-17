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
HEX40 = "3f2a9c1e" * 5
# Each built at run time, so no secret scanner reads one as leaked. None is a real key.
KEYS = {
    "OpenAI project key": "sk-proj-" + "Ab3dEf9h" * 6,
    "Anthropic key": "sk-ant-api03-" + "Zx9_" * 10,
    "OpenAI key": "sk-" + "Q1w2E3r4" * 3,
    "OpenRouter key": "sk-or-v1-" + "3f2a9c1e" * 8,
    "Langfuse secret key": "sk-lf-" + UUID,
    "Entra client secret": "Q8k" + "8Q~" + ("Ab3_dEf9~h.K" * 3)[:34],
    "Stripe secret key": "sk_" + "live_" + "Ab3dEf9h" * 3,
    "npm token": "npm_" + ("Ab3dEf9h" * 5)[:36],
    "PyPI token": "pypi-" + "AgEIcHlwaS5vcmc" + "Ab3dEf9h_-" * 6,
    "Hugging Face token": "hf_" + ("Ab3dEf9h" * 5)[:34],
    "SonarQube token": "squ_" + HEX40,
    "GitHub classic token": "ghp_" + "Zx9" * 12,
    "GitHub OAuth token": "gho_" + "Zx9" * 12,
    "GitHub app token": "ghs_" + "Zx9" * 12,
    "GitHub fine-grained token": "github_pat_" + "Ab3_" * 6,
    "GitLab token": "glpat-" + "Ab3dEf9h" * 3,
    "GitLab runner token": "glrt-" + "Ab3dEf9h" * 3,
    "40 hex after token": "token: " + HEX40,
    "40 hex after a PAT": "my PAT " + HEX40,
    "bearer header": "Bearer " + "abc.123/" * 3,
    "bearer of letters only": "Bearer " + "abcdefghijklmnopqrstuvwxyz",
    "basic header": "Basic " + "dXNlcjpwYXNz=",
    "Azure OpenAI key header": "api-key: " + "3f2a9c1e" * 4,
    "API key header": "X-API-Key: " + "Ab3dEf9h" * 4,
    "token in an Authorization header": "Authorization: token " + "Ab3dEf9h" * 4,
    "password in a URL": "postgresql://app:" + "S3cr3tPassw0rd" + "@",
    "AWS access key id": "AKIA" + "Z7Q2" * 4,
    "AWS session key id": "ASIA" + "K3V9" * 4,
    "Slack bot token": "xoxb-" + "1234567890-" * 2 + "Ab3dEf9h" * 3,
    "Slack session token": "xoxc-" + "1234567890-" * 2 + "Ab3dEf9h" * 3,
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
    "commit " + HEX40 + " fixed it",
    "the key commit " + HEX40 + " was reverted",
    "token for commit " + HEX40,
    "password reset for commit " + HEX40,
    "short sha 3f2a9c1",
    "run 123e4567-e89b-12d3-a456-426614174000 failed",
    "move MOCK-123 and MOCK-4567 to done",
    "ask the team about this task",
    "set up a task-management-workflow for the risk-assessment-report",
    "desk-proj-tracker-2026-q1",
    "a basic understanding.",
    "set up a basic 2-step-approval-flow",
    "bearer instruments",
    "bearer instrumentation-ready",
    "a bearer authentication header",
    "secret santa 2026",
    "highs_and_lows_of_the_quarter",
    "assign the design=final sign-off",
    "the ASIA PACIFIC region",
    "see https://someone@example.com/path and http://localhost:8080/path",
    "hf_transfer and npm_config_cache and pypi-server",
    "Authorization: Bearer {{$json.accessToken}}",
]
BEFORE = {
    "space": " ",
    "underscore": "_",
    "digit": "7",
    "letter": "x",
    "backslash": "\\",
    "escaped backslash": "\\\\",
    "escaped quote": '\\"',
    "email escape": "=3D",
    "escaped newline": "\\n",
    "escaped tab": "\\t",
    "unicode escape": "\\u003d",
    "URL escape": "%3D",
    "equals": "=",
    "colon": ":",
    "quote": '"',
}
"""What may stand just before a key in what a person types or n8n sends back."""
GLUED_TO_A_WORD = ("OpenAI key",)
"""Keys read as part of a word when glued to a letter, as "sk-" is in "task-management-workflow".
The longer vendor forms, as sk-proj- and sk-lf-, are refused even glued."""
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
            r"(?i:bearer)\s+[\w.~+/=-]{8,}",
            r"(?i:basic)\s+(?=[A-Za-z0-9+/=]*[0-9+/=])[A-Za-z0-9+/=]{8,}",
            r"\b(?i:token|key|secret|sig|password|api[_-]?key)=[^&\s\"']{8,}",
            r"hooks\.slack\.com/services/\S+",
            r"webhook\.office\.com/\S+",
            r"\b[0-9a-f]{40}\b",
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*",
        )
    )
)
"""platform-api's shapes on main, every one of them, to show that no key they refused is let
through now, except what LET_THROUGH_ON_PURPOSE writes down."""
LET_THROUGH_ON_PURPOSE = {
    "a git commit's SHA": "commit " + HEX40 + " fixed it",
    "bearer before a plain word": "bearer instruments",
    "a bearer token of fewer than 24 letters only": "Bearer " + "abcdefghijklmnopq",
    "an sk- key of the short form glued to a letter": "x" + KEYS["OpenAI key"],
    "sk- glued to a word": "set up a task-management-workflow",
    "basic before a hyphenated phrase": "set up a basic 2-step-approval-flow",
}
"""What main refused and platform-api lets through now, on purpose. A shape dropped later has to
be written down here too."""
MAIN_EXAMPLES = [
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "ghp_" + "a" * 36,
    "Basic dXNlcjpwYXNzd29yZA==",
    "https://hooks.slack.com/services/T0/B0/abcDEF123456",
    "https://acme.webhook.office.com/webhookb2/abc@def/IncomingWebhook/123/456",
    "token=" + HEX40,
    *KEYS.values(),
]
"""The keys main's own tests used, and each key above."""
N = 100_000
PEM_BEGIN = "-----BEGIN " + "PRIVATE" + " KEY-----"
HOSTILE = {
    "sk-": "sk-" * (N // 3),
    "xsk-": "xsk-" * (N // 4),
    "sk-proj-": "sk-proj-" * (N // 8),
    "eyJ-": "eyJ-" * (N // 4),
    "_eyJ": "_eyJ" * (N // 4),
    "eyJ then letters": "eyJ" + "a" * N,
    "AKIA": "AKIA" * (N // 4),
    "xoxb-": "xoxb-" * (N // 5),
    "sig=": "sig=" * (N // 4),
    "token=": "token=" * (N // 6),
    "token: ": "token: " * (N // 7),
    "key then hex letters": "key " + "a" * N,
    "api-key: ": "api-key: " * (N // 9),
    "authorization: x ": "authorization: x " * (N // 17),
    "Authorization: token then letters": "Authorization: token " + "a" * N,
    "Q~": "Q~" * (N // 2),
    "digit then Q~": "a8Q~" * (N // 4),
    "://a:": "://a:" * (N // 5),
    "://a: then letters": "://a:" + "a" * N,
    "npm_": "npm_" * (N // 4),
    "BEGIN then letters": "-----BEGIN " + "A " * (N // 2),
    "END then letters": PEM_BEGIN + "-----END " + "A" * N,
    "BEGIN then backslashes": PEM_BEGIN + "\\" * N,
    "BEGIN then short lines": PEM_BEGIN + '"' + ('", "' + "A" * 15) * (N // 19),
    "BEGIN then field names": PEM_BEGIN + '"' + ('", "' + "A" * 20 + '": ') * (N // 27),
    "BEGIN then dashes": PEM_BEGIN + "-" * N,
    "token={{": "token={{" * (N // 8),
    "Bearer then spaces": "Bearer" + " " * N + "x",
    "Bearer then letters": "Bearer " + "a" * N,
    "basic ": "basic " * (N // 6),
    "escaped newlines": "\\n" * (N // 2),
    "backslash then eyJ-": "\\eyJ-" * (N // 5),
    "backslashes": "\\" * N,
    "URL escapes": "%41" * (N // 3),
    "email escapes": "=3D" * (N // 3),
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
            glued = where == "letter" and example == KEYS["OpenAI key"]
            if MAIN_SHAPES.search(text) and not glued:
                assert PASTED_KEY.search(text), text


@pytest.mark.parametrize("text", LET_THROUGH_ON_PURPOSE.values(), ids=list(LET_THROUGH_ON_PURPOSE))
def test_what_main_refused_and_is_let_through_now_is_written_down(text: str):
    assert MAIN_SHAPES.search(text)
    assert PASTED_KEY.search(text) is None


@pytest.mark.parametrize("shape", KEY_SHAPE_SOURCES)
def test_each_shape_reads_a_long_hostile_text_in_linear_time(shape: str):
    pattern = re.compile(shape)
    for name, text in HOSTILE.items():
        begun = time.perf_counter()
        pattern.sub(HIDDEN, text)
        took = time.perf_counter() - begun
        assert took < 0.1, f"{name}: {took:.3f}s"


PEM_LINES = [
    "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "MIIEow" + "Ab3d" * 15,
    "Zx9y" * 16,
    "Qr7t" * 4,
    "-----END " + "RSA PRIVATE" + " KEY-----",
]


@pytest.mark.parametrize(
    "text",
    ['"' + '\\n" + "'.join(PEM_LINES) + '"', json.dumps(PEM_LINES)],
    ids=["split by quotes", "a JSON array of lines"],
)
def test_a_private_key_split_into_lines_is_refused_and_hidden_line_by_line(text: str):
    assert PASTED_KEY.search(f"use {text} here")
    hidden = KEY_SHAPE.sub(HIDDEN, f"use {text} here")
    assert not any(line[-8:] in hidden for line in PEM_LINES[1:4])


@pytest.mark.parametrize(
    "value",
    ["abc{def0123456789", "abc\\def0123456789"],
    ids=["a brace inside", "a backslash inside"],
)
def test_a_key_in_a_query_or_header_is_refused_whatever_letters_it_holds(value: str):
    for text in (f"token={value}", f"api-key: {value}", f"Authorization: token {value}"):
        assert PASTED_KEY.search(text), text


@pytest.mark.parametrize(
    "text",
    ["token={{ $json.t }}", "token={{$json.token}}", "api-key: {{ $json.key }}"],
)
def test_an_n8n_expression_after_a_key_s_name_is_not_a_key(text: str):
    assert PASTED_KEY.search(text) is None


@pytest.mark.parametrize("text", PLAIN_WORDS)
def test_plain_words_are_never_refused_or_hidden(text: str):
    assert PASTED_KEY.search(text) is None
    assert not _holds_a_key({"name": text, "nodes": [{"name": "Note", "parameters": {"t": text}}]})
    assert KEY_SHAPE.sub(HIDDEN, text) == text
