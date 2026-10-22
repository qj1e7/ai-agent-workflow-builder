from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

type Env = Mapping[str, str]
type Settings = Callable[[Env, str], dict[str, Any]]

CLOUD_TIMEOUT_SECONDS = 120
LOCAL_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Provider:
    name: str
    needs: tuple[str, ...]
    models_env: str
    default_models: tuple[str, ...]
    settings: Settings


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    kwargs: dict[str, Any]

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def build(self) -> BaseChatModel:
        return init_chat_model(self.model, model_provider=self.provider, **self.kwargs)


@dataclass(frozen=True)
class NotRun:
    provider: str
    model: str | None
    reason: str


def _temperature(env: Env, default: str | None) -> dict[str, object]:
    value = env.get("EVAL_TEMPERATURE", default)
    return {"temperature": float(value)} if value else {}


def _ollama(env: Env, model: str) -> dict[str, object]:
    return {
        "base_url": env["OLLAMA_BASE_URL"],
        "seed": 7,
        "client_kwargs": {"timeout": LOCAL_TIMEOUT_SECONDS},
        **_temperature(env, "0"),
    }


def _azure(env: Env, model: str) -> dict[str, object]:
    return {
        "azure_deployment": model,
        "azure_endpoint": env["AZURE_OPENAI_ENDPOINT"],
        "api_version": env["AZURE_OPENAI_API_VERSION"],
        "timeout": CLOUD_TIMEOUT_SECONDS,
        "max_retries": 2,
        **_temperature(env, None),
    }


def _cloud(env: Env, model: str) -> dict[str, object]:
    return {"timeout": CLOUD_TIMEOUT_SECONDS, "max_retries": 2, **_temperature(env, None)}


PROVIDERS = (
    Provider(
        "ollama",
        needs=("OLLAMA_BASE_URL",),
        models_env="OLLAMA_MODELS",
        default_models=("gemma:2b", "deepseek-r1:latest"),
        settings=_ollama,
    ),
    Provider(
        "azure_openai",
        needs=("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"),
        models_env="AZURE_OPENAI_DEPLOYMENTS",
        default_models=(),
        settings=_azure,
    ),
    Provider(
        "anthropic",
        needs=("ANTHROPIC_API_KEY",),
        models_env="ANTHROPIC_MODELS",
        default_models=("claude-haiku-5-5", "claude-sonnet-5-5"),
        settings=_cloud,
    ),
    Provider(
        "google_genai",
        needs=("GOOGLE_API_KEY",),
        models_env="GOOGLE_MODELS",
        default_models=(),
        settings=_cloud,
    ),
)


def _ollama_models(base_url: str) -> set[str] | str:
    try:
        reply = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        reply.raise_for_status()
    except httpx.HTTPError as error:
        # The address can hold a password or a private host name, so it stays out of the reason.
        return f"cannot reach Ollama ({type(error).__name__})"
    return {m["name"] for m in reply.json().get("models", [])}


def plan(env: Env) -> tuple[list[Target], list[NotRun]]:
    targets: list[Target] = []
    not_run: list[NotRun] = []
    for provider in PROVIDERS:
        missing = [name for name in provider.needs if not env.get(name)]
        if missing:
            not_run.append(NotRun(provider.name, None, f"not set: {', '.join(missing)}"))
            continue
        listed = env.get(provider.models_env, "")
        models = [m.strip() for m in listed.split(",") if m.strip()] or list(
            provider.default_models
        )
        if not models:
            not_run.append(NotRun(provider.name, None, f"not set: {provider.models_env}"))
            continue
        installed = _ollama_models(env["OLLAMA_BASE_URL"]) if provider.name == "ollama" else None
        for model in models:
            if isinstance(installed, str):
                not_run.append(NotRun(provider.name, model, installed))
            elif installed is not None and model not in installed:
                not_run.append(NotRun(provider.name, model, "model not installed, not pulled"))
            else:
                targets.append(Target(provider.name, model, provider.settings(env, model)))
    return targets, not_run
