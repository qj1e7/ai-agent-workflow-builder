from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from platform_api.shared import Principal, Role, UserId
from platform_api.wire import Responses, WireModel, error_response

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class DevAuth:
    public_base_url: str


type AuthConfig = DevAuth


def auth_config(env: Mapping[str, str]) -> AuthConfig:
    mode = env.get("AUTH_MODE")
    if mode is None:
        raise ConfigError("AUTH_MODE is not set. Set AUTH_MODE=dev for local mode.")
    if mode != "dev":
        raise ConfigError(f"AUTH_MODE={mode!r} is not supported. Only 'dev' exists so far.")
    base_url = env.get("PUBLIC_BASE_URL")
    if base_url is None:
        raise ConfigError("PUBLIC_BASE_URL is not set. Dev mode needs it to prove it is local.")
    if urlsplit(base_url).hostname not in LOCAL_HOSTS:
        raise ConfigError(
            f"AUTH_MODE=dev only runs on localhost or 127.0.0.1, not {base_url!r}. "
            "The dev sign-in stub must never reach a shared deployment."
        )
    return DevAuth(base_url)


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
