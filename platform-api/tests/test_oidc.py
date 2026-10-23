import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.oidc import (
    KEYS_MAX_AGE_SECONDS,
    KEYS_MAX_STALE_SECONDS,
    MAX_DOCUMENT_BYTES,
    REFETCH_COOLDOWN_SECONDS,
)
from platform_api.orchestration.service import NotFound
from tests.declared import FakeOrchestrator, declared_status
from tests.oidc_support import (
    ALICE_ID,
    EC_KEY,
    IMPOSTOR,
    ISSUER,
    OIDC_ENV,
    RSA_KEY,
    Clock,
    FakeIssuer,
    KeyPair,
    bearer,
    ec_pair,
    hs256_token_signed_with_the_public_key,
    oidc_app,
    rsa_pair,
    token,
    unsigned_token,
)
from tests.support import LOCAL_ENV

ME = "/api/v1/me"
INVALID_TOKEN = 'Bearer error="invalid_token"'
SMALL_RSA = rsa_pair("small", bits=1024)
P384 = ec_pair("p384", ec.SECP384R1())
EC_ENC = ec_pair("enc")
EC_ES384 = ec_pair("es384")
EC_RS = ec_pair("rs")


@pytest.fixture
def issuer() -> FakeIssuer:
    return FakeIssuer()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(issuer: FakeIssuer, clock: Clock) -> FastAPI:
    return oidc_app(issuer, clock)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def refused(app: FastAPI, response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == INVALID_TOKEN
    assert set(response.json()) == {"detail"}
    declared_status(app, "GET", ME, response)


def unavailable(app: FastAPI, response: httpx.Response) -> None:
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert set(response.json()) == {"detail"}
    declared_status(app, "GET", ME, response)


def async_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def eventually(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(1):
        while not condition():
            await asyncio.sleep(0)


class Drip(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            yield b" "
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("key", [RSA_KEY, EC_KEY], ids=["RS256", "ES256"])
def test_a_valid_token_signs_in_as_the_person_it_names(client: TestClient, key: KeyPair):
    response = client.get(ME, headers=bearer(token(key)))
    assert response.status_code == 200
    assert response.json() == {
        "id": ALICE_ID,
        "display": "Alice",
        "roles": ["operator", "approver"],
    }


def test_startup_does_not_contact_the_issuer(issuer: FakeIssuer, clock: Clock):
    oidc_app(issuer, clock)
    assert issuer.requests == []


def test_an_expired_token_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(expires_in=-120))))


def test_a_token_expired_within_the_leeway_still_signs_in(client: TestClient):
    assert client.get(ME, headers=bearer(token(expires_in=-30))).status_code == 200


def test_a_token_not_yet_valid_is_refused(client: TestClient, app: FastAPI):
    not_yet = token(claims={"nbf": int(time.time()) + 300})
    refused(app, client.get(ME, headers=bearer(not_yet)))


def test_a_token_from_another_issuer_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(issuer="https://other.test"))))


def test_a_token_for_another_audience_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(audience="other-api"))))


def test_a_token_with_a_bad_signature_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(IMPOSTOR))))


def test_a_token_without_exp_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(drop=["exp"]))))


def test_a_token_that_is_not_a_jwt_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer("not-a-token")))


def test_no_authorization_header_answers_401_with_a_bearer_challenge(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert set(response.json()) == {"detail"}
    declared_status(app, "GET", ME, response)
    assert issuer.requests == []


def test_x_dev_user_is_ignored_in_oidc_mode(client: TestClient):
    assert client.get(ME, headers={"X-Dev-User": "alice"}).status_code == 401


@pytest.mark.parametrize(
    "authorization",
    ["Bearer", "Bearer a b", "Basic abc"],
    ids=["no token", "two tokens", "another scheme"],
)
def test_an_authorization_header_without_one_bearer_token_is_refused(
    client: TestClient, authorization: str
):
    assert client.get(ME, headers={"Authorization": authorization}).status_code == 401


def test_the_bearer_scheme_is_case_insensitive(client: TestClient):
    assert client.get(ME, headers={"Authorization": f"bearer {token()}"}).status_code == 200


def test_an_unsigned_token_is_refused_without_asking_the_issuer(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    refused(app, client.get(ME, headers=bearer(unsigned_token())))
    assert issuer.requests == []


def test_hs256_signed_with_the_public_key_is_refused_without_asking_the_issuer(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    refused(app, client.get(ME, headers=bearer(hs256_token_signed_with_the_public_key())))
    assert issuer.requests == []


@pytest.mark.parametrize(
    ("key", "kid"),
    [(EC_KEY, RSA_KEY.kid), (RSA_KEY, EC_KEY.kid)],
    ids=["ES256 header on an RSA key", "RS256 header on an EC key"],
)
def test_the_header_algorithm_must_be_the_one_the_key_verifies(
    client: TestClient, app: FastAPI, key: KeyPair, kid: str
):
    refused(app, client.get(ME, headers=bearer(token(key, headers={"kid": kid}))))


@pytest.mark.parametrize("headers", [{}, {"kid": ""}], ids=["absent", "empty"])
def test_a_token_without_a_kid_is_refused_without_asking_the_issuer(
    client: TestClient, app: FastAPI, issuer: FakeIssuer, headers: dict[str, str]
):
    refused(app, client.get(ME, headers=bearer(token(headers=headers))))
    assert issuer.requests == []


def test_a_rotated_key_is_found_by_fetching_the_keys_again(
    client: TestClient, issuer: FakeIssuer, clock: Clock
):
    assert client.get(ME, headers=bearer(token())).status_code == 200
    rotated = rsa_pair("rsa-2")
    issuer.publish(rotated)
    clock.advance(REFETCH_COOLDOWN_SECONDS)
    assert client.get(ME, headers=bearer(token(rotated))).status_code == 200
    assert client.get(ME, headers=bearer(token())).status_code == 401
    assert (issuer.discovery_fetches, issuer.jwks_fetches) == (1, 2)


def test_an_unknown_kid_inside_the_cooldown_is_refused_without_a_fetch(
    client: TestClient, issuer: FakeIssuer, clock: Clock
):
    assert client.get(ME, headers=bearer(token())).status_code == 200
    clock.advance(REFETCH_COOLDOWN_SECONDS - 1)
    assert client.get(ME, headers=bearer(token(rsa_pair("rsa-9")))).status_code == 401
    assert issuer.jwks_fetches == 1


@pytest.mark.parametrize(
    ("issuer_up", "status"),
    [(True, 401), (False, 503)],
    ids=["the reload succeeded", "the reload failed"],
)
def test_an_unknown_kid_inside_the_cooldown_answers_as_the_reload_that_opened_it_did(
    client: TestClient, issuer: FakeIssuer, clock: Clock, issuer_up: bool, status: int
):
    assert client.get(ME, headers=bearer(token())).status_code == 200
    issuer.down = not issuer_up
    clock.advance(REFETCH_COOLDOWN_SECONDS)
    unknown = bearer(token(rsa_pair("rsa-9")))
    assert client.get(ME, headers=unknown).status_code == status
    clock.advance(1)
    assert client.get(ME, headers=unknown).status_code == status
    assert issuer.jwks_fetches == 2


def test_an_unknown_kid_is_still_refused_after_the_keys_are_fetched_again(
    client: TestClient, issuer: FakeIssuer, clock: Clock
):
    assert client.get(ME, headers=bearer(token())).status_code == 200
    clock.advance(REFETCH_COOLDOWN_SECONDS)
    assert client.get(ME, headers=bearer(token(rsa_pair("rsa-9")))).status_code == 401
    assert issuer.jwks_fetches == 2


def test_a_flood_of_made_up_kids_costs_the_issuer_one_fetch(client: TestClient, issuer: FakeIssuer):
    for n in range(20):
        made_up = token(headers={"kid": f"made-up-{n}"})
        assert client.get(ME, headers=bearer(made_up)).status_code == 401
    assert issuer.jwks_fetches == 1


def test_discovery_naming_another_issuer_is_a_failed_load(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    issuer.discovery["issuer"] = "https://other.test"
    unavailable(app, client.get(ME, headers=bearer(token())))
    assert issuer.jwks_fetches == 0


def test_a_discovered_jwks_uri_that_is_not_https_is_a_failed_load(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    issuer.discovery["jwks_uri"] = "http://idp.test/keys"
    unavailable(app, client.get(ME, headers=bearer(token())))
    assert issuer.jwks_fetches == 0


def test_a_configured_jwks_url_skips_discovery(issuer: FakeIssuer, clock: Clock):
    app = oidc_app(issuer, clock, {**OIDC_ENV, "OIDC_JWKS_URL": f"{ISSUER}/keys"})
    assert TestClient(app).get(ME, headers=bearer(token())).status_code == 200
    assert (issuer.discovery_fetches, issuer.jwks_fetches) == (0, 1)


def test_a_key_fetch_failure_with_no_keys_is_503_with_retry_after(
    client: TestClient, app: FastAPI, issuer: FakeIssuer
):
    issuer.down = True
    unavailable(app, client.get(ME, headers=bearer(token())))


@pytest.mark.anyio
async def test_an_issuer_that_drips_its_keys_is_a_failed_load_at_the_deadline(
    issuer: FakeIssuer, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("platform_api.oidc.FETCH_DEADLINE_SECONDS", 0.2)
    issuer.jwks_answer = httpx.Response(200, stream=Drip())
    app = oidc_app(issuer, clock)
    async with async_client(app) as client, asyncio.timeout(1):
        response = await client.get(ME, headers=bearer(token()))
    unavailable(app, response)
    assert issuer.jwks_fetches == 1


@pytest.mark.anyio
async def test_a_failed_refresh_keeps_the_keys_already_loaded(
    issuer: FakeIssuer, clock: Clock, caplog: pytest.LogCaptureFixture
):
    async with async_client(oidc_app(issuer, clock)) as client:
        assert (await client.get(ME, headers=bearer(token()))).status_code == 200
        issuer.down = True
        clock.advance(KEYS_MAX_AGE_SECONDS)
        with caplog.at_level(logging.WARNING, logger="platform_api.oidc"):
            assert (await client.get(ME, headers=bearer(token()))).status_code == 200
            await eventually(lambda: "Could not load the identity provider's keys" in caplog.text)
        assert (await client.get(ME, headers=bearer(token()))).status_code == 200
    assert issuer.jwks_fetches == 2


@pytest.mark.anyio
async def test_a_known_kid_is_answered_from_stale_keys_while_they_refresh_in_the_background(
    issuer: FakeIssuer, clock: Clock
):
    rotated = rsa_pair("rsa-2")
    hold = asyncio.Event()
    async with async_client(oidc_app(issuer, clock)) as client:
        assert (await client.get(ME, headers=bearer(token()))).status_code == 200
        issuer.publish(RSA_KEY, rotated)
        clock.advance(KEYS_MAX_AGE_SECONDS)
        issuer.hold = hold
        async with asyncio.timeout(1):
            responses = await asyncio.gather(
                *(client.get(ME, headers=bearer(token())) for _ in range(3))
            )
        assert [r.status_code for r in responses] == [200] * 3
        await eventually(lambda: issuer.jwks_fetches == 2)
        hold.set()
        assert (await client.get(ME, headers=bearer(token(rotated)))).status_code == 200
    assert issuer.jwks_fetches == 2


def test_keys_older_than_a_day_are_refused_when_they_cannot_be_reloaded(
    client: TestClient, app: FastAPI, issuer: FakeIssuer, clock: Clock
):
    assert client.get(ME, headers=bearer(token())).status_code == 200
    issuer.down = True
    clock.advance(KEYS_MAX_STALE_SECONDS - 1)
    assert client.get(ME, headers=bearer(token())).status_code == 200
    clock.advance(1)
    unavailable(app, client.get(ME, headers=bearer(token())))


def test_a_down_issuer_is_asked_at_most_once_per_cooldown(
    client: TestClient, issuer: FakeIssuer, clock: Clock
):
    issuer.down = True
    assert client.get(ME, headers=bearer(token())).status_code == 503
    clock.advance(1)
    assert client.get(ME, headers=bearer(token())).status_code == 503
    assert issuer.discovery_fetches == 1
    issuer.down = False
    clock.advance(REFETCH_COOLDOWN_SECONDS)
    assert client.get(ME, headers=bearer(token())).status_code == 200
    assert issuer.discovery_fetches == 2


@pytest.mark.parametrize("document", ["discovery", "jwks"])
def test_an_oversized_document_is_a_failed_load(
    client: TestClient, app: FastAPI, issuer: FakeIssuer, document: str
):
    padding = "A" * MAX_DOCUMENT_BYTES
    if document == "discovery":
        issuer.discovery["padding"] = padding
    else:
        issuer.jwks["keys"].append(padding)
    unavailable(app, client.get(ME, headers=bearer(token())))


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500),
        httpx.Response(302, headers={"location": f"{ISSUER}/elsewhere"}),
        httpx.Response(200, content=b"{not json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"keys": "not a list"}),
        httpx.Response(200, json={"keys": []}),
    ],
    ids=["500", "redirect", "not JSON", "not an object", "keys not a list", "no usable keys"],
)
def test_a_jwks_answer_without_usable_keys_is_a_failed_load(
    client: TestClient, app: FastAPI, issuer: FakeIssuer, answer: httpx.Response
):
    issuer.jwks_answer = answer
    unavailable(app, client.get(ME, headers=bearer(token())))


@pytest.mark.parametrize(
    ("published", "members", "signer"),
    [
        pytest.param(SMALL_RSA, {}, SMALL_RSA, id="RSA under 2048 bits"),
        pytest.param(P384, {}, EC_KEY, id="EC not on P-256"),
        pytest.param(EC_ENC, {"use": "enc"}, EC_ENC, id="use enc"),
        pytest.param(EC_ES384, {"alg": "ES384"}, EC_ES384, id="alg member for another algorithm"),
        pytest.param(EC_RS, {"alg": "RS256"}, EC_RS, id="alg member for another key family"),
    ],
)
def test_a_key_that_cannot_verify_rs256_or_es256_is_dropped(
    client: TestClient,
    issuer: FakeIssuer,
    published: KeyPair,
    members: dict[str, str],
    signer: KeyPair,
):
    issuer.jwks["keys"].append(published.jwk(**members))
    under_that_kid = token(signer, headers={"kid": published.kid})
    assert client.get(ME, headers=bearer(under_that_kid)).status_code == 401
    assert client.get(ME, headers=bearer(token())).status_code == 200


@pytest.mark.parametrize(
    "entry",
    [
        {"kty": "oct", "kid": "oct-1", "k": "c2VjcmV0"},
        {
            "kty": "OKP",
            "kid": "okp-1",
            "crv": "Ed25519",
            "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo",
        },
        {**EC_KEY.jwk(), "kid": ""},
        {**EC_KEY.jwk(), "x": "!!!"},
        {**EC_KEY.jwk(), "x": 5},
        "not an object",
    ],
    ids=["oct", "OKP", "no kid", "garbage coordinate", "coordinate not a string", "not an object"],
)
def test_an_entry_that_is_not_a_signing_key_does_not_spoil_the_document(
    client: TestClient, issuer: FakeIssuer, entry: object
):
    issuer.jwks["keys"].append(entry)
    assert client.get(ME, headers=bearer(token())).status_code == 200


def test_a_kid_published_twice_is_dropped(client: TestClient, issuer: FakeIssuer):
    first, second = ec_pair("dup"), ec_pair("dup")
    issuer.publish(RSA_KEY, first, second)
    assert client.get(ME, headers=bearer(token(first))).status_code == 401
    assert client.get(ME, headers=bearer(token(second))).status_code == 401
    assert client.get(ME, headers=bearer(token())).status_code == 200


@pytest.mark.parametrize(
    ("claims", "drop", "expected"),
    [
        ({"oid": "o-1", "sub": "s-1"}, [], "o-1"),
        ({"sub": "s-1"}, ["oid"], "s-1"),
        ({"oid": "", "sub": "s-1"}, [], "s-1"),
        ({"oid": 5, "sub": "s-1"}, [], "s-1"),
    ],
    ids=["oid wins", "sub without oid", "empty oid", "oid not a string"],
)
def test_the_id_is_oid_then_sub(
    client: TestClient, claims: dict[str, object], drop: list[str], expected: str
):
    response = client.get(ME, headers=bearer(token(claims=claims, drop=drop)))
    assert response.json()["id"] == expected


def test_a_token_naming_no_person_is_refused(client: TestClient, app: FastAPI):
    refused(app, client.get(ME, headers=bearer(token(drop=["oid", "sub"]))))


@pytest.mark.parametrize(
    ("claims", "drop", "expected"),
    [
        ({"name": "Alice Liddell"}, [], "Alice Liddell"),
        ({}, ["name"], "alice@example.test"),
        ({}, ["name", "preferred_username"], ALICE_ID),
        ({"name": "  Al\x00ice​ \n"}, [], "Alice"),
        ({"name": "A" * 200}, [], "A" * 120),
        ({"name": "\x00\x01"}, [], ALICE_ID),
    ],
    ids=["name", "preferred_username", "the id", "cleaned", "cut to 120", "empty after cleaning"],
)
def test_the_display_name_is_name_then_preferred_username_then_the_id(
    client: TestClient, claims: dict[str, object], drop: list[str], expected: str
):
    response = client.get(ME, headers=bearer(token(claims=claims, drop=drop)))
    assert response.json()["display"] == expected


def test_an_unknown_role_is_ignored(client: TestClient):
    roles = ["Operator", "Admin", 5, "operator", "APPROVER"]
    response = client.get(ME, headers=bearer(token(claims={"roles": roles})))
    assert response.json()["roles"] == ["operator"]


def test_a_roles_claim_that_is_not_a_list_counts_as_no_roles(client: TestClient):
    response = client.get(ME, headers=bearer(token(claims={"roles": "Operator"})))
    assert response.json()["roles"] == []


@pytest.mark.parametrize("roles", [{"roles": []}, None], ids=["empty", "absent"])
def test_a_person_without_a_known_role_can_read_but_not_act_as_an_operator(
    issuer: FakeIssuer, clock: Clock, roles: dict[str, object] | None
):
    app = oidc_app(issuer, clock)
    app.state.orchestrator = FakeOrchestrator(retry=NotFound())
    client = TestClient(app)
    nobody = bearer(token(claims=roles, drop=[] if roles else ["roles"]))
    assert client.get(ME, headers=nobody).json()["roles"] == []
    response = client.post("/api/v1/runs/run_1/retry", headers=nobody)
    assert response.status_code == 403
    declared_status(app, "POST", "/api/v1/runs/{run_id}/retry", response)
    operator = bearer(token(claims={"roles": ["Operator"]}))
    assert client.post("/api/v1/runs/run_1/retry", headers=operator).status_code == 404


def test_the_reason_for_a_refusal_is_logged_and_not_sent(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="platform_api.oidc"):
        response = client.get(ME, headers=bearer(token(expires_in=-120)))
    assert "expired" not in response.json()["detail"]
    assert "expired" in caplog.text


def test_dev_users_is_not_served_in_oidc_mode(client: TestClient):
    assert client.get("/api/v1/dev/users").status_code == 404


def test_the_contract_does_not_depend_on_the_auth_mode():
    dev = create_app(LOCAL_ENV).openapi()
    del dev["paths"]["/api/v1/dev/users"]
    for schema in ("DevUser", "DevUsers"):
        del dev["components"]["schemas"][schema]
    assert create_app(OIDC_ENV).openapi() == dev


def test_a_plain_http_issuer_is_trusted_only_through_the_test_only_allowance(
    clock: Clock, caplog: pytest.LogCaptureFixture
):
    issuer = FakeIssuer("http://mock-oidc:8080/default")
    env = {**OIDC_ENV, "OIDC_ISSUER": issuer.issuer, "OIDC_TEST_ONLY_HTTP_ISSUER": issuer.issuer}
    with caplog.at_level(logging.WARNING, logger="platform_api.oidc"):
        app = oidc_app(issuer, clock, env)
    assert "OIDC_TEST_ONLY_HTTP_ISSUER" in caplog.text
    client = TestClient(app)
    assert client.get(ME, headers=bearer(token(issuer=issuer.issuer))).status_code == 200
    assert issuer.requests[0] == "/default/.well-known/openid-configuration"


def test_the_allowance_covers_only_the_issuers_origin(clock: Clock):
    issuer = FakeIssuer("http://mock-oidc:8080/default")
    issuer.discovery["jwks_uri"] = "http://elsewhere:8080/keys"
    env = {**OIDC_ENV, "OIDC_ISSUER": issuer.issuer, "OIDC_TEST_ONLY_HTTP_ISSUER": issuer.issuer}
    app = oidc_app(issuer, clock, env)
    assert TestClient(app).get(ME, headers=bearer(token(issuer=issuer.issuer))).status_code == 503


@pytest.mark.anyio
async def test_concurrent_first_requests_share_one_key_load(issuer: FakeIssuer, clock: Clock):
    async with async_client(oidc_app(issuer, clock)) as client:
        responses = await asyncio.gather(
            *(client.get(ME, headers=bearer(token())) for _ in range(5))
        )
    assert [r.status_code for r in responses] == [200] * 5
    assert (issuer.discovery_fetches, issuer.jwks_fetches) == (1, 1)
