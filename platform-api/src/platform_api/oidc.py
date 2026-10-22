import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from platform_api.shared import Principal, Role, UserId

log = logging.getLogger(__name__)

type Algorithm = Literal["RS256", "ES256"]

ACCEPTED: frozenset[str] = frozenset({"RS256", "ES256"})
LEEWAY_SECONDS = 60
KEYS_MAX_AGE_SECONDS = 3600
REFETCH_COOLDOWN_SECONDS = 30
FETCH_TIMEOUT_SECONDS = 5
RETRY_AFTER_SECONDS = 30
MIN_RSA_BITS = 2048
MAX_DISPLAY_CHARS = 120
MAX_DOCUMENT_BYTES = 256 * 1024

ROLE_BY_CLAIM: Mapping[str, Role] = {"Operator": Role.OPERATOR, "Approver": Role.APPROVER}


@dataclass(frozen=True)
class OidcAuth:
    public_base_url: str
    issuer: str
    audience: str
    jwks_url: str | None
    test_only_http_origin: str | None


@dataclass(frozen=True)
class VerificationKey:
    kid: str
    algorithm: Algorithm
    public_key: RSAPublicKey | EllipticCurvePublicKey


class Rejection(Enum):
    MISSING = "missing"
    MALFORMED = "malformed"
    ALGORITHM = "algorithm"
    UNKNOWN_KEY = "unknown_key"
    SIGNATURE = "signature"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    ISSUER = "issuer"
    AUDIENCE = "audience"
    NO_USER = "no_user"


class TokenRejected(Exception):
    def __init__(self, reason: Rejection) -> None:
        super().__init__(reason.value)
        self.reason = reason


class KeysUnavailable(Exception):
    pass


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_trusted_url(url: str, http_origin: str | None) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if not parts.hostname or parts.query or parts.fragment:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and http_origin is not None and origin_of(url) == http_origin


class _Jwk(BaseModel):
    model_config = ConfigDict(extra="allow")
    kid: str = Field(min_length=1)
    kty: str
    use: str = "sig"
    alg: str | None = None


class _Jwks(BaseModel):
    keys: list[object]


class _Discovery(BaseModel):
    issuer: str
    jwks_uri: str


def _verification_key(entry: _Jwk) -> VerificationKey | None:
    if entry.use != "sig":
        return None
    try:
        key = jwt.PyJWK(entry.model_dump()).key
    except jwt.PyJWTError, TypeError, ValueError:
        return None
    match key:
        case RSAPublicKey() if key.key_size >= MIN_RSA_BITS:
            algorithm: Algorithm = "RS256"
        case EllipticCurvePublicKey() if isinstance(key.curve, ec.SECP256R1):
            algorithm = "ES256"
        case _:
            return None
    if entry.alg not in (None, algorithm):
        return None
    return VerificationKey(entry.kid, algorithm, key)


def parse_jwks(document: object) -> dict[str, VerificationKey]:
    try:
        entries = _Jwks.model_validate(document).keys
    except ValidationError:
        return {}
    named: list[_Jwk] = []
    for entry in entries:
        try:
            named.append(_Jwk.model_validate(entry))
        except ValidationError:
            continue
    seen = Counter(entry.kid for entry in named)
    keys: dict[str, VerificationKey] = {}
    for entry in named:
        key = _verification_key(entry)
        if key is not None and seen[key.kid] == 1:
            keys[key.kid] = key
    return keys


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _cleaned(display: str) -> str:
    return "".join(ch for ch in display if ch.isprintable()).strip()[:MAX_DISPLAY_CHARS]


def principal_from_claims(claims: Mapping[str, object]) -> Principal:
    user_id = _text(claims.get("oid")) or _text(claims.get("sub"))
    if user_id is None:
        raise TokenRejected(Rejection.NO_USER)
    display = _text(claims.get("name")) or _text(claims.get("preferred_username")) or user_id
    raw_roles = claims.get("roles")
    granted = cast("list[object]", raw_roles) if isinstance(raw_roles, list) else []
    roles = frozenset(
        ROLE_BY_CLAIM[value]
        for value in granted
        if isinstance(value, str) and value in ROLE_BY_CLAIM
    )
    return Principal(UserId(user_id), roles, _cleaned(display) or user_id)


class _LoadFailed(Exception):
    pass


async def _document(client: httpx.AsyncClient, url: str) -> object:
    try:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise _LoadFailed(f"{url} answered {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_DOCUMENT_BYTES:
                    raise _LoadFailed(f"{url} is larger than {MAX_DOCUMENT_BYTES} bytes")
    except httpx.HTTPError as error:
        raise _LoadFailed(f"{url} could not be fetched: {error!r}") from None
    try:
        return json.loads(body)
    except ValueError:
        raise _LoadFailed(f"{url} is not JSON") from None


class SigningKeys:
    def __init__(
        self,
        config: OidcAuth,
        *,
        transport: httpx.AsyncBaseTransport | None,
        clock: Callable[[], float],
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock
        self._lock = asyncio.Lock()
        self._jwks_url = config.jwks_url
        self._keys: dict[str, VerificationKey] = {}
        self._loaded_at: float | None = None
        self._attempted_at: float | None = None

    async def key_for(self, kid: str) -> VerificationKey:
        key = self._fresh(kid)
        if key is not None:
            return key
        async with self._lock:
            key = self._fresh(kid)
            if key is not None:
                return key
            loaded = await self._load_if_due()
            key = self._keys.get(kid)
            if key is not None:
                return key
            if not self._keys or not loaded:
                raise KeysUnavailable
            raise TokenRejected(Rejection.UNKNOWN_KEY)

    def _fresh(self, kid: str) -> VerificationKey | None:
        if self._loaded_at is None or self._clock() - self._loaded_at >= KEYS_MAX_AGE_SECONDS:
            return None
        return self._keys.get(kid)

    async def _load_if_due(self) -> bool:
        now = self._clock()
        if self._attempted_at is not None and now - self._attempted_at < REFETCH_COOLDOWN_SECONDS:
            return True
        self._attempted_at = now
        try:
            self._keys = await self._fetch()
        except _LoadFailed as failed:
            log.warning("Could not load the identity provider's keys: %s", failed)
            return False
        self._loaded_at = now
        return True

    async def _fetch(self) -> dict[str, VerificationKey]:
        async with httpx.AsyncClient(
            transport=self._transport, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            if self._jwks_url is None:
                self._jwks_url = await self._discover(client)
            keys = parse_jwks(await _document(client, self._jwks_url))
        if not keys:
            raise _LoadFailed(f"{self._jwks_url} has no usable keys")
        return keys

    async def _discover(self, client: httpx.AsyncClient) -> str:
        url = f"{self._config.issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            discovery = _Discovery.model_validate(await _document(client, url))
        except ValidationError:
            raise _LoadFailed(f"{url} does not name an issuer and a jwks_uri") from None
        if discovery.issuer != self._config.issuer:
            raise _LoadFailed(
                f"{url} names the issuer {discovery.issuer!r}, not the configured one"
            )
        if not is_trusted_url(discovery.jwks_uri, self._config.test_only_http_origin):
            raise _LoadFailed(f"{url} names a jwks_uri that is not https: {discovery.jwks_uri!r}")
        return discovery.jwks_uri


_REJECTION_BY_ERROR: tuple[tuple[type[jwt.InvalidTokenError], Rejection], ...] = (
    (jwt.ExpiredSignatureError, Rejection.EXPIRED),
    (jwt.ImmatureSignatureError, Rejection.NOT_YET_VALID),
    (jwt.InvalidIssuerError, Rejection.ISSUER),
    (jwt.InvalidAudienceError, Rejection.AUDIENCE),
    (jwt.InvalidSignatureError, Rejection.SIGNATURE),
    (jwt.InvalidAlgorithmError, Rejection.ALGORITHM),
    (jwt.InvalidTokenError, Rejection.MALFORMED),
)


def _rejection(error: jwt.InvalidTokenError) -> Rejection:
    return next(reason for kind, reason in _REJECTION_BY_ERROR if isinstance(error, kind))


def bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise TokenRejected(Rejection.MISSING)
    scheme, _, credentials = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        raise TokenRejected(Rejection.MISSING)
    match credentials.split():
        case [token]:
            return token
        case _:
            raise TokenRejected(Rejection.MALFORMED)


def _unauthorized(reason: Rejection) -> HTTPException:
    if reason is Rejection.MISSING:
        return HTTPException(
            401,
            "Not signed in. Send an access token as Authorization: Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return HTTPException(
        401,
        "Not signed in. The access token was not accepted.",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        503,
        "Sign-in could not be checked because the identity provider's keys are unavailable. "
        "Try again shortly.",
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


class OidcAuthenticator:
    def __init__(
        self,
        config: OidcAuth,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._keys = SigningKeys(config, transport=transport, clock=clock)
        if config.test_only_http_origin is not None:
            log.warning(
                "OIDC_TEST_ONLY_HTTP_ISSUER is set, so plain http is trusted for %s. "
                "This must never reach a shared deployment.",
                config.test_only_http_origin,
            )

    async def __call__(self, request: Request) -> Principal:
        try:
            return await self.verify(bearer_token(request.headers.get("authorization")))
        except TokenRejected as rejected:
            log.info("Sign-in refused: %s", rejected.reason.value)
            raise _unauthorized(rejected.reason) from None
        except KeysUnavailable:
            raise _unavailable() from None

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as error:
            raise TokenRejected(_rejection(error)) from None
        algorithm = header.get("alg")
        if algorithm not in ACCEPTED:
            raise TokenRejected(Rejection.ALGORITHM)
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenRejected(Rejection.UNKNOWN_KEY)
        key = await self._keys.key_for(kid)
        if algorithm != key.algorithm:
            raise TokenRejected(Rejection.ALGORITHM)
        try:
            claims = jwt.decode(
                token,
                key.public_key,
                algorithms=[key.algorithm],
                audience=self._config.audience,
                issuer=self._config.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.InvalidTokenError as error:
            raise TokenRejected(_rejection(error)) from None
        return principal_from_claims(claims)
