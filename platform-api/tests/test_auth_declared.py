from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from tests.support import LOCAL_ENV

SIGNED_OUT = {"/healthz", "/healthz/ready", "/api/v1/dev/users"}
SIGN_IN = [{"DevUser": []}, {"OidcBearer": []}]


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return create_app(LOCAL_ENV).openapi()


def operations(schema: dict[str, Any]):
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            yield path, method, operation


def test_dev_sign_in_is_an_api_key_header_scheme(schema: dict[str, Any]):
    scheme = schema["components"]["securitySchemes"]["DevUser"]
    assert (scheme["type"], scheme["in"], scheme["name"]) == ("apiKey", "header", "X-Dev-User")
    assert "dev" in scheme["description"].lower()


def test_real_sign_in_is_an_http_bearer_scheme(schema: dict[str, Any]):
    scheme = schema["components"]["securitySchemes"]["OidcBearer"]
    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")
    assert "oidc" in scheme["description"].lower()


def test_sign_in_is_required_on_exactly_the_routes_that_read_it(schema: dict[str, Any]):
    needs = {
        (path, method) for path, method, op in operations(schema) if op.get("security") == SIGN_IN
    }
    reads = {
        (path, method)
        for path, method, _ in operations(schema)
        if path.startswith("/api/v1/") and path not in SIGNED_OUT
    }
    assert needs == reads
    assert "security" not in schema


def test_every_signed_in_route_declares_the_401_and_503_it_answers(schema: dict[str, Any]):
    missing = [
        f"{method.upper()} {path} {status}"
        for path, method, op in operations(schema)
        if op.get("security")
        for status in ("401", "503")
        if status not in op["responses"]
    ]
    assert missing == []


ERROR_BODY = {"$ref": "#/components/schemas/ErrorBody"}


def admits_error_body(response: dict[str, Any]) -> bool:
    body = response.get("content", {}).get("application/json", {}).get("schema", {})
    return body == ERROR_BODY or ERROR_BODY in body.get("anyOf", [])


def test_every_signed_in_route_but_me_declares_the_403_for_someone_not_on_the_list(
    schema: dict[str, Any],
):
    missing = [
        f"{method.upper()} {path}"
        for path, method, op in operations(schema)
        if op.get("security")
        and path != "/api/v1/me"
        and not admits_error_body(op["responses"].get("403", {}))
    ]
    assert missing == []
    me = schema["paths"]["/api/v1/me"]["get"]["responses"]
    assert "403" not in me


def test_a_signed_in_route_answers_401_without_the_header():
    client = TestClient(create_app(LOCAL_ENV))
    response = client.get("/api/v1/runs")
    assert response.status_code == 401
    assert set(response.json()) == {"detail"}
