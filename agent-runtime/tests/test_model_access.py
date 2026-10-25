from collections.abc import Callable, Iterable, Iterator

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.addresses import AddressPolicy, AddressRefusedError
from agent_runtime.contract import (
    Connected,
    ConnectRequest,
    ModelAccess,
    ModelProblem,
    ModelTestPassed,
)
from agent_runtime.guarded import GuardedModels
from agent_runtime.model_access import ModelProbe, chat_for, problem_for
from agent_runtime.summary import ModelFactory

KEY = "sk-example-key-not-real-x7"
ANTHROPIC_LIST = {
    "data": [
        {"type": "model", "id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5"},
        {"type": "model", "id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"},
    ],
    "has_more": False,
}
OPENAI_LIST = {
    "object": "list",
    "data": [
        {"id": "gpt-5-mini", "object": "model", "owned_by": "openai"},
        {"id": "text-embedding-3-small", "object": "model", "owned_by": "openai"},
        {"id": "gpt-5", "object": "model", "owned_by": "openai"},
    ],
}


def public(host: str) -> Iterable[str]:
    return ["8.8.8.8"]


class Provider:
    """Answers the model list at one path, as a provider or gateway would."""

    def __init__(self, path: str, body: object, status: int = 200) -> None:
        self.path = path
        self.body = body
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path != self.path:
            return httpx.Response(404, json={"error": "not here"})
        return httpx.Response(self.status, json=self.body)


def probe_for(provider: Callable[[httpx.Request], httpx.Response]) -> ModelProbe:
    client = httpx.Client(transport=httpx.MockTransport(provider), follow_redirects=False)
    return ModelProbe(AddressPolicy(resolver=public), client=client)


def connect(probe: ModelProbe, base_url: str, key: str = KEY):
    return probe.connect(ConnectRequest(base_url=base_url, api_key=key))


def test_an_anthropic_style_list_is_detected_and_keeps_the_root_address():
    provider = Provider("/v1/models", ANTHROPIC_LIST)
    found = connect(probe_for(provider), "https://llm-gateway.example/")
    assert isinstance(found, Connected)
    assert found.style == "anthropic"
    assert found.base_url == "https://llm-gateway.example"
    assert [(m.id, m.display, m.suggested) for m in found.models] == [
        ("claude-haiku-5-5", "Claude Haiku 5.5", True),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5", False),
    ]


def test_an_openai_style_list_is_detected_and_keeps_the_v1_address():
    provider = Provider("/v1/models", OPENAI_LIST)
    found = connect(probe_for(provider), "https://api.example")
    assert isinstance(found, Connected)
    assert found.style == "openai"
    assert found.base_url == "https://api.example/v1"


def test_models_that_cannot_write_text_are_left_out():
    found = connect(probe_for(Provider("/v1/models", OPENAI_LIST)), "https://api.example/v1")
    assert isinstance(found, Connected)
    assert [m.id for m in found.models] == ["gpt-5-mini", "gpt-5"]


def test_a_list_that_lives_under_the_address_itself_is_found():
    provider = Provider("/v1beta/openai/models", OPENAI_LIST)
    found = connect(probe_for(provider), "https://gemini.example/v1beta/openai")
    assert isinstance(found, Connected)
    assert found.base_url == "https://gemini.example/v1beta/openai"


def test_an_address_ending_in_v1_is_asked_once_and_anthropic_drops_the_v1():
    provider = Provider("/v1/models", ANTHROPIC_LIST)
    found = connect(probe_for(provider), "https://llm-gateway.example/v1")
    assert isinstance(found, Connected)
    assert found.base_url == "https://llm-gateway.example"
    assert len(provider.requests) == 1


def test_the_key_goes_in_both_header_styles_and_never_in_the_url():
    provider = Provider("/v1/models", ANTHROPIC_LIST)
    connect(probe_for(provider), "https://llm-gateway.example")
    sent = provider.requests[0]
    assert sent.headers["x-api-key"] == KEY
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(sent.url)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_is_reported_in_plain_words(status: int):
    found = connect(probe_for(Provider("/v1/models", {}, status)), "https://api.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "key_refused"
    assert "refused this key" in found.message


def test_a_redirect_is_not_followed():
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})

    found = connect(probe_for(redirect), "https://api.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "address_not_allowed"


def test_an_address_that_is_not_a_model_api_says_so():
    found = connect(probe_for(Provider("/v1/models", {"hello": "world"})), "https://api.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "not_a_model_api"


def test_a_key_with_only_non_text_models_says_so():
    body = {"data": [{"id": "whisper-1", "object": "model"}]}
    found = connect(probe_for(Provider("/v1/models", body)), "https://api.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "no_text_models"


def test_nobody_answering_is_unreachable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    found = connect(probe_for(down), "https://api.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "unreachable"


def test_a_private_address_is_refused_before_anything_is_sent():
    provider = Provider("/v1/models", ANTHROPIC_LIST)
    client = httpx.Client(transport=httpx.MockTransport(provider))
    probe = ModelProbe(AddressPolicy(resolver=lambda host: ["10.0.0.8"]), client=client)
    found = connect(probe, "https://inside.example")
    assert isinstance(found, ModelProblem)
    assert found.reason == "address_not_allowed"
    assert provider.requests == []


ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm-gateway.example", model="claude-haiku-5-5", api_key=KEY
)
SENTENCE = "Two new LangGraph releases came out after 1.2.14: 1.2.16 and 1.2.15."


class Ticks:
    def __init__(self, *readings: float) -> None:
        self._readings = iter(readings)

    def __call__(self) -> float:
        return next(self._readings)


def answering(*replies: str) -> Callable[[ModelAccess], ModelFactory]:
    def factory_for(access: ModelAccess) -> ModelFactory:
        def build(name: str) -> BaseChatModel:
            messages: Iterator[AIMessage] = iter(AIMessage(content=r) for r in replies)
            return GenericFakeChatModel(messages=messages)

        return build

    return factory_for


def raising(error: Exception) -> Callable[[ModelAccess], ModelFactory]:
    def factory_for(access: ModelAccess) -> ModelFactory:
        def build(name: str) -> BaseChatModel:
            raise error

        return build

    return factory_for


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


def answer_from(factory_for: Callable[[ModelAccess], ModelFactory], clock: Ticks | None = None):
    probe = ModelProbe(
        AddressPolicy(resolver=public), factory_for=factory_for, clock=clock or Ticks(100.0, 101.4)
    )
    return probe.test(ACCESS)


def test_a_model_that_answers_in_time_passes_with_its_sentence_and_time():
    result = answer_from(answering(f"  {SENTENCE}\n"))
    assert result == ModelTestPassed(seconds=1.4, text=SENTENCE)


def test_the_test_asks_with_the_runtimes_own_summary_prompt():
    seen: list[str] = []

    def factory_for(access: ModelAccess) -> ModelFactory:
        def build(name: str) -> BaseChatModel:
            seen.append(name)
            return GenericFakeChatModel(messages=iter([AIMessage(content=SENTENCE)]))

        return build

    answer_from(factory_for)
    assert seen == ["claude-haiku-5-5"]


def test_an_answer_slower_than_the_summary_limit_fails_as_too_slow():
    result = answer_from(answering(SENTENCE), Ticks(100.0, 111.2))
    assert isinstance(result, ModelProblem)
    assert result.reason == "too_slow"
    assert "11.2 seconds" in result.message


@pytest.mark.parametrize("reply", ["", "line one\nline two", "x" * 301])
def test_an_answer_the_product_could_not_use_fails(reply: str):
    result = answer_from(answering(reply))
    assert isinstance(result, ModelProblem)
    assert result.reason == "unusable_answer"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (StatusError(401), "key_refused"),
        (StatusError(403), "key_refused"),
        (StatusError(404), "model_not_found"),
        (StatusError(500), "failed"),
        (APITimeoutError("slow"), "too_slow"),
        (APIConnectionError("down"), "unreachable"),
        (RuntimeError("boom"), "failed"),
    ],
)
def test_errors_become_plain_reasons(error: Exception, reason: str):
    result = answer_from(raising(error), Ticks(100.0))
    assert isinstance(result, ModelProblem)
    assert result.reason == reason


def test_an_error_message_never_repeats_the_providers_words():
    result = answer_from(
        raising(RuntimeError(f"bad key {KEY} at https://secret.example")), Ticks(100.0)
    )
    assert isinstance(result, ModelProblem)
    assert KEY not in result.message
    assert "secret.example" not in result.message


def test_a_private_address_is_refused_before_the_model_is_built():
    built: list[str] = []

    def factory_for(access: ModelAccess) -> ModelFactory:
        built.append(access.base_url)
        return answering(SENTENCE)(access)

    probe = ModelProbe(AddressPolicy(resolver=lambda host: ["127.0.0.1"]), factory_for=factory_for)
    result = probe.test(ACCESS)
    assert isinstance(result, ModelProblem)
    assert result.reason == "address_not_allowed"
    assert built == []


def test_the_key_never_shows_in_the_access_repr():
    assert KEY not in repr(ACCESS)


def test_a_slow_card_model_is_not_told_that_runs_use_the_built_in_sentence():
    result = problem_for(APITimeoutError("slow"), runs_fall_back=False)
    assert result.reason == "too_slow"
    assert "built-in" not in result.message


def test_the_chat_for_a_card_checks_the_address_each_time_a_model_is_built():

    policy = AddressPolicy(resolver=lambda host: ["127.0.0.1"])
    build = chat_for(ACCESS, policy, GuardedModels(policy))
    with pytest.raises(AddressRefusedError):
        build(45.0)
