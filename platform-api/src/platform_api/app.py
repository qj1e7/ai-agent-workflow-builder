import os
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import FastAPI

from platform_api import auth
from platform_api.builder import http as builder_http
from platform_api.monitoring import http as monitoring_http
from platform_api.orchestration import http as orchestration_http
from platform_api.wire import WireModel, not_implemented


class Health(WireModel):
    status: Literal["ok"] = "ok"


class ReadinessCheck(WireModel):
    name: str
    ok: bool
    detail: str


class Readiness(WireModel):
    ready: bool
    checks: list[ReadinessCheck]


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    config = auth.auth_config(os.environ if env is None else env)
    app = FastAPI(title="AI workflow builder platform API", version="0.1.0")
    app.state.authenticator = auth.authenticator_for(config)
    app.include_router(builder_http.router)
    app.include_router(orchestration_http.router)
    app.include_router(monitoring_http.router)

    @app.get("/healthz", tags=["health"])
    def healthz() -> Health:
        return Health()

    @app.get(
        "/healthz/ready",
        tags=["health"],
        responses={503: {"model": Readiness, "description": "Not ready to take traffic"}},
    )
    def ready() -> Readiness:
        not_implemented()

    match config:
        case auth.DevAuth():
            app.include_router(auth.dev_router)
            _document_dev_header(app)
    return app


def _document_dev_header(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = FastAPI.openapi(app)
            schema.setdefault("components", {})["securitySchemes"] = {
                "DevUser": {
                    "type": "apiKey",
                    "in": "header",
                    "name": auth.DEV_USER_HEADER,
                    "description": "Local sign-in stub. One of the ids from GET /api/v1/dev/users.",
                }
            }
            schema["security"] = [{"DevUser": []}]
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
