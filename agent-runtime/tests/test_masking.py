import json
import re

import pytest
from pydantic import BaseModel

from agent_runtime.monitoring.masking import KEY_SHAPE_SOURCES, KEY_SHAPES, MASKED, Masker

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
    "OpenAI project key": "sk-proj-" + "Ab3dEf9h" * 6,
    "Langfuse secret key": "sk-lf-" + UUID,
    "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "Ab3dEf9h-_" * 3,
    "bearer header": "Bearer " + "abc.123/" * 3,
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
    "set up a task-management-workflow for the risk-assessment-report",
    "ask-the-team-before-merging and the desk-booking-workflow",
    "a basic understanding.",
    "set up a basic 2-step-approval-flow",
    "bearer instruments",
    "sk-short",
    "see https://github.com/langchain-ai/langgraph/releases/tag/0.2.34",
    "-----BEGIN " + "PUBLIC KEY-----",
]


@pytest.mark.parametrize("key", KEYS.values(), ids=list(KEYS))
def test_each_key_the_team_pastes_is_masked_to_its_end(key: str):
    masked = Masker().mask(f"keep {key} words")
    assert MASKED in masked and key[-8:] not in masked
    assert masked.startswith("keep ") and masked.endswith(" words")


def test_a_private_key_block_is_masked_to_its_end_line_or_to_the_end_of_the_text():
    assert Masker().mask(f"here {PEM} thanks") == f"here {MASKED} thanks"
    cut = PEM.split("\n-----END")[0]
    assert Masker().mask(f"here {cut}") == f"here {MASKED}"


@pytest.mark.parametrize("text", PLAIN_WORDS)
def test_plain_words_never_look_like_a_key(text: str):
    assert KEY_SHAPES.search(text) is None
    assert Masker().mask(text) == text


@pytest.mark.parametrize("shape", KEY_SHAPE_SOURCES)
def test_no_shape_repeats_a_group_so_each_runs_in_linear_time(shape: str):
    assert re.search(r"\)[*+?{]", shape) is None


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
