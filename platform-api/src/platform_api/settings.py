from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from platform_api.auth import AuthConfig, ConfigError, auth_config

type Context = Literal["builder", "orchestration", "monitoring"]

CONTEXTS: tuple[Context, ...] = ("builder", "orchestration", "monitoring")


@dataclass(frozen=True)
class DatabaseUrls:
    builder: str
    orchestration: str
    monitoring: str

    def for_context(self, context: Context) -> str:
        match context:
            case "builder":
                return self.builder
            case "orchestration":
                return self.orchestration
            case "monitoring":
                return self.monitoring


@dataclass(frozen=True)
class Settings:
    auth: AuthConfig
    public_base_url: str
    database: DatabaseUrls
    agent_runtime_url: str
    agent_api_key: str
    n8n_base_url: str
    step_key: str
    platform_internal_url: str
    callback_signing_key: str
    teams_channel: str


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ConfigError(f"{name} is not set.")
    return value


def settings_from_env(env: Mapping[str, str]) -> Settings:
    auth = auth_config(env)
    return Settings(
        auth=auth,
        public_base_url=auth.public_base_url.rstrip("/"),
        database=DatabaseUrls(
            builder=_required(env, "DATABASE_URL_BUILDER"),
            orchestration=_required(env, "DATABASE_URL_ORCHESTRATION"),
            monitoring=_required(env, "DATABASE_URL_MONITORING"),
        ),
        agent_runtime_url=_required(env, "AGENT_RUNTIME_URL").rstrip("/"),
        agent_api_key=_required(env, "AGENT_API_KEY"),
        n8n_base_url=_required(env, "N8N_BASE_URL").rstrip("/"),
        step_key=_required(env, "STEP_KEY"),
        platform_internal_url=_required(env, "PLATFORM_INTERNAL_URL").rstrip("/"),
        callback_signing_key=_required(env, "CALLBACK_SIGNING_KEY"),
        teams_channel=env.get("TEAMS_CHANNEL") or "CODESparks Ops",
    )


@dataclass(frozen=True)
class BootstrapSettings:
    owner_database_url: str
    n8n_base_url: str
    n8n_owner_email: str
    n8n_owner_password: str
    step_key: str
    platform_internal_url: str


def bootstrap_settings_from_env(env: Mapping[str, str]) -> BootstrapSettings:
    return BootstrapSettings(
        owner_database_url=_required(env, "DATABASE_URL_OWNER"),
        n8n_base_url=_required(env, "N8N_BASE_URL").rstrip("/"),
        n8n_owner_email=_required(env, "N8N_OWNER_EMAIL"),
        n8n_owner_password=_required(env, "N8N_OWNER_PASSWORD"),
        step_key=_required(env, "STEP_KEY"),
        platform_internal_url=_required(env, "PLATFORM_INTERNAL_URL").rstrip("/"),
    )
