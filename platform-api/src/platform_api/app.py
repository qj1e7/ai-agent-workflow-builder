import logging
import os
import sys
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from platform_api import auth, wiring
from platform_api.body_guard import RefuseDeepJson, refuse_invalid_request
from platform_api.builder import drafts_http, lifecycle_http, watchlist_http
from platform_api.builder import http as builder_http
from platform_api.db import Database
from platform_api.monitoring import Copier
from platform_api.monitoring import http as monitoring_http
from platform_api.nul_guard import RefuseNul
from platform_api.orchestration import http as orchestration_http
from platform_api.orchestration import people_http, practice_jira_http, settings_http
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


_LOG_HANDLER = "platform_api"


def _log_platform_api() -> None:
    """Sends platform_api's lines at INFO and above to stderr. Uvicorn sets up only its own
    loggers, so without this an INFO line, such as a skipped scheduled check, is dropped.
    Uvicorn's loggers and the root logger are left alone, so no line prints twice. Building the
    app again adds no second handler."""
    logger = logging.getLogger("platform_api")
    if any(handler.name == _LOG_HANDLER for handler in logger.handlers):
        return
    # sys.__stderr__, because a test runner swaps sys.stderr for a copy it closes later.
    handler = logging.StreamHandler(sys.__stderr__)
    handler.set_name(_LOG_HANDLER)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    _log_platform_api()
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
    app.add_middleware(RefuseNul)
    app.add_middleware(RefuseDeepJson, max_bytes=settings.max_body_bytes)
    app.add_exception_handler(RequestValidationError, refuse_invalid_request)
    app.state.people = auth.people_for(settings.auth)
    app.add_middleware(SecurityHeaders)
    app.include_router(builder_http.router)
    app.include_router(lifecycle_http.router)
    app.include_router(drafts_http.router)
    app.include_router(watchlist_http.router)
    app.include_router(orchestration_http.router)
    app.include_router(practice_jira_http.router)
    app.include_router(settings_http.router)
    app.include_router(people_http.router)
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
        copier: Copier | None = app.state.copier
        readiness = await readiness_of(
            app.state.db,
            app.state.activity_log.listening,
            None if copier is None else copier.listening,
            copy_behind=copier is not None and copier.behind,
        )
        return JSONResponse(
            status_code=200 if readiness.ready else 503,
            content=readiness.model_dump(mode="json"),
        )

    app.include_router(auth.me_router)
    match settings.auth:
        case auth.DevAuth():
            app.include_router(auth.dev_router)
        case auth.OidcAuth():
            pass
    return app


async def readiness_of(
    db: Database, listening: bool, copying: bool | None = None, *, copy_behind: bool = False
) -> Readiness:
    checks = [
        ReadinessCheck(
            name="activity_log",
            ok=listening,
            detail="listening for run events" if listening else "not listening for run events",
        )
    ]
    if copying is not None:
        checks.append(
            ReadinessCheck(
                name="activity_copy", ok=copying, detail=_copy_detail(copying, copy_behind)
            )
        )
    async with db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT ready, detail, loaded_at, workflows "
                "FROM orchestration.engine_status WHERE id = 1"
            )
        ).fetchone()
    if row is None:
        checks.append(
            ReadinessCheck(name="workflows", ok=False, detail="bootstrap has not run yet")
        )
    else:
        loaded = ", ".join(
            f"{w['name']} {'active' if w['active'] else 'inactive'}" for w in row["workflows"]
        )
        detail = f"{row['detail']} (bootstrap at {row['loaded_at'].isoformat()})"
        if loaded:
            detail += f"; loaded: {loaded}"
        checks.append(ReadinessCheck(name="workflows", ok=bool(row["ready"]), detail=detail))
    return Readiness(ready=all(c.ok for c in checks), checks=checks)


def _copy_detail(copying: bool, behind: bool) -> str:
    if not copying:
        return "not listening for events to copy to Cosmos DB"
    if behind:
        return "listening for events to copy to Cosmos DB, but the copy is behind and retrying"
    return "listening for events to copy to Cosmos DB"
