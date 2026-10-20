from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from platform_api.shared import Principal, Role, UserId
from platform_api.wire import WireModel

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
    def __call__(self, request: Request) -> Principal: ...


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


def dev_authenticator(request: Request) -> Principal:
    user_id = request.headers.get(DEV_USER_HEADER)
    user = next((user for user in DEV_USERS.users if user.id == user_id), None)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown or missing {DEV_USER_HEADER}")
    return Principal(user.id, frozenset(user.roles))


def authenticator_for(config: AuthConfig) -> Authenticator:
    match config:
        case DevAuth():
            return dev_authenticator


def current_principal(request: Request) -> Principal:
    authenticator: Authenticator = request.app.state.authenticator
    return authenticator(request)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

dev_router = APIRouter(tags=["dev"])


@dev_router.get("/api/v1/dev/users")
def list_dev_users() -> DevUsers:
    return DEV_USERS
