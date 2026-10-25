from collections.abc import Iterable

import httpx
import httpx2
import pytest

from agent_runtime.addresses import AddressPolicy, AddressRefusedError
from agent_runtime.contract import ModelAccess, ModelProblem, ModelTestPassed
from agent_runtime.guarded import GuardedModels, GuardedTransport, GuardedTransport2
from agent_runtime.model_access import ModelProbe

KEY = "sk-example-key-not-real-x7"
SENTENCE = "Two new LangGraph releases came out after 1.2.14: 1.2.16 and 1.2.15."
NAMES = {"api.example": "8.8.8.8", "inside.example": "10.0.0.7", "v6.example": "2606:4700::1111"}


def lookup(host: str) -> Iterable[str]:
    return [NAMES[host]]


POLICY = AddressPolicy(resolver=lookup)


class Rebinding:
    """Answers with a public address the first time and a private one after that."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, host: str) -> Iterable[str]:
        self.calls += 1
        return ["8.8.8.8"] if self.calls == 1 else ["10.0.0.7"]


def recording(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handle)


def test_a_request_goes_to_the_checked_ip_with_the_real_name_for_tls():
    seen: list[httpx.Request] = []
    client = httpx.Client(transport=GuardedTransport(POLICY, recording(seen)))
    client.get("https://api.example/v1/models")
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "api.example"
    assert seen[0].extensions["sni_hostname"] == "api.example"


def test_an_ipv6_answer_is_pinned_too():
    seen: list[httpx.Request] = []
    client = httpx.Client(transport=GuardedTransport(POLICY, recording(seen)))
    client.get("https://v6.example/v1/models")
    assert seen[0].url.host == "2606:4700::1111"
    assert seen[0].headers["host"] == "v6.example"


def test_a_private_answer_at_connect_time_stops_the_request():
    seen: list[httpx.Request] = []
    client = httpx.Client(transport=GuardedTransport(POLICY, recording(seen)))
    with pytest.raises(AddressRefusedError) as refused:
        client.get("https://inside.example/v1/models")
    assert refused.value.refused.reason == "address_not_allowed"
    assert seen == []


def test_a_listed_host_is_not_pinned():
    seen: list[httpx.Request] = []
    policy = AddressPolicy(listed_hosts=frozenset({"host.docker.internal"}), resolver=lookup)
    client = httpx.Client(transport=GuardedTransport(policy, recording(seen)))
    client.get("http://host.docker.internal:11434/v1/models")
    assert seen[0].url.host == "host.docker.internal"
    assert "sni_hostname" not in seen[0].extensions


def test_a_followed_redirect_to_an_inside_address_is_still_stopped():
    def bounce(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "https://inside.example/latest"})

    guarded = GuardedTransport(POLICY, httpx.MockTransport(bounce))
    client = httpx.Client(transport=guarded, follow_redirects=True)
    with pytest.raises(AddressRefusedError):
        client.get("https://api.example/v1/models")


def test_the_httpx2_transport_pins_and_refuses_the_same_way():
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"ok": True})

    client = httpx2.Client(transport=GuardedTransport2(POLICY, httpx2.MockTransport(handle)))
    client.get("https://api.example/v1/messages")
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "api.example"
    with pytest.raises(AddressRefusedError):
        client.get("https://inside.example/v1/messages")


def anthropic_reply(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": SENTENCE}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 40, "output_tokens": 20},
        },
    )


def openai_reply(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-5-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": SENTENCE},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
        },
    )


def through(reply, seen: list[httpx2.Request]) -> httpx2.MockTransport:  # noqa: ANN001
    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return reply(request)

    return httpx2.MockTransport(handle)


def test_an_anthropic_style_model_talks_through_the_guard():
    seen: list[httpx2.Request] = []
    models = GuardedModels(POLICY, inner=through(anthropic_reply, seen))
    access = ModelAccess(
        style="anthropic", base_url="https://api.example", model="claude-haiku-5-5", api_key=KEY
    )
    answer = models.factory_for(access)(access.model).invoke("hello")
    assert answer.text == SENTENCE
    assert seen[0].url.path == "/v1/messages"
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["x-api-key"] == KEY


def test_an_openai_style_model_talks_through_the_guard():
    seen: list[httpx2.Request] = []
    models = GuardedModels(POLICY, inner=through(openai_reply, seen))
    access = ModelAccess(
        style="openai", base_url="https://api.example/v1", model="gpt-5-mini", api_key=KEY
    )
    answer = models.factory_for(access)(access.model).invoke("hello")
    assert answer.text == SENTENCE
    assert seen[0].url.path == "/v1/chat/completions"
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("style", ["anthropic", "openai"])
def test_a_name_that_turns_private_after_the_check_is_refused_by_the_test(style: str):
    seen: list[httpx2.Request] = []
    policy = AddressPolicy(resolver=Rebinding())
    reply = anthropic_reply if style == "anthropic" else openai_reply
    probe = ModelProbe(policy, models=GuardedModels(policy, inner=through(reply, seen)))
    access = ModelAccess(
        style=style,  # type: ignore[arg-type]
        base_url="https://rebind.example/v1",
        model="any-model",
        api_key=KEY,
    )
    result = probe.test(access)
    assert isinstance(result, ModelProblem)
    assert result.reason == "address_not_allowed"
    assert seen == []


def test_a_public_name_passes_the_test_through_the_guard():
    seen: list[httpx2.Request] = []
    probe = ModelProbe(POLICY, models=GuardedModels(POLICY, inner=through(anthropic_reply, seen)))
    access = ModelAccess(
        style="anthropic", base_url="https://api.example", model="claude-haiku-5-5", api_key=KEY
    )
    result = probe.test(access)
    assert isinstance(result, ModelTestPassed)
    assert result.text == SENTENCE


@pytest.mark.parametrize("style", ["anthropic", "openai"])
def test_a_card_model_waits_as_long_as_it_is_told(style: str):
    access = ModelAccess(
        style=style,  # type: ignore[arg-type]
        base_url="https://api.example",
        model="m",
        api_key=KEY,
    )
    quick = GuardedModels(POLICY).factory_for(access)("m")
    patient = GuardedModels(POLICY).factory_for(access, 45.0)("m")
    wait = {"anthropic": "default_request_timeout", "openai": "request_timeout"}[style]
    assert getattr(quick, wait) == 10.0
    assert getattr(patient, wait) == 45.0
