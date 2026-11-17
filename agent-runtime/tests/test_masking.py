import json
import re
import time

import pytest
from pydantic import BaseModel

from agent_runtime.monitoring.masking import (
    GLUED_SK_KEY,
    KEY_SHAPE_SOURCES,
    KEY_SHAPES,
    MASKED,
    Masker,
)

UUID = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
# Each fake is built at run time, so no secret scanner reads one as leaked. None is a real key.
KEYS = {
    "AWS access key id": "AKIA" + "Z7Q2" * 4,
    "AWS session key id": "ASIA" + "K3V9" * 4,
    "GitHub classic token": "ghp_" + "Zx9" * 12,
    "GitHub OAuth token": "gho_" + "Zx9" * 12,
    "GitHub user token": "ghu_" + "Zx9" * 12,
    "GitHub app token": "ghs_" + "Zx9" * 12,
    "GitHub refresh token": "ghr_" + "Zx9" * 12,
    "GitHub fine-grained token": "github_pat_" + "11AB3DEF0_" + "Zx9" * 20,
    "GitLab token": "glpat-" + "Ab3dEf9h" * 3,
    "Slack bot token": "xoxb-" + "1234567890-" * 2 + "Ab3dEf9h" * 3,
    "Slack user token": "xoxp-" + "1234567890-" * 3 + "Ab3dEf9h" * 4,
    "Slack app token": "xoxa-" + "2-1234567890-" + "Ab3dEf9h" * 3,
    "Slack refresh token": "xoxr-" + "1234567890-" + "Ab3dEf9h" * 3,
    "Slack app-level token": "xapp-" + "1-A0B1C2D3E4F-1234567890123-" + "ab3d" * 16,
    "Slack webhook": "https://hooks.slack.com/" + "services/T0AB12CD3/B0EF45GH6/" + "Xy7" * 8,
    "Teams webhook": f"https://contoso.webhook.office.com/webhookb2/{UUID}@{UUID}/IncomingWebhook/"
    + "ab12" * 8
    + f"/{UUID}",
    "Atlassian API token": "ATATT3" + "xFfGF0" + "Ab3_dEf9-" * 20 + "=1A2B3C4D",
    "Google API key": "AIza" + "Sy" + "Ab3dEf9h" * 4 + "Z",
    "Azure storage key": "AccountKey=" + "Ab3d+Ef9/" * 9 + "Ab==",
    "Azure Service Bus key": "SharedAccessKey=" + "Ab3d+Ef9/" * 5,
    "Azure SAS signature": "sig=" + "Ab3dEf9h%2B" * 4 + "%3D",
    "Power Automate signature": "sig=" + "Ab3_dEf9-h" * 4 + "Xyz",
    "Anthropic key": "sk-ant-" + "api03-" + "Zx9_" * 10,
    "OpenAI project key": "sk-proj-" + "Ab3dEf9h_-" * 16,
    "OpenAI service account key": "sk-svcacct-" + "Ab3dEf9h_-" * 8,
    "OpenAI legacy key": "sk-" + "Q1w2E3r4" * 6,
    "OpenRouter key": "sk-or-v1-" + "3f2a9c1e" * 8,
    "Langfuse secret key": "sk-lf-" + UUID,
    "Entra client secret": "Q8k" + "8Q~" + ("Ab3_dEf9~h.K" * 3)[:34],
    "Stripe secret key": "sk_" + "live_" + "Ab3dEf9h" * 3,
    "Stripe restricted key": "rk_" + "test_" + "Ab3dEf9h" * 3,
    "npm token": "npm_" + ("Ab3dEf9h" * 5)[:36],
    "PyPI token": "pypi-" + "AgEIcHlwaS5vcmc" + "Ab3dEf9h_-" * 6,
    "Hugging Face token": "hf_" + ("Ab3dEf9h" * 5)[:34],
    "SonarQube token": "squ_" + "3f2a9c1e" * 5,
    "Slack session token": "xoxc-" + "1234567890-" * 2 + "Ab3dEf9h" * 3,
    "Slack session cookie": "xoxd-" + "%2FAb3dEf9h%2B" * 4,
    "GitLab runner token": "glrt-" + "Ab3dEf9h" * 3,
    "40 hex after token": "token: " + "3f2a9c1e" * 5,
    "password in a URL": "postgresql://app:" + "S3cr3tPassw0rd" + "@",
    "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "Ab3dEf9h-_" * 3,
    "bearer header": "Bearer " + "abc.123/" * 3,
    "bearer of letters only": "Bearer " + "abcdefghijklmnopqrstuvwxyz",
    "basic header": "Basic " + "dXNlcjpwYXNz=",
}
PEM = (
    "-----BEGIN " + "RSA PRIVATE" + " KEY-----\nMIIEow" + "Ab3d" * 16 + "\n"
    "-----END " + "RSA PRIVATE" + " KEY-----"
)
PLAIN_WORDS = [
    "langgraph 0.2.34 is out",
    "upgrade node to v22.11.0-rc.1",
    "release 2024.11.18 and 1.0.0-alpha.3",
    "commit " + "3f2a9c1e" * 5 + " fixed it",
    "short sha 3f2a9c1",
    "run 123e4567-e89b-12d3-a456-426614174000 failed",
    "move MOCK-123 and MOCK-4567 to done",
    "ask the team about this task",
    "a basic understanding.",
    "set up a basic 2-step-approval-flow",
    "bearer instruments",
    "sk-short",
    "see https://github.com/langchain-ai/langgraph/releases/tag/0.2.34",
    "-----BEGIN " + "PUBLIC KEY-----",
    "highs_and_lows_of_the_quarter",
    "assign the design=final sign-off",
    "xoxo, see you soon",
    "the ASIA PACIFIC region",
    "the key commit " + "3f2a9c1e" * 5 + " was reverted",
    "token for commit " + "3f2a9c1e" * 5,
    "password reset for commit " + "3f2a9c1e" * 5,
    "a bearer authentication header",
    "bearer instrumentation-ready",
    "secret santa 2026",
    "see https://someone@example.com/path and http://localhost:8080/path",
    "hf_transfer and npm_config_cache and pypi-server",
]
WORDS_LIKE_A_GLUED_KEY = [
    "set up a task-management-workflow for the risk-assessment-report",
    "ask-the-team-before-merging and the desk-booking-workflow",
    "desk-proj-tracker-2026-q1",
]
"""Words that hold "sk-" glued to a letter. They are never refused, but the masker hides them."""
BEFORE = {
    "space": " ",
    "underscore": "_",
    "digit": "7",
    "letter": "x",
    "backslash": "\\",
    "JSON backslash": "\\\\",
    "JSON quote": '\\"',
    "JSON newline": "\\n",
    "JSON tab": "\\t",
    "JSON unicode escape": "\\u003d",
    "URL escape": "%3D",
    "email escape": "=3D",
    "equals": "=",
    "colon": ":",
    "quote": '"',
}
"""What may stand just before a key in text the masker sees. Serialised JSON writes a newline as
two characters, a backslash and then a letter."""
GLUED_TO_A_WORD = ("OpenAI legacy key",)
"""Keys read as part of a word when glued to a letter, as "sk-" is in "task-management-workflow",
so they are not refused there. The masker still hides them. The longer vendor forms, as sk-proj-
and sk-lf-, are refused even glued."""
PLACED = [
    pytest.param(before, key, id=f"{name} after {where}")
    for name, key in KEYS.items()
    for where, before in BEFORE.items()
]
MAIN_SHAPES = re.compile(
    "|".join(
        (
            r"sk-ant-[A-Za-z0-9_\-]{8,}",
            r"sk-[A-Za-z0-9_\-]{16,}",
            r"gh[pousr]_[A-Za-z0-9]{16,}",
            r"github_pat_[A-Za-z0-9_]{16,}",
            r"(?i:bearer|basic)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}",
        )
    )
)
"""The masker's shapes on main before this list grew, to show that nothing they caught is lost."""
MAIN_EXAMPLES = [
    "sk-ant-api03-abcDEF123_-xyz",
    "sk-proj-0123456789abcdefABCD",
    "ghp_0123456789abcdefABCDEF0123",
    "Bearer eyJhbGciOi.eyJzdWIi.c2ln",
    "basic dXNlcjpwYXNz=",
    "sk-ant-api03-FAKEKEYFAKEKEY",
    "sk-ant-example-not-a-key",
    "ghp_plantedINmetadata01",
    "ghp_ABCDEFGHIJKLMNOPQRSTUV",
    *KEYS.values(),
]
"""The keys main's own tests used, and each key above."""
N = 100_000
PEM_BEGIN = "-----BEGIN " + "PRIVATE" + " KEY-----"
HOSTILE = {
    "sk-": "sk-" * (N // 3),
    "xsk-": "xsk-" * (N // 4),
    "task-": "task-" * (N // 5),
    "eyJ-": "eyJ-" * (N // 4),
    "_eyJ": "_eyJ" * (N // 4),
    "eyJ.": "eyJ." * (N // 4),
    "eyJ then letters": "eyJ" + "a" * N,
    "x.eyJ": "x.eyJ" * (N // 5),
    "AKIA": "AKIA" * (N // 4),
    "xoxb-": "xoxb-" * (N // 5),
    "Slack webhook": "hooks.slack.com/services/" * (N // 25),
    "sig=": "sig=" * (N // 4),
    "AccountKey=": "AccountKey=" * (N // 11),
    "BEGIN": "-----BEGIN " * (N // 11),
    "BEGIN then letters": "-----BEGIN " + "A " * (N // 2),
    "END then letters": PEM_BEGIN + "-----END " + "A" * N,
    "bearer ": "bearer " * (N // 7),
    "Bearer then letters": "Bearer " + "a" * N,
    "Bearer then spaces": "Bearer" + " " * N + "x",
    "basic ": "basic " * (N // 6),
    "JSON newlines": "\\n" * (N // 2),
    "JSON newline then eyJ-": "\\neyJ-" * (N // 6),
    "backslash then eyJ-": "\\eyJ-" * (N // 5),
    "backslash then sk-": "\\sk-" * (N // 4),
    "backslashes": "\\" * N,
    "URL escapes": "%41" * (N // 3),
    "email escapes": "=3D" * (N // 3),
    "JSON unicode escapes": "\\u0041" * (N // 6),
    "JSON unicode escape then eyJ-": "\\u0041eyJ-" * (N // 10),
    "Q~": "Q~" * (N // 2),
    "digit then Q~": "a8Q~" * (N // 4),
    "token: ": "token: " * (N // 7),
    "key then hex letters": "key " + "a" * N,
    "://a:": "://a:" * (N // 5),
    ":// then letters": "://" + "a" * N,
    "://a: then letters": "://a:" + "a" * N,
    "sk_live_": "sk_live_" * (N // 8),
    "npm_": "npm_" * (N // 4),
    "hf_": "hf_" * (N // 3),
    "squ_": "squ_" * (N // 4),
    "pypi-": "pypi-AgEIcHlwaS5vcmc" * (N // 20),
    "sk-proj-": "sk-proj-" * (N // 8),
    "BEGIN then backslashes": PEM_BEGIN + "\\" * N,
    "BEGIN then separators": PEM_BEGIN + '"' + '", +' * (N // 4),
    "BEGIN then short lines": PEM_BEGIN + '"' + ('", "' + "A" * 15) * (N // 19),
    "BEGIN then long lines": PEM_BEGIN + '"' + ('", "' + "A" * 20) * (N // 24),
    "BEGIN then field names": PEM_BEGIN + '"' + ('", "' + "A" * 20 + '": ') * (N // 27),
    "BEGIN then dashes": PEM_BEGIN + "-" * N,
    "BEGIN then END marks": PEM_BEGIN + "-----END " * (N // 9),
    "xoxd-%2F": "xoxd-%2F" * (N // 8),
    "glrt-": "glrt-" * (N // 5),
    "letters": "a" * N,
    "hyphens": "-" * N,
    "underscores": "_" * N,
}
"""Long texts that would make a shape read the same letters again and again, if it could."""


@pytest.mark.parametrize(("before", "key"), PLACED)
def test_each_key_is_masked_to_its_end_wherever_it_sits(before: str, key: str):
    masked = Masker().mask(f"keep {before}{key} words")
    assert MASKED in masked and key[-8:] not in masked
    assert masked.startswith("keep ") and masked.endswith(" words")


@pytest.mark.parametrize(("before", "key"), PLACED)
def test_each_key_is_refused_wherever_it_sits_unless_an_sk_key_is_glued_to_a_letter(
    before: str, key: str
):
    glued = before == BEFORE["letter"] and key in (KEYS[name] for name in GLUED_TO_A_WORD)
    assert (KEY_SHAPES.search(f"keep {before}{key} words") is None) == glued


@pytest.mark.parametrize("key", KEYS.values(), ids=list(KEYS))
@pytest.mark.parametrize(
    "before",
    ["\n", "\t", "_", "\\", '"', "\\n"],
    ids=["newline", "tab", "underscore", "backslash", "quote", "backslash then n"],
)
def test_a_key_in_serialised_json_is_masked_and_the_json_still_reads(before: str, key: str):
    note = json.loads(Masker().mask(json.dumps({"note": f"line{before}{key}"})))["note"]
    assert MASKED in note and key[-8:] not in note


def test_nothing_main_s_shapes_caught_is_lost_wherever_it_sits():
    masker = Masker()
    for example in MAIN_EXAMPLES:
        for before in BEFORE.values():
            text = f"keep {before}{example} words"
            if MAIN_SHAPES.search(text):
                assert masker.mask(text) != text, text


def test_a_private_key_block_is_masked_to_its_end_line_or_to_the_end_of_the_text():
    assert Masker().mask(f"here {PEM} thanks") == f"here {MASKED} thanks"
    cut = PEM.split("\n-----END")[0]
    assert Masker().mask(f"here {cut}") == f"here {MASKED}"
    note = json.loads(Masker().mask(json.dumps({"note": f"here {PEM} thanks"})))["note"]
    assert note == f"here {MASKED} thanks"


def test_a_private_key_without_its_end_line_is_masked_only_to_the_end_of_its_json_string():
    """Langfuse's input is a whole JSON document, so the fields after the key must survive."""
    cut = PEM.split("\n-----END")[0]
    once = json.dumps({"input": cut, "other": 1})
    assert json.loads(Masker().mask(once)) == {"input": MASKED, "other": 1}
    twice = json.dumps(once)
    assert json.loads(json.loads(Masker().mask(twice))) == {"input": MASKED, "other": 1}
    long_name = json.dumps({"input": cut, "configurationValues": 1})
    assert json.loads(Masker().mask(long_name)) == {"input": MASKED, "configurationValues": 1}


PEM_LINES = [
    "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "MIIEow" + "Ab3d" * 15,
    "Zx9y" * 16,
    "Qr7t" * 4,
    "-----END " + "RSA PRIVATE" + " KEY-----",
]


def test_a_private_key_split_by_quotes_is_masked_through_every_line():
    joined = '"' + '\\n" + "'.join(PEM_LINES) + '"'
    masked = Masker().mask(f"key = {joined};")
    assert not any(line[-8:] in masked for line in PEM_LINES[1:4])


def test_a_private_key_as_a_json_array_of_lines_is_masked_and_the_json_still_reads():
    data = json.loads(Masker().mask(json.dumps({"key": PEM_LINES, "configurationValues": 1})))
    assert data["configurationValues"] == 1
    assert not any(line[-8:] in json.dumps(data) for line in PEM_LINES[1:4])


@pytest.mark.parametrize("text", PLAIN_WORDS)
def test_plain_words_never_look_like_a_key(text: str):
    assert KEY_SHAPES.search(text) is None
    assert Masker().mask(text) == text


@pytest.mark.parametrize("text", WORDS_LIKE_A_GLUED_KEY)
def test_words_like_a_glued_key_are_never_refused_but_the_masker_hides_them(text: str):
    """A few hidden letters in a trace cost less than a leaked key."""
    assert KEY_SHAPES.search(text) is None
    assert MASKED in Masker().mask(text)


@pytest.mark.parametrize("shape", [*KEY_SHAPE_SOURCES, GLUED_SK_KEY])
def test_each_shape_reads_a_long_hostile_text_in_linear_time(shape: str):
    pattern = re.compile(shape)
    for name, text in HOSTILE.items():
        begun = time.perf_counter()
        pattern.sub(MASKED, text)
        took = time.perf_counter() - begun
        assert took < 0.1, f"{name}: {took:.3f}s"


def test_the_masker_reads_a_long_hostile_text_in_linear_time():
    masker = Masker(["callback-token-first"])
    for name, text in HOSTILE.items():
        begun = time.perf_counter()
        masker.mask(text)
        took = time.perf_counter() - begun
        assert took < 0.1, f"{name}: {took:.3f}s"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("my key is sk-ant-api03-abcDEF123_-xyz", f"my key is {MASKED}"),
        ("openai sk-proj-0123456789abcdefABCD", f"openai {MASKED}"),
        ("token ghp_0123456789abcdefABCDEF0123", f"token {MASKED}"),
        ("Authorization: Bearer eyJhbGciOi.eyJzdWIi.c2ln", f"Authorization: {MASKED}"),
        ("Authorization: basic dXNlcjpwYXNz=", f"Authorization: {MASKED}"),
        ("a basic understanding.", "a basic understanding."),
        ("bearer instruments", "bearer instruments"),
        ("sk-short", "sk-short"),
    ],
)
def test_a_known_key_shape_is_masked_and_plain_words_are_not(text: str, masked: str):
    assert Masker().mask(text) == masked


def test_every_secret_setting_is_masked_by_its_exact_value_and_others_are_not():
    masker = Masker.from_env(
        {
            "GITHUB_TOKEN": "plain-token-value-1",
            "AGENT_MODEL_API_KEY": "gateway-key-value-2",
            "LANGFUSE_SECRET_KEY": "lf-secret-value-3",
            "N8N_DB_PASSWORD": "db-password-value-4",
            "COSMOS_CONNECTION_STRING": "AccountKey=connection-value-5",
            "AGENT_SUMMARY_MODEL": "claude-haiku-5-5",
            "SHORT_KEY": "abc",
        }
    )
    text = (
        "plain-token-value-1 gateway-key-value-2 lf-secret-value-3 db-password-value-4 "
        "AccountKey=connection-value-5 abc"
    )
    assert masker.mask(text) == " ".join([MASKED] * 5 + ["abc"])
    assert masker.mask("claude-haiku-5-5") == "claude-haiku-5-5"


def test_a_secret_inside_json_text_is_masked_with_its_escapes():
    masker = Masker(['quote"and\\slash-secret'])
    encoded = json.dumps({"note": 'quote"and\\slash-secret'})
    assert json.loads(masker.mask(encoded)) == {"note": MASKED}


def test_a_held_secret_is_masked_until_every_trace_holding_it_lets_it_go():
    masker = Masker()
    first = masker.hold("callback-token-first", None, "short")
    assert first == ("callback-token-first",)
    second = masker.hold("callback-token-first")
    masker.release(first)
    assert masker.mask("callback-token-first") == MASKED
    masker.release(second)
    assert masker.mask("callback-token-first") == "callback-token-first"


class Note(BaseModel):
    text: str


def test_every_string_in_a_spans_data_is_masked_before_the_span_holds_it():
    masker = Masker()
    masker.hold("callback-token-first")
    data = {
        "messages": [{"role": "user", "content": "token callback-token-first"}],
        "args": ("Bearer abc123def456", 3, None),
        "note": Note(text="callback-token-first"),
    }
    assert masker.mask_data(data) == {
        "messages": [{"role": "user", "content": f"token {MASKED}"}],
        "args": [MASKED, 3, None],
        "note": {"text": MASKED},
    }
