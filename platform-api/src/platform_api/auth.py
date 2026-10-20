"""Sign-in for local mode: `AUTH_MODE=dev` reads `X-Dev-User`. Entra ID replaces it later."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from platform_api.shared import Principal, Role, UserId
from platform_api.wire import WireModel


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


def dev_user(user_id: str) -> DevUser | None:
    return next((user for user in DEV_USERS.users if user.id == user_id), None)


def current_principal(x_dev_user: Annotated[str, Header(alias="X-Dev-User")]) -> Principal:
    user = dev_user(x_dev_user)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown dev user")
    return Principal(user.id, frozenset(user.roles))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

router = APIRouter(tags=["dev"])


@router.get("/api/v1/dev/users")
def list_dev_users() -> DevUsers:
    return DEV_USERS
