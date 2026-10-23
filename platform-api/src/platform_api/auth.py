from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from platform_api.oidc import OidcAuth, OidcAuthenticator, is_trusted_url, origin_of
from platform_api.shared import Principal, Role, UserId
from platform_api.wire import Responses, WireModel, error_response

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class DevAuth:
    public_base_url: str


type AuthConfig = DevAuth | OidcAuth


def auth_config(env: Mapping[str, str]) -> AuthConfig:
    match env.get("AUTH_MODE"):
        case None:
            raise ConfigError(
                "AUTH_MODE is not set. Set AUTH_MODE=dev for local mode "
                "or AUTH_MODE=oidc for real sign-in."
            )
        case "dev":
            return _dev_config(env)
        case "oidc":
            return _oidc_config(env)
        case mode:
            raise ConfigError(f"AUTH_MODE={mode!r} is not supported. Use 'dev' or 'oidc'.")


def _dev_config(env: Mapping[str, str]) -> DevAuth:
    base_url = env.get("PUBLIC_BASE_URL")
    if base_url is None:
        raise ConfigError("PUBLIC_BASE_URL is not set. Dev mode needs it to prove it is local.")
    if urlsplit(base_url).hostname not in LOCAL_HOSTS:
        raise ConfigError(
            f"AUTH_MODE=dev only runs on localhost or 127.0.0.1, not {base_url!r}. "
            "The dev sign-in stub must never reach a shared deployment."
        )
    return DevAuth(base_url)


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. AUTH_MODE=oidc needs it.")
    return value


def _test_only_http_origin(env: Mapping[str, str], issuer: str, base_url: str) -> str | None:
    allowance = env.get("OIDC_TEST_ONLY_HTTP_ISSUER", "").strip()
    if not allowance:
        return None
    if allowance != issuer:
        raise ConfigError(
            "OIDC_TEST_ONLY_HTTP_ISSUER must equal OIDC_ISSUER exactly. "
            "It allows plain http for that one issuer in local tests."
        )
    if urlsplit(base_url).hostname not in LOCAL_HOSTS:
        raise ConfigError(
            "OIDC_TEST_ONLY_HTTP_ISSUER only works with PUBLIC_BASE_URL on localhost or "
            f"127.0.0.1, not {base_url!r}. A plain-http issuer must never reach a shared "
            "deployment."
        )
    return origin_of(issuer) if urlsplit(issuer).scheme == "http" else None


def _oidc_config(env: Mapping[str, str]) -> OidcAuth:
    base_url = _required(env, "PUBLIC_BASE_URL")
    issuer = _required(env, "OIDC_ISSUER")
    audience = _required(env, "OIDC_AUDIENCE")
    http_origin = _test_only_http_origin(env, issuer, base_url)
    jwks_url = env.get("OIDC_JWKS_URL", "").strip() or None
    for name, url in (("OIDC_ISSUER", issuer), ("OIDC_JWKS_URL", jwks_url)):
        if url is not None and not is_trusted_url(url, http_origin):
            raise ConfigError(
                f"{name} must be an absolute https URL with a host and no query or fragment, "
                f"not {url!r}."
            )
    return OidcAuth(base_url, issuer, audience, jwks_url, http_origin)


class Authenticator(Protocol):
    async def __call__(self, request: Request) -> Principal: ...


class DevUser(WireModel):
    id: UserId
    display: str
    roles: list[Role]


class DevUsers(WireModel):
    users: list[DevUser]


DEV_USERS = DevUsers(
    users=[
        DevUser(id=UserId("alice"), display="Alice", roles=[Role.OPERATOR, Role.APPROVER]),
        DevUser(id=UserId("bob"), display="Bob", roles=[Role.APPROVER]),
        DevUser(id=UserId("carol"), display="Carol", roles=[Role.OPERATOR]),
    ]
)

DEV_USER_HEADER = "X-Dev-User"


async def dev_authenticator(request: Request) -> Principal:
    user_id = request.headers.get(DEV_USER_HEADER)
    user = next((user for user in DEV_USERS.users if user.id == user_id), None)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown or missing {DEV_USER_HEADER}")
    return Principal(user.id, frozenset(user.roles), user.display)


def authenticator_for(config: AuthConfig) -> Authenticator:
    match config:
        case DevAuth():
            return dev_authenticator
        case OidcAuth():
            return OidcAuthenticator(config)


dev_user_scheme = APIKeyHeader(
    name=DEV_USER_HEADER,
    scheme_name="DevUser",
    description=(
        "Dev-only sign-in for local mode. Send one of the ids from GET /api/v1/dev/users. "
        "A deployment with real sign-in does not use it."
    ),
    auto_error=False,
)


oidc_bearer_scheme = HTTPBearer(
    scheme_name="OidcBearer",
    bearerFormat="JWT",
    description=(
        "Real sign-in (AUTH_MODE=oidc). Send an OpenID Connect access token whose audience is "
        "platform-api. Roles come from its roles claim: Operator and Approver."
    ),
    auto_error=False,
)


async def current_principal(
    request: Request,
    dev_declared: Annotated[str | None, Security(dev_user_scheme)],
    bearer_declared: Annotated[HTTPAuthorizationCredentials | None, Security(oidc_bearer_scheme)],
) -> Principal:
    authenticator: Authenticator = request.app.state.authenticator
    return await authenticator(request)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

SIGNED_IN: Responses = {
    401: error_response(
        f"Not signed in: no valid access token, or in local mode no known {DEV_USER_HEADER}"
    ),
    503: error_response(
        "Sign-in could not be checked because the identity provider's keys are unavailable"
    ),
}
OPERATORS_ONLY: Responses = {
    **SIGNED_IN,
    403: error_response("Only an Operator can do this"),
}


class Me(WireModel):
    id: UserId
    display: str
    roles: list[Role]


me_router = APIRouter(tags=["sign-in"])


@me_router.get("/api/v1/me", responses=SIGNED_IN)
def who_am_i(principal: CurrentPrincipal) -> Me:
    return Me(
        id=principal.user_id,
        display=principal.display,
        roles=[role for role in Role if role in principal.roles],
    )


dev_router = APIRouter(tags=["dev"])


@dev_router.get("/api/v1/dev/users")
def list_dev_users() -> DevUsers:
    return DEV_USERS
