import base64
import json
from pathlib import Path
from typing import Any

import pytest
from evals.providers import Target, plan
from evals.runner import MIN_FRAGMENT, main, redact

# Recognisable values. None of them is a real secret.
USER = "bake%40off-user"  # percent-encoded "bake@off-user"
PASSWORD = "pass%2Fword-9"  # percent-encoded "pass/word-9"
OLLAMA = f"http://{USER}:{PASSWORD}@ollama-box-9.private.example:11434"
ENDPOINT = "https://bakeoff-res-9.openai.azure.com/"
SECRETS = {
    "OLLAMA_BASE_URL": OLLAMA,
    "AZURE_OPENAI_ENDPOINT": ENDPOINT,
    "AZURE_OPENAI_API_KEY": "azure-key-value-9",
    "ANTHROPIC_API_KEY": "anthropic-key-value-9",
    "GOOGLE_API_KEY": "google-key-value-9",
}
FORMS = {
    "whole URL": OLLAMA,
    "host and port with the user": f"{USER}:{PASSWORD}@ollama-box-9.private.example:11434",
    "host name": "ollama-box-9.private.example",
    "first label of the host": "ollama-box-9",
    "user name": USER,
    "decoded user name": "bake@off-user",
    "password": PASSWORD,
    "decoded password": "pass/word-9",
    "basic auth": base64.b64encode(b"bake@off-user:pass/word-9").decode(),
    "basic auth, encoded parts": base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode(),
    "Azure endpoint": ENDPOINT,
    "Azure host": "bakeoff-res-9.openai.azure.com",
    "Azure resource name": "bakeoff-res-9",
    "Azure key": "azure-key-value-9",
}


@pytest.mark.parametrize("form", FORMS.values(), ids=list(FORMS))
def test_redact_removes_every_form_of_a_secret(form: str) -> None:
    assert form not in redact(f"failed near {form} after 3 tries", SECRETS)


def test_redact_keeps_short_fragments_so_the_message_stays_readable() -> None:
    env = {"OLLAMA_BASE_URL": "http://a:pw@db:11434"}
    message = "a request to the database failed"
    assert redact(message, env) == message
    assert len("pw") < MIN_FRAGMENT


def test_redact_removes_a_whole_secret_however_short() -> None:
    assert redact("key=k9", {"GOOGLE_API_KEY": "k9"}) == "key=[redacted]"


def test_redact_hides_values_that_pydantic_echoes_cut_short() -> None:
    message = (
        "1 validation error for AzureChatOpenAI\n  Value error [type=value_error, "
        "input_value={'azure_endpoint': 'https://zz-unlisted-9...', 'api_key': 'sec'}, "
        "input_type=dict]"
    )
    cleaned = redact(message, {})
    assert "zz-unlisted-9" not in cleaned
    assert "validation error for AzureChatOpenAI" in cleaned


def test_a_malformed_ollama_address_is_planned_as_not_run() -> None:
    targets, not_run = plan({"OLLAMA_BASE_URL": "http://user-9:secret-pw-9@[::1:11434"})
    assert targets == []
    assert {n.model for n in not_run if n.provider == "ollama"} == {
        "gemma:2b",
        "deepseek-r1:latest",
    }


PROVIDER_ENVS = {
    "ollama": {"OLLAMA_BASE_URL": "http://user-9:secret-pw-9@[ollama-box-9.private.example:11434"},
    "azure_openai": {
        "AZURE_OPENAI_API_KEY": "azure-key-value-9",
        "AZURE_OPENAI_ENDPOINT": "htps:/bakeoff-res-9 .openai.azure.com",
        "AZURE_OPENAI_API_VERSION": "2026-01-01",
        "AZURE_OPENAI_DEPLOYMENTS": "d1",
    },
    "anthropic": {"ANTHROPIC_API_KEY": "anthropic-key-value-9"},
    "google_genai": {"GOOGLE_API_KEY": "google-key-value-9", "GOOGLE_MODELS": "g1"},
}


@pytest.mark.parametrize("provider", list(PROVIDER_ENVS))
def test_a_model_or_judge_that_cannot_be_built_is_not_run_and_leaks_nothing(
    provider: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = PROVIDER_ENVS[provider]

    def refuse(self: Target, **overrides: Any) -> Any:
        echoed = ", ".join(f"{k}={v!r}" for k, v in env.items())
        raise ValueError(f"1 validation error for {self.provider}: bad settings {echoed}")

    # The cloud packages are not in the test environment, so this stands in for their
    # constructors, which echo the settings they were given.
    monkeypatch.setattr(Target, "build", refuse)
    if provider == "ollama":
        monkeypatch.setattr("evals.providers._ollama_models", lambda base_url: {"gemma:2b"})
    out = tmp_path / "results.json"

    assert main(out, {**env, "EVAL_JUDGE": f"{provider}:judge-model"}) == 0

    report = json.loads(out.read_text())
    assert report["results"] == []
    assert provider in {n["provider"] for n in report["not_run"]}
    captured = capsys.readouterr()
    written = out.read_text() + captured.out + captured.err
    for value in env.values():
        if value not in {"2026-01-01", "d1", "g1"}:
            assert value not in written
    for fragment in ("secret-pw-9", "ollama-box-9", "bakeoff-res-9", "user-9"):
        assert fragment not in written
