import os
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from platform_api import auth, wiring
from platform_api.builder import http as builder_http
from platform_api.db import Database
from platform_api.monitoring import http as monitoring_http
from platform_api.orchestration import http as orchestration_http
from platform_api.security_headers import SecurityHeaders
from platform_api.settings import Settings, settings_from_env
from platform_api.wire import WireModel


class Health(WireModel):
    status: Literal["ok"] = "ok"


class ReadinessCheck(WireModel):
    name: str
    ok: bool
    detail: str


class Readiness(WireModel):
    ready: bool
    checks: list[ReadinessCheck]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    services = await wiring.build(settings)
    wiring.install(app, services)
    runner = wiring.Runner(services)
    runner.start()
    try:
        yield
    finally:
        await runner.stop()


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    settings = settings_from_env(os.environ if env is None else env)
    app = FastAPI(
        title="AI workflow builder platform API",
        version="0.1.0",
        lifespan=lifespan,
        # A slash redirect puts the request's Host in an absolute Location.
        # Behind the Portal's nginx that is the internal name platform-api:8000.
        redirect_slashes=False,
    )
    app.state.settings = settings
    app.state.step_key = settings.step_key
    app.state.authenticator = auth.authenticator_for(settings.auth)
    app.add_middleware(SecurityHeaders)
    app.include_router(builder_http.router)
    app.include_router(orchestration_http.router)
    app.include_router(monitoring_http.router)

    @app.get("/healthz", tags=["health"])
    def healthz() -> Health:
        return Health()

    @app.get(
        "/healthz/ready",
        tags=["health"],
        response_model=Readiness,
        responses={503: {"model": Readiness, "description": "Not ready to take traffic"}},
    )
    async def ready() -> JSONResponse:
        readiness = await readiness_of(app.state.db, app.state.activity_log.listening)
        return JSONResponse(
            status_code=200 if readiness.ready else 503,
            content=readiness.model_dump(mode="json"),
        )

    match settings.auth:
        case auth.DevAuth():
            app.include_router(auth.dev_router)
            _document_dev_header(app)
    return app


async def readiness_of(db: Database, listening: bool) -> Readiness:
    checks = [
        ReadinessCheck(
            name="activity_log",
            ok=listening,
            detail="listening for run events" if listening else "not listening for run events",
        )
    ]
    async with db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT ready, detail, loaded_at FROM orchestration.engine_status WHERE id = 1"
            )
        ).fetchone()
    if row is None:
        checks.append(
            ReadinessCheck(name="workflows", ok=False, detail="bootstrap has not run yet")
        )
    else:
        detail = f"{row['detail']} (bootstrap at {row['loaded_at'].isoformat()})"
        checks.append(ReadinessCheck(name="workflows", ok=bool(row["ready"]), detail=detail))
    return Readiness(ready=all(c.ok for c in checks), checks=checks)


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
