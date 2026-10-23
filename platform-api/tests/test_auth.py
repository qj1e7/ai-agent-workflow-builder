import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.auth import ConfigError
from tests.support import LOCAL_ENV as LOCAL


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
        pytest.param(
            {k: v for k, v in LOCAL.items() if k != "STEP_KEY"},
            "STEP_KEY is not set",
            id="no step key",
        ),
    ],
)
def test_bad_auth_config_refuses_to_start(env: dict[str, str], reason: str):
    with pytest.raises(ConfigError, match=reason):
        create_app(env)


def test_dev_mode_on_localhost_lists_users_and_signs_in():
    client = TestClient(create_app(LOCAL))
    users = client.get("/api/v1/dev/users").json()["users"]
    assert [u["id"] for u in users] == ["alice", "bob", "carol"]
    assert users[0]["roles"] == ["operator", "approver"]
    assert client.get("/api/v1/dev/users", headers={"X-Dev-User": "alice"}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Dev-User": "mallory"}], ids=["missing", "unknown"])
def test_dev_mode_rejects_missing_or_unknown_user(headers: dict[str, str]):
    client = TestClient(create_app(LOCAL))
    assert client.get("/api/v1/runs", headers=headers).status_code == 401
