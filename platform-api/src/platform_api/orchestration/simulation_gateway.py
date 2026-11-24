"""The simulation gateway (ADR 0054, section 3), a service of its own in the simulation's network:

    uvicorn platform_api.orchestration.simulation_gateway:create_app --factory --port 8600

The simulation n8n's WAB_API_URL points here, so our blocks there call it in place of
platform-api. It mounts platform-api's own router for those calls, so each block gets the same
answers, refusals and checks, and SimulatedCalls answers them from the scenario
(simulated_calls.py).

It is not a mode of platform-api. It runs from the same image as its own process, and reads only
the settings below: the simulation's own node key and start secret, and the simulation n8n's
address and owner, whose executions it reads to link each call. It has no database, and no Jira,
Teams, Slack or model key.

The simulation's driver uses two more routes. Each is signed with the simulation's start secret,
which our blocks never hold, so a workflow under simulation can't start or read a simulated run:

- `POST /simulation/v1/starts` takes a workflow id and a scenario, and answers the start item for
  n8n's run by hand.
- `GET /simulation/v1/runs/{nonce}` answers that run's record for the grader.

A request is signed in X-Wab-Signature: HMAC-SHA256, hex-encoded, with the start secret, over the
method, the path, X-Wab-Expires (Unix seconds) and the body, each of the first three followed by a
line break. Expires may be up to a minute past and six minutes ahead, as a start to Start from the
Portal may.
"""

import hashlib
import hmac
import logging
import os
import sys
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from platform_api.auth import ConfigError
from platform_api.body_guard import RefuseDeepJson, refuse_invalid_request
from platform_api.nul_guard import RefuseNul
from platform_api.orchestration import n8n_calls_http
from platform_api.orchestration.dispatch import N8nWaker
from platform_api.orchestration.n8n import N8nApi
from platform_api.orchestration.simulated_calls import (
    MockGitHub,
    Scenario,
    SimulatedCalls,
    SimulatedRun,
    Unsealed,
)
from platform_api.settings import MAX_BODY_BYTES_DEFAULT, N8nOwner
from platform_api.wire import WireIn, WireModel, error_response

SIGNATURE_HEADER = "X-Wab-Signature"
EXPIRES_HEADER = "X-Wab-Expires"
PAST = 60
AHEAD = 360
BAD_SIGNATURE = "The signature does not match."

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewaySettings:
    node_key: str = field(repr=False)
    """WAB_NODE_KEY: the simulation's own, which the simulation n8n's blocks send."""
    start_secret: str = field(repr=False)
    """WAB_START_SECRET: the simulation's own, which signs the driver's requests."""
    n8n_base_url: str
    """N8N_BASE_URL: the simulation n8n, whose executions it reads and wakes."""
    n8n_owner: N8nOwner
    """N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD: the simulation n8n's owner, as its bootstrap made."""
    mock_github_url: str | None = None
    """MOCK_GITHUB_URL: mock GitHub, for a Read the scenario serves from the mock."""


def gateway_settings_from_env(env: Mapping[str, str]) -> GatewaySettings:
    """Only these settings are read. Anything else the environment holds is left alone."""

    def required(name: str) -> str:
        value = env.get(name, "").strip()
        if not value:
            raise ConfigError(f"{name} is not set.")
        return value

    return GatewaySettings(
        node_key=required("WAB_NODE_KEY"),
        start_secret=required("WAB_START_SECRET"),
        n8n_base_url=required("N8N_BASE_URL").rstrip("/"),
        n8n_owner=N8nOwner(required("N8N_OWNER_EMAIL"), required("N8N_OWNER_PASSWORD")),
        mock_github_url=env.get("MOCK_GITHUB_URL", "").strip().rstrip("/") or None,
    )


def control_signature(secret: str, method: str, path: str, expires: int, body: bytes) -> str:
    message = f"{method}\n{path}\n{expires}\n".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


async def signed_body(request: Request) -> bytes:
    """The request's body, once its signature checks out with the start secret. Refused with
    401 before the body is read as JSON."""
    settings: GatewaySettings = request.app.state.settings
    body = await request.body()
    given = request.headers.get(SIGNATURE_HEADER, "")
    expires_text = request.headers.get(EXPIRES_HEADER, "")
    if not expires_text.isdigit() or not given:
        raise HTTPException(status_code=401, detail=BAD_SIGNATURE)
    expires = int(expires_text)
    now = int(time.time())
    if not now - PAST <= expires <= now + AHEAD:
        raise HTTPException(status_code=401, detail="This request has expired.")
    expected = control_signature(
        settings.start_secret, request.method, request.url.path, expires, body
    )
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail=BAD_SIGNATURE)
    return body


SignedBody = Annotated[bytes, Depends(signed_body)]


def current_calls(request: Request) -> SimulatedCalls:
    calls: SimulatedCalls = request.app.state.node_calls
    return calls


CurrentCalls = Annotated[SimulatedCalls, Depends(current_calls)]


class StartIn(WireIn):
    workflow_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$", description="n8n's id."
    )
    scenario: Scenario


class StartItem(WireModel):
    """The trigger's output for n8n's run by hand, as platform-api's test run gives it."""

    nonce: str
    kind: Literal["test"] = "test"
    workflow_id: str


class StartOut(WireModel):
    nonce: str
    item: StartItem


class Health(WireModel):
    status: Literal["ok"] = "ok"


REFUSED = {401: error_response("Not signed with the simulation's start secret")}

control = APIRouter(prefix="/simulation/v1", tags=["simulation"])


@control.post(
    "/starts",
    status_code=201,
    response_model=StartOut,
    description="A simulated run of one workflow for one scenario. n8n runs the workflow by hand "
    "with the item as Start from the Portal's output.",
    responses={**REFUSED, 422: error_response("The scenario is not one the gateway can play")},
)
async def start(body: SignedBody, calls: CurrentCalls) -> StartOut | JSONResponse:
    try:
        given = StartIn.model_validate_json(body)
    except ValidationError as error:
        problems = [
            {"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": problems})
    run = calls.start(given.workflow_id, given.scenario)
    return StartOut(nonce=run.nonce, item=StartItem(nonce=run.nonce, workflow_id=run.workflow_id))


@control.get(
    "/runs/{nonce}",
    response_model=SimulatedRun,
    description="One simulated run's record: each call in order, what was proposed, what Ask "
    "for a yes got and what the write would have made.",
    responses={**REFUSED, 404: error_response("The gateway keeps no such run")},
)
async def record(nonce: str, _: SignedBody, calls: CurrentCalls) -> SimulatedRun | JSONResponse:
    run = calls.run(nonce)
    if run is None:
        return JSONResponse(status_code=404, content={"detail": "No such simulated run."})
    return run


def gateway_app(
    settings: GatewaySettings,
    calls: SimulatedCalls,
    closers: Sequence[Callable[[], Awaitable[None]]] = (),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        await calls.close()
        for close in closers:
            await close()

    app = FastAPI(
        title="Simulation gateway",
        version="0.1.0",
        lifespan=lifespan,
        redirect_slashes=False,
    )
    # n8n_calls_http reads the node key from settings.node_key and the calls from node_calls.
    app.state.settings = settings
    app.state.node_calls = calls
    app.add_middleware(RefuseNul)
    app.add_middleware(RefuseDeepJson, max_bytes=MAX_BODY_BYTES_DEFAULT)
    app.add_exception_handler(RequestValidationError, refuse_invalid_request)
    app.include_router(n8n_calls_http.router)
    app.include_router(control)

    @app.get("/healthz", tags=["health"])
    def healthz() -> Health:
        return Health()

    return app


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    _log()
    settings = gateway_settings_from_env(os.environ if env is None else env)
    n8n = N8nApi(settings.n8n_base_url, settings.n8n_owner)
    waker = N8nWaker(settings.n8n_base_url, settings.node_key, Unsealed())
    github = None if settings.mock_github_url is None else MockGitHub(settings.mock_github_url)
    calls = SimulatedCalls(n8n, waker, github)
    closers = [n8n.close, waker.close, *([] if github is None else [github.close])]
    log.info("the simulation gateway answers the simulation n8n at %s", settings.n8n_base_url)
    return gateway_app(settings, calls, closers)


def _log() -> None:
    """As platform-api's own: httpx logs each address at INFO, and n8n's resume address carries
    its signature."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logger = logging.getLogger("platform_api")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.__stderr__)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
