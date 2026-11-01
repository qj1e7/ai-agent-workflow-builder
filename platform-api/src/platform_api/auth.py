from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from platform_api.oidc import OidcAuth, OidcAuthenticator, is_trusted_url, origin_of
from platform_api.shared import (
    DevIdentity,
    ExternalIdentity,
    Identity,
    Principal,
    Role,
    SeedPerson,
    UserId,
)
from platform_api.wire import Responses, WireModel, error_response

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
# Entra's issuers that serve every tenant at once. A user name is only unique within one tenant.
ANY_TENANT = frozenset({"common", "organizations", "consumers"})


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


def _is_portal_url(url: str) -> bool:
    """The Portal's address, which Teams cards and sign-in send people to: https with a host and
    no query or fragment. Plain http only on this machine, for the local sign-in stack."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if not parts.hostname or parts.query or parts.fragment:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)


def _oidc_config(env: Mapping[str, str]) -> OidcAuth:
    base_url = _required(env, "PUBLIC_BASE_URL")
    if not _is_portal_url(base_url):
        raise ConfigError(
            "PUBLIC_BASE_URL must be an absolute https URL with a host and no query or fragment, "
            f"not {base_url!r}. Plain http works only on localhost or 127.0.0.1."
        )
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
    if any(segment.lower() in ANY_TENANT for segment in urlsplit(issuer).path.split("/")):
        raise ConfigError(
            f"OIDC_ISSUER must name one tenant, not {issuer!r}. People are matched to the list "
            "by their user name, which is only unique within one tenant."
        )
    return OidcAuth(base_url, issuer, audience, jwks_url, http_origin)


class Authenticator(Protocol):
    """Checks the sign-in and says who the identity provider says this is. It grants no role."""

    async def __call__(self, request: Request) -> Identity: ...


class PeopleDirectory(Protocol):
    """The People list (ADR 0029). An identity becomes a person with roles only through it."""

    async def resolve(self, identity: Identity) -> Principal | None: ...

    async def person(self, person_id: UserId) -> Principal | None: ...

    async def listed(self) -> list[Principal]: ...


class DevUser(WireModel):
    id: UserId
    display: str
    roles: list[Role]


class DevUsers(WireModel):
    users: list[DevUser]


DEV_PEOPLE: tuple[SeedPerson, ...] = (
    SeedPerson(
        UserId("alice"), "alice@example.test", "Alice", frozenset({Role.OPERATOR, Role.APPROVER})
    ),
    SeedPerson(UserId("bob"), "bob@example.test", "Bob", frozenset({Role.APPROVER})),
    SeedPerson(UserId("carol"), "carol@example.test", "Carol", frozenset({Role.OPERATOR})),
)


def dev_users(people: Iterable[Principal]) -> DevUsers:
    return DevUsers(
        users=[
            DevUser(id=p.user_id, display=p.display, roles=[r for r in Role if r in p.roles])
            for p in people
        ]
    )


DEV_USERS = dev_users(Principal(p.id, p.roles, p.display) for p in DEV_PEOPLE)

DEV_USER_HEADER = "X-Dev-User"
NOT_ON_THE_LIST = (
    "You are signed in, but you are not on the People list. Ask an Operator to add you."
)


def _unknown_dev_user() -> HTTPException:
    return HTTPException(status_code=401, detail=f"Unknown or missing {DEV_USER_HEADER}")


async def dev_authenticator(request: Request) -> Identity:
    user_id = request.headers.get(DEV_USER_HEADER)
    if not user_id:
        raise _unknown_dev_user()
    return DevIdentity(UserId(user_id))


def authenticator_for(config: AuthConfig) -> Authenticator:
    match config:
        case DevAuth():
            return dev_authenticator
        case OidcAuth():
            return OidcAuthenticator(config)


class InMemoryPeople:
    """The People list before the database opens, and in tests. The same binding rule as the
    stored one: a token matches a person by their bound subject, or once by email."""

    def __init__(self, seed: Iterable[SeedPerson] = ()) -> None:
        self._people = {p.id: Principal(p.id, p.roles, p.display) for p in seed}
        self._emails = {p.email.lower(): p.id for p in seed}
        self._subjects: dict[str, UserId] = {}

    async def resolve(self, identity: Identity) -> Principal | None:
        match identity:
            case DevIdentity(person_id):
                return self._people.get(person_id)
            case ExternalIdentity(subject, user_name):
                person_id = self._subjects.get(subject)
                if person_id is None and user_name:
                    person_id = self._emails.get(user_name.lower())
                    if person_id in self._subjects.values():
                        return None
                    if person_id is not None:
                        self._subjects[subject] = person_id
                return self._people.get(person_id) if person_id is not None else None

    async def person(self, person_id: UserId) -> Principal | None:
        return self._people.get(person_id)

    async def listed(self) -> list[Principal]:
        return list(self._people.values())

    def remove(self, person_id: UserId) -> None:
        self._people.pop(person_id, None)


def people_for(config: AuthConfig) -> PeopleDirectory:
    match config:
        case DevAuth():
            return InMemoryPeople(DEV_PEOPLE)
        case OidcAuth():
            return InMemoryPeople()


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
        "platform-api. The token only says who you are. Your roles come from the People list, "
        "and a roles claim in the token is ignored."
    ),
    auto_error=False,
)


@dataclass(frozen=True)
class SignedIn:
    identity: Identity
    person: Principal | None
    """None when the sign-in is good but the person is not on the People list."""


async def current_sign_in(
    request: Request,
    dev_declared: Annotated[str | None, Security(dev_user_scheme)],
    bearer_declared: Annotated[HTTPAuthorizationCredentials | None, Security(oidc_bearer_scheme)],
) -> SignedIn:
    authenticator: Authenticator = request.app.state.authenticator
    identity = await authenticator(request)
    directory: PeopleDirectory = request.app.state.people
    person = await directory.resolve(identity)
    if person is None and isinstance(identity, DevIdentity):
        raise _unknown_dev_user()
    return SignedIn(identity, person)


CurrentSignIn = Annotated[SignedIn, Depends(current_sign_in)]


async def current_principal(signed_in: CurrentSignIn) -> Principal:
    if signed_in.person is None:
        raise HTTPException(status_code=403, detail=NOT_ON_THE_LIST)
    return signed_in.person


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

SIGNED_IN: Responses = {
    401: error_response(
        f"Not signed in: no valid access token, or in local mode no known {DEV_USER_HEADER}"
    ),
    403: error_response("Signed in, but not on the People list. Ask an Operator to add you"),
    503: error_response(
        "Sign-in could not be checked because the identity provider's keys are unavailable"
    ),
}
OPERATORS_ONLY: Responses = {
    **SIGNED_IN,
    403: error_response("Only an Operator can do this, or the person is not on the People list"),
}


def _without_default(schema: dict[str, Any]) -> None:
    # The Portal's generated type treats a field with a default as required. Without the
    # default it stays optional there, so older Me values still type-check.
    schema.pop("default", None)


class Me(WireModel):
    id: UserId
    display: str
    roles: list[Role]
    on_list: bool = Field(
        default=True,
        json_schema_extra=_without_default,
        description="False when the sign-in is good but no Operator has added this person yet.",
    )


me_router = APIRouter(tags=["sign-in"])


@me_router.get(
    "/api/v1/me",
    responses={status: body for status, body in SIGNED_IN.items() if status != 403},
    description=(
        "Who the platform thinks you are. Someone signed in but not on the People list gets "
        "`on_list: false` and no roles; every other route answers them 403."
    ),
)
def who_am_i(signed_in: CurrentSignIn) -> Me:
    if signed_in.person is None:
        identity = signed_in.identity
        assert isinstance(identity, ExternalIdentity)
        return Me(id=UserId(identity.subject), display=identity.display, roles=[], on_list=False)
    principal = signed_in.person
    return Me(
        id=principal.user_id,
        display=principal.display,
        roles=[role for role in Role if role in principal.roles],
    )


dev_router = APIRouter(tags=["dev"])


@dev_router.get("/api/v1/dev/users")
async def list_dev_users(request: Request) -> DevUsers:
    directory: PeopleDirectory = request.app.state.people
    return dev_users(await directory.listed())
