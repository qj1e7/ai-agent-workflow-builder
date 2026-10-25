from functools import cached_property
from typing import Any

import anthropic
import httpx
import httpx2
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from agent_runtime.addresses import AddressPolicy
from agent_runtime.contract import ModelAccess
from agent_runtime.summary import SUMMARY_TIMEOUT_SECONDS, ModelFactory


# Every connection to a model address goes through one of these two transports (ADR 0022). Each
# checks the IP it is about to connect to and connects to exactly that IP, keeping the real name
# for TLS. That covers redirects too, because each hop is a new request through the transport.
class GuardedTransport(httpx.BaseTransport):
    def __init__(self, policy: AddressPolicy, inner: httpx.BaseTransport | None = None) -> None:
        self._policy = policy
        self._inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        ip = self._policy.pin(host)
        if ip is not None:
            request.extensions = {**request.extensions, "sni_hostname": host}
            request.url = request.url.copy_with(host=ip)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


# The same guard for httpx2, the HTTP library the Anthropic and OpenAI clients use.
class GuardedTransport2(httpx2.BaseTransport):
    def __init__(self, policy: AddressPolicy, inner: httpx2.BaseTransport | None = None) -> None:
        self._policy = policy
        self._inner = inner or httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        ip = self._policy.pin(host)
        if ip is not None:
            request.extensions = {**request.extensions, "sni_hostname": host}
            request.url = request.url.copy_with(host=ip)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


# langchain-anthropic builds its own HTTP client and has no option to pass one in, so this swaps
# ours in at the one place it builds it. The package is pinned, and test_guarded.py covers this.
class _GuardedChatAnthropic(ChatAnthropic):
    guarded_client: Any = Field(default=None, exclude=True)

    @cached_property
    def _client(self) -> anthropic.Client:
        return anthropic.Client(**self._client_params, http_client=self.guarded_client)


class GuardedModels:
    """Builds chat models whose every connection goes through the address guard."""

    def __init__(self, policy: AddressPolicy, inner: httpx2.BaseTransport | None = None) -> None:
        # One client for every model, so connections are reused and nothing is left open.
        self._client = httpx2.Client(
            transport=GuardedTransport2(policy, inner),
            follow_redirects=False,
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )

    def factory_for(
        self, access: ModelAccess, timeout: float = SUMMARY_TIMEOUT_SECONDS
    ) -> ModelFactory:
        def build(name: str) -> BaseChatModel:
            if access.style == "anthropic":
                return _GuardedChatAnthropic(
                    model_name=name,
                    stop=None,
                    base_url=access.base_url,
                    api_key=SecretStr(access.api_key),
                    timeout=timeout,
                    max_retries=0,
                    guarded_client=self._client,
                )
            return ChatOpenAI(
                model=name,
                base_url=access.base_url,
                api_key=SecretStr(access.api_key),
                timeout=timeout,
                max_retries=0,
                http_client=self._client,
            )

        return build
