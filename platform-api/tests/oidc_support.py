import asyncio
import base64
import hashlib
import hmac
import json
import time
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
import jwt
import jwt.warnings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from platform_api.app import create_app
from platform_api.oidc import OidcAuth, OidcAuthenticator
from platform_api.shared import Principal, Role, UserId
from tests.support import LOCAL_ENV

ISSUER = "https://idp.test"
AUDIENCE = "platform-api"
OIDC_ENV = {**LOCAL_ENV, "AUTH_MODE": "oidc", "OIDC_ISSUER": ISSUER, "OIDC_AUDIENCE": AUDIENCE}

ALICE_ID = "0a11ce00-0000-4000-8000-000000000001"
BOB_ID = "0b0b0000-0000-4000-8000-000000000002"
ALICE_CLAIMS: dict[str, object] = {
    "oid": ALICE_ID,
    "name": "Alice",
    "preferred_username": "alice@example.test",
    "roles": ["Operator", "Approver"],
}
BOB_CLAIMS: dict[str, object] = {
    "oid": BOB_ID,
    "name": "Bob",
    "preferred_username": "bob@example.test",
    "roles": ["Approver"],
}
OIDC_ALICE = Principal(UserId(ALICE_ID), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")


@dataclass(frozen=True)
class KeyPair:
    kid: str
    algorithm: Literal["RS256", "ES256"]
    private: RSAPrivateKey | EllipticCurvePrivateKey

    def jwk(self, **members: object) -> dict[str, object]:
        public = self.private.public_key()
        raw = (
            RSAAlgorithm.to_jwk(public)
            if isinstance(public, rsa.RSAPublicKey)
            else ECAlgorithm.to_jwk(public)
        )
        return {**json.loads(raw), "kid": self.kid, **members}

    def public_pem(self) -> bytes:
        return self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


def rsa_pair(kid: str, bits: int = 2048) -> KeyPair:
    return KeyPair(kid, "RS256", rsa.generate_private_key(public_exponent=65537, key_size=bits))


def ec_pair(kid: str, curve: ec.EllipticCurve | None = None) -> KeyPair:
    return KeyPair(kid, "ES256", ec.generate_private_key(curve or ec.SECP256R1()))


RSA_KEY = rsa_pair("rsa-1")
EC_KEY = ec_pair("ec-1")
IMPOSTOR = rsa_pair(RSA_KEY.kid)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeIssuer:
    def __init__(self, issuer: str = ISSUER, keys: Iterable[KeyPair] = (RSA_KEY, EC_KEY)) -> None:
        self.issuer = issuer
        base = urlsplit(issuer).path.rstrip("/")
        self.discovery_path = f"{base}/.well-known/openid-configuration"
        self.jwks_path = f"{base}/keys"
        self.jwks: dict[str, list[object]] = {"keys": [key.jwk() for key in keys]}
        self.jwks_answer: httpx.Response | None = None
        self.discovery: dict[str, object] = {"issuer": issuer, "jwks_uri": f"{issuer}/keys"}
        self.down = False
        self.hold: asyncio.Event | None = None
        self.requests: list[str] = []

    @property
    def discovery_fetches(self) -> int:
        return self.requests.count(self.discovery_path)

    @property
    def jwks_fetches(self) -> int:
        return self.requests.count(self.jwks_path)

    def publish(self, *keys: KeyPair) -> None:
        self.jwks = {"keys": [key.jwk() for key in keys]}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        await asyncio.sleep(0)
        if self.hold is not None:
            await self.hold.wait()
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == self.discovery_path:
            return httpx.Response(200, json=self.discovery)
        if request.url.path == self.jwks_path:
            return self.jwks_answer or httpx.Response(200, json=self.jwks)
        return httpx.Response(404)

    def authenticator(self, config: OidcAuth, clock: Clock) -> OidcAuthenticator:
        return OidcAuthenticator(config, transport=httpx.MockTransport(self.handle), clock=clock)


def oidc_app(issuer: FakeIssuer, clock: Clock, env: Mapping[str, str] = OIDC_ENV) -> FastAPI:
    app = create_app(env)
    app.state.authenticator = issuer.authenticator(app.state.settings.auth, clock)
    return app


def _claims(
    claims: Mapping[str, object] | None,
    drop: Iterable[str],
    issuer: str,
    audience: object,
    expires_in: int,
) -> dict[str, object]:
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        **ALICE_CLAIMS,
        **(claims or {}),
    }
    for name in drop:
        payload.pop(name, None)
    return payload


def token(
    key: KeyPair = RSA_KEY,
    *,
    claims: Mapping[str, object] | None = None,
    drop: Iterable[str] = (),
    headers: Mapping[str, str] | None = None,
    issuer: str = ISSUER,
    audience: object = AUDIENCE,
    expires_in: int = 300,
) -> str:
    payload = _claims(claims, drop, issuer, audience, expires_in)
    if headers is None:
        headers = {"kid": key.kid}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", jwt.warnings.InsecureKeyLengthWarning)
        return jwt.encode(payload, key.private, algorithm=key.algorithm, headers=dict(headers))


def unsigned_token() -> str:
    payload = _claims(None, (), ISSUER, AUDIENCE, 300)
    return jwt.encode(payload, "", algorithm="none", headers={"kid": RSA_KEY.kid})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hs256_token_signed_with_the_public_key(key: KeyPair = RSA_KEY) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "kid": key.kid, "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps(
            {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300, **ALICE_CLAIMS}
        ).encode()
    )
    signature = hmac.new(key.public_pem(), f"{header}.{payload}".encode(), hashlib.sha256)
    return f"{header}.{payload}.{_b64(signature.digest())}"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
