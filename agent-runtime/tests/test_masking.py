import json

import pytest

from agent_runtime.monitoring.masking import GRACE_SECONDS, MASKED, Masker


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


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_held_secret_is_masked_until_its_trace_ends_and_for_the_grace_after():
    clock = Clock()
    masker = Masker(clock=clock)
    held = masker.hold("callback-token-first", None, "short")
    assert held is not None and held == ("callback-token-first",)
    clock.now += GRACE_SECONDS * 10
    assert masker.mask("callback-token-first") == MASKED
    masker.release(held)
    clock.now += GRACE_SECONDS - 1
    assert masker.mask("callback-token-first") == MASKED
    clock.now += 1
    assert masker.mask("callback-token-first") == "callback-token-first"
    assert masker.holding == 0


def test_a_secret_held_by_two_traces_stays_until_both_end():
    clock = Clock()
    masker = Masker(clock=clock)
    first, second = masker.hold("model-key-shared"), masker.hold("model-key-shared")
    assert first is not None and second is not None
    masker.release(first)
    clock.now += GRACE_SECONDS * 2
    assert masker.mask("model-key-shared") == MASKED
    masker.release(second)
    clock.now += GRACE_SECONDS
    assert masker.holding == 0


def test_past_the_limit_a_hold_is_refused_and_nothing_held_is_let_go():
    clock = Clock()
    masker = Masker(limit=2, clock=clock)
    first = masker.hold("secret-one-1234")
    assert masker.hold("secret-two-1234") is not None
    assert masker.hold("secret-three-12") is None
    again = masker.hold("secret-one-1234")
    assert masker.mask("secret-one-1234 secret-two-1234") == f"{MASKED} {MASKED}"
    assert first is not None and again is not None
    masker.release(first)
    masker.release(again)
    assert masker.hold("secret-three-12") is None
    clock.now += GRACE_SECONDS
    assert masker.hold("secret-three-12") is not None
