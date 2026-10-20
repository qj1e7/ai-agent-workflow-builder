from typing import Literal

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


def create_app() -> FastAPI:
    app = FastAPI(title="AI workflow builder platform API", version="0.1.0")
    app.include_router(auth.router)
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

    return app
