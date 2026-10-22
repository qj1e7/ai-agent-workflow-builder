import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.auth import ConfigError
from tests.oidc_support import OIDC_ENV as OIDC
from tests.support import LOCAL_ENV as LOCAL

HTTP_ISSUER = "http://idp.test"


def without(env: dict[str, str], name: str) -> dict[str, str]:
    return {k: v for k, v in env.items() if k != name}


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        pytest.param({}, "AUTH_MODE is not set", id="unset mode"),
        pytest.param({"AUTH_MODE": "entra"}, "not supported", id="unknown mode"),
        pytest.param({"AUTH_MODE": "dev"}, "PUBLIC_BASE_URL is not set", id="dev without a URL"),
        pytest.param(
            {**LOCAL, "PUBLIC_BASE_URL": "https://wab.azurecontainerapps.io"},
            "only runs on localhost",
            id="dev on a shared host",
        ),
        pytest.param(without(LOCAL, "STEP_KEY"), "STEP_KEY is not set", id="no step key"),
        pytest.param(
            without(OIDC, "OIDC_ISSUER"), "OIDC_ISSUER is not set", id="oidc without an issuer"
        ),
        pytest.param(
            {**OIDC, "OIDC_AUDIENCE": " "}, "OIDC_AUDIENCE is not set", id="oidc blank audience"
        ),
        pytest.param(
            without(OIDC, "PUBLIC_BASE_URL"),
            "PUBLIC_BASE_URL is not set",
            id="oidc without a base URL",
        ),
        pytest.param(
            {**OIDC, "OIDC_ISSUER": HTTP_ISSUER},
            "OIDC_ISSUER must be an absolute https URL",
            id="http issuer",
        ),
        pytest.param(
            {**OIDC, "OIDC_ISSUER": "https:///tenant"}, "OIDC_ISSUER must be", id="issuer no host"
        ),
        pytest.param(
            {**OIDC, "OIDC_ISSUER": "https://idp.test/?tenant=1"},
            "OIDC_ISSUER must be",
            id="issuer with a query",
        ),
        pytest.param(
            {**OIDC, "OIDC_ISSUER": "https://idp.test#v2"},
            "OIDC_ISSUER must be",
            id="issuer with a fragment",
        ),
        pytest.param(
            {**OIDC, "OIDC_JWKS_URL": "http://idp.test/keys"},
            "OIDC_JWKS_URL must be an absolute https URL",
            id="http JWKS URL",
        ),
        pytest.param(
            {**OIDC, "OIDC_ISSUER": HTTP_ISSUER, "OIDC_TEST_ONLY_HTTP_ISSUER": HTTP_ISSUER + "/"},
            "must equal OIDC_ISSUER",
            id="allowance not equal to the issuer",
        ),
        pytest.param(
            {
                **OIDC,
                "PUBLIC_BASE_URL": "https://wab.azurecontainerapps.io",
                "OIDC_ISSUER": HTTP_ISSUER,
                "OIDC_TEST_ONLY_HTTP_ISSUER": HTTP_ISSUER,
            },
            "only works with PUBLIC_BASE_URL on localhost",
            id="allowance on a shared host",
        ),
        pytest.param(
            {
                **OIDC,
                "OIDC_ISSUER": HTTP_ISSUER,
                "OIDC_TEST_ONLY_HTTP_ISSUER": HTTP_ISSUER,
                "OIDC_JWKS_URL": "http://other.test/keys",
            },
            "OIDC_JWKS_URL must be",
            id="http JWKS URL on another origin",
        ),
    ],
)
def test_bad_auth_config_refuses_to_start(env: dict[str, str], reason: str):
    with pytest.raises(ConfigError, match=reason):
        create_app(env)


def test_oidc_mode_allows_a_plain_http_issuer_only_on_localhost_and_only_that_origin():
    issuer = "http://mock-oidc:8080/default"
    create_app(
        {
            **OIDC,
            "OIDC_ISSUER": issuer,
            "OIDC_TEST_ONLY_HTTP_ISSUER": issuer,
            "OIDC_JWKS_URL": "http://mock-oidc:8080/default/keys",
        }
    )


def test_dev_mode_on_localhost_lists_users_and_signs_in():
    client = TestClient(create_app(LOCAL))
    users = client.get("/api/v1/dev/users").json()["users"]
    assert [u["id"] for u in users] == ["alice", "bob", "carol"]
    assert users[0]["roles"] == ["operator", "approver"]
    assert client.get("/api/v1/dev/users", headers={"X-Dev-User": "alice"}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Dev-User": "mallory"}], ids=["missing", "unknown"])
def test_dev_mode_rejects_missing_or_unknown_user(headers: dict[str, str]):
    client = TestClient(create_app(LOCAL))
    response = client.get("/api/v1/runs", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unknown or missing X-Dev-User"}
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize(
    ("user", "me"),
    [
        ("alice", {"id": "alice", "display": "Alice", "roles": ["operator", "approver"]}),
        ("bob", {"id": "bob", "display": "Bob", "roles": ["approver"]}),
    ],
)
def test_me_answers_who_the_platform_thinks_you_are(user: str, me: dict[str, object]):
    client = TestClient(create_app(LOCAL))
    assert client.get("/api/v1/me", headers={"X-Dev-User": user}).json() == me


def test_me_needs_a_signed_in_user():
    client = TestClient(create_app(LOCAL))
    assert client.get("/api/v1/me").status_code == 401
