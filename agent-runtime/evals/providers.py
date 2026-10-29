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
    client: str | None = None


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    kwargs: dict[str, Any]
    client: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def build(self, **overrides: Any) -> BaseChatModel:
        settings = self.kwargs | overrides
        return init_chat_model(self.model, model_provider=self.client or self.provider, **settings)


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


def _gateway(env: Env, model: str) -> dict[str, object]:
    return {
        "base_url": env["AGENT_MODEL_BASE_URL"],
        "api_key": env["AGENT_MODEL_API_KEY"],
        **_cloud(env, model),
    }


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
    # An Anthropic-style gateway, read from the runtime's own settings (ADR 0021): the AI
    # Singapore gateway for the demo model, or the mock model for a dry run.
    Provider(
        "gateway",
        needs=("AGENT_MODEL_BASE_URL", "AGENT_MODEL_API_KEY"),
        models_env="GATEWAY_MODELS",
        default_models=("azure_ai/claude-haiku-5-5",),
        settings=_gateway,
        client="anthropic",
    ),
)


def _ollama_models(base_url: str) -> set[str] | str:
    try:
        reply = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        reply.raise_for_status()
        return {m["name"] for m in reply.json().get("models", [])}
    except Exception as error:  # A malformed address raises InvalidURL, not an HTTPError.
        # The address can hold a password or a private host name, so it stays out of the reason.
        return f"cannot reach Ollama ({type(error).__name__})"


def plan(env: Env) -> tuple[list[Target], list[NotRun]]:
    targets: list[Target] = []
    not_run: list[NotRun] = []
    for provider in PROVIDERS:
        try:
            planned, skipped = _plan_provider(provider, env)
        except Exception as error:
            # The caller redacts every reason before it keeps it.
            planned, skipped = [], [NotRun(provider.name, None, f"{type(error).__name__}: {error}")]
        targets += planned
        not_run += skipped
    return targets, not_run


def _plan_provider(provider: Provider, env: Env) -> tuple[list[Target], list[NotRun]]:
    missing = [name for name in provider.needs if not env.get(name)]
    if missing:
        return [], [NotRun(provider.name, None, f"not set: {', '.join(missing)}")]
    listed = env.get(provider.models_env, "")
    models = [m.strip() for m in listed.split(",") if m.strip()] or list(provider.default_models)
    if not models:
        return [], [NotRun(provider.name, None, f"not set: {provider.models_env}")]
    installed = _ollama_models(env["OLLAMA_BASE_URL"]) if provider.name == "ollama" else None
    targets: list[Target] = []
    not_run: list[NotRun] = []
    for model in models:
        if isinstance(installed, str):
            not_run.append(NotRun(provider.name, model, installed))
        elif installed is not None and model not in installed:
            not_run.append(NotRun(provider.name, model, "model not installed, not pulled"))
        else:
            targets.append(
                Target(provider.name, model, provider.settings(env, model), provider.client)
            )
    return targets, not_run
