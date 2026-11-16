import json

import pytest
from pydantic import BaseModel

from agent_runtime.monitoring.masking import MASKED, Masker


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
            "AGENT_SUMMARY_MODEL": "claude-haiku-5-5",
            "SHORT_KEY": "abc",
        }
    )
    text = "plain-token-value-1 gateway-key-value-2 lf-secret-value-3 db-password-value-4 abc"
    assert masker.mask(text) == " ".join([MASKED] * 4 + ["abc"])
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
