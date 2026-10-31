from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from platform_api.auth import AuthConfig, ConfigError, auth_config

type Context = Literal["builder", "orchestration", "monitoring"]
type ActivityReader = Literal["postgres", "cosmos"]

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
class CosmosSettings:
    endpoint: str
    key: str


@dataclass(frozen=True)
class FirstPeople:
    """The first deploy's people (ADR 0030): applied only while the People list is empty."""

    operator: str
    approvers: tuple[str, str]


MAX_BODY_BYTES_DEFAULT = 2 * 1024 * 1024
"""The largest request body the API reads, unless MAX_BODY_BYTES says otherwise. The largest
real body is a New workflow draft. Its content may be 32 KB (DRAFT_LIMIT_BYTES), which is about
100 KB as JSON even with every character escaped, so 2 MiB leaves about 20 times that."""


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
    settings_encryption_key: str | None = None
    first_people: FirstPeople | None = None
    activity_reader: ActivityReader = "postgres"
    cosmos: CosmosSettings | None = None
    max_body_bytes: int = MAX_BODY_BYTES_DEFAULT


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ConfigError(f"{name} is not set.")
    return value


def first_people_from_env(env: Mapping[str, str]) -> FirstPeople | None:
    operator = env.get("FIRST_OPERATOR", "").strip()
    approvers = [a.strip() for a in env.get("FIRST_APPROVERS", "").split(",") if a.strip()]
    if not operator and not approvers:
        return None
    if not operator or not approvers:
        raise ConfigError(
            "FIRST_OPERATOR and FIRST_APPROVERS go together: one email, and two emails "
            "separated by a comma."
        )
    if len(approvers) != 2 or approvers[0].lower() == approvers[1].lower():
        raise ConfigError(
            "FIRST_APPROVERS must name two different people, separated by a comma, so nobody "
            "has to approve their own work."
        )
    for email in (operator, *approvers):
        local, at, domain = email.partition("@")
        if not (at and local and "." in domain):
            raise ConfigError(f"{email!r} in FIRST_OPERATOR or FIRST_APPROVERS is not an email.")
    return FirstPeople(operator, (approvers[0], approvers[1]))


def cosmos_from_env(env: Mapping[str, str]) -> CosmosSettings | None:
    endpoint = env.get("COSMOS_ENDPOINT", "").strip()
    key = env.get("COSMOS_KEY", "").strip()
    if not endpoint and not key:
        return None
    if not endpoint:
        raise ConfigError("COSMOS_KEY is set but COSMOS_ENDPOINT is not.")
    if not key:
        raise ConfigError("COSMOS_ENDPOINT is set but COSMOS_KEY is not.")
    return CosmosSettings(endpoint=endpoint.rstrip("/"), key=key)


def activity_reader_from_env(
    env: Mapping[str, str], cosmos: CosmosSettings | None
) -> ActivityReader:
    match env.get("ACTIVITY_READER") or "postgres":
        case "postgres":
            return "postgres"
        case "cosmos" if cosmos is not None:
            return "cosmos"
        case "cosmos":
            raise ConfigError("ACTIVITY_READER=cosmos needs COSMOS_ENDPOINT and COSMOS_KEY.")
        case other:
            raise ConfigError(f"ACTIVITY_READER takes postgres or cosmos, not {other!r}.")


def max_body_bytes_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("MAX_BODY_BYTES", "").strip()
    if not raw:
        return MAX_BODY_BYTES_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"MAX_BODY_BYTES takes a whole number of bytes above 0, not {raw!r}.")
    return value


def settings_from_env(env: Mapping[str, str]) -> Settings:
    auth = auth_config(env)
    cosmos = cosmos_from_env(env)
    return Settings(
        auth=auth,
        first_people=first_people_from_env(env),
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
        settings_encryption_key=env.get("SETTINGS_ENCRYPTION_KEY") or None,
        activity_reader=activity_reader_from_env(env, cosmos),
        cosmos=cosmos,
        max_body_bytes=max_body_bytes_from_env(env),
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
