"""The simulation gateway (ADR 0054, section 3), a service of its own in the simulation's network:

    uvicorn platform_api.orchestration.simulation_gateway:create_app --factory --port 8600

The simulation n8n's WAB_API_URL points here, so our blocks there call it in place of
platform-api. It mounts platform-api's own router for those calls, so each block gets the same
answers, refusals and checks, and SimulatedCalls answers them from the scenario
(simulated_calls.py).

It is not a mode of platform-api. It runs from the same image as its own process, and reads only
the settings below: the simulation's own node key and start secret, the simulation n8n's address
and owner, whose executions it reads to link each call and where it makes each version's copy,
and the mocks there. It has no database, and no real Jira, Teams, Slack or model key.

The simulation's driver uses five more routes, each signed with the simulation's start secret:

- `POST /simulation/v1/simulations` takes a workflow version, and its scenarios or none, and runs
  each scenario on a copy of its own, grades it and deletes the copy (simulations.py). Without
  scenarios it runs code's templates. With fall_back, scenarios that don't fit are refused and
  code's templates run in their place, as for the scenario writer's. Recorded samples sent with
  it are scrubbed before use.
- `POST /simulation/v1/plans` takes a workflow version and its recorded samples, and answers the
  version as a simulation sees it: each block's role and the plays a simulation can make of it,
  the kinds that apply and the samples, scrubbed. The scenario writer is offered this (PR 6).
  It makes nothing.
- `POST /simulation/v1/copies` takes a workflow version, makes its copy in the simulation n8n with
  only mock keys (mock_setup.py), and answers the copy's id and how each block runs in it. The
  caller deletes the copy.
- `POST /simulation/v1/starts` takes a workflow id and a scenario, and answers the start item for
  n8n's run by hand.
- `GET /simulation/v1/runs/{nonce}` answers that run's record for the grader.

The simulation n8n's own environment holds the start secret, since Start from the Portal checks a
start with it. A workflow under simulation can't read it, or call these routes: n8n blocks
expressions from reading its environment (N8N_BLOCK_ENV_ACCESS_IN_NODE), Code runs in the
external task runner, which holds none of n8n's settings, and the mock setup refuses HTTP Request
and Code, as the class file turns both off.

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
from dataclasses import asdict, dataclass, field
from typing import Annotated, Literal, cast

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, JsonValue, ValidationError

from platform_api.auth import ConfigError
from platform_api.body_guard import RefuseDeepJson, refuse_invalid_request
from platform_api.nul_guard import RefuseNul
from platform_api.orchestration import n8n_calls_http
from platform_api.orchestration.dispatch import N8nWaker
from platform_api.orchestration.mock_setup import MockSetups, Mode, SetupRefused, mock_keys
from platform_api.orchestration.n8n import N8nApi, N8nError
from platform_api.orchestration.recorded_samples import (
    ALLOW_LISTS,
    SAMPLE_ITEMS,
    AnswerKind,
    RecordedSamples,
    Variation,
)
from platform_api.orchestration.scenario_grades import Ending, Graded, Verdict
from platform_api.orchestration.scenarios import (
    NotTried,
    Role,
    SampleId,
    ScenarioKind,
    ScenarioSpec,
    Serve,
    SimulationPlan,
    kinds_that_apply,
    plays_of,
)
from platform_api.orchestration.simulated_calls import (
    MockGitHub,
    Scenario,
    SimulatedCalls,
    SimulatedRun,
    Unsealed,
)
from platform_api.orchestration.simulations import Simulation, SimulationRefused, Simulations
from platform_api.settings import MAX_BODY_BYTES_DEFAULT, SHORTEST_START_SECRET, N8nOwner
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
    """MOCK_GITHUB_URL: mock GitHub, for a Read the scenario serves from the mock, and for n8n's
    own GitHub block in a copy."""
    mock_jira_url: str | None = None
    """MOCK_JIRA_URL: a mock Jira for n8n's own Jira block in a copy. None runs here yet, so such
    a block is pinned."""
    mock_slack_token: str | None = field(default=None, repr=False)
    """MOCK_SLACK_TOKEN: the key mock Slack takes, which its stack makes up at each start. Set only
    where mock Slack answers as slack.com, so n8n's own Slack block in a copy posts to it."""


def gateway_settings_from_env(env: Mapping[str, str]) -> GatewaySettings:
    """Only these settings are read. Anything else the environment holds is left alone."""

    def required(name: str, shortest: int = 1) -> str:
        value = env.get(name, "").strip()
        if not value:
            raise ConfigError(f"{name} is not set.")
        if len(value) < shortest:
            raise ConfigError(f"{name} needs at least {shortest} characters.")
        return value

    return GatewaySettings(
        node_key=required("WAB_NODE_KEY"),
        start_secret=required("WAB_START_SECRET", SHORTEST_START_SECRET),
        n8n_base_url=required("N8N_BASE_URL").rstrip("/"),
        n8n_owner=N8nOwner(required("N8N_OWNER_EMAIL"), required("N8N_OWNER_PASSWORD")),
        mock_github_url=env.get("MOCK_GITHUB_URL", "").strip().rstrip("/") or None,
        mock_jira_url=env.get("MOCK_JIRA_URL", "").strip().rstrip("/") or None,
        mock_slack_token=env.get("MOCK_SLACK_TOKEN", "").strip() or None,
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


def current_setups(request: Request) -> MockSetups:
    setups: MockSetups = request.app.state.setups
    return setups


CurrentSetups = Annotated[MockSetups, Depends(current_setups)]


def current_simulations(request: Request) -> Simulations:
    simulations: Simulations = request.app.state.simulations
    return simulations


CurrentSimulations = Annotated[Simulations, Depends(current_simulations)]
BlockName = Annotated[str, Field(min_length=1, max_length=200)]


class VersionIn(WireIn):
    """A workflow version as n8n's public API holds one, with its pinned output if it has any."""

    name: str = Field(min_length=1, max_length=200)
    nodes: list[dict[str, JsonValue]] = Field(min_length=1, max_length=200)
    connections: dict[str, JsonValue]
    settings: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    pin_data: dict[str, JsonValue] | None = Field(default=None, alias="pinData")


class CopyIn(WireIn):
    version: VersionIn
    pins: dict[BlockName, list[dict[str, JsonValue]]] = Field(
        default_factory=dict[str, list[dict[str, JsonValue]]],
        max_length=100,
        description="A scenario's own output for blocks with no mock, by block name (PR 5).",
    )


class BlockModeOut(WireModel):
    block: str
    node_type: str
    mode: Mode = Field(
        description="ours: the gateway answers it. runs: it runs as it is. mock: it runs against "
        "a mock with a mock key. pinned: its output is pinned, so its failures are not tried."
    )
    mock: str | None = None
    why: str | None = Field(default=None, description="Why a pinned block has no mock.")


class CopyOut(WireModel):
    workflow_id: str = Field(description="The copy's id in the simulation n8n.")
    blocks: list[BlockModeOut]
    not_tried: list[str] = Field(description="The pinned blocks, whose failures are not tried.")


class RefusedBlockOut(WireModel):
    block: str
    node_type: str
    why: str


class CopyRefused(WireModel):
    detail: str
    blocks: list[RefusedBlockOut]


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


class SampleIn(WireIn):
    """A recorded sample, which the gateway scrubs by its allow list before any scenario serves
    it (recorded_samples.py)."""

    id: SampleId
    answer: AnswerKind
    block: BlockName | None = Field(default=None, description="The block it was recorded from.")
    items: list[dict[str, JsonValue]] = Field(max_length=SAMPLE_ITEMS)


class SimulationIn(WireIn):
    version: VersionIn
    scenarios: list[ScenarioSpec] | None = Field(
        default=None, max_length=20, description="None runs code's own templates."
    )
    samples: list[SampleIn] = Field(default_factory=list[SampleIn], max_length=20)
    fall_back: bool = Field(
        default=False,
        description="When a scenario doesn't fit, run code's templates in place of the scenarios "
        "and say why, rather than refuse. The scenario writer's scenarios are sent so.",
    )


class PlanIn(WireIn):
    version: VersionIn
    samples: list[SampleIn] = Field(default_factory=list[SampleIn], max_length=20)


class PlanBlockOut(WireModel):
    name: str
    node_type: str
    role: Role
    mode: Mode
    mock: str | None
    answer: AnswerKind | None = Field(description="For a read, what it gives, when covered.")
    plays: list[Serve] = Field(description="How a simulation can play the block.")
    varies: list[Variation] = Field(description="The variations its answer takes.")


class SampleOut(WireModel):
    id: str
    answer: AnswerKind
    block: str | None
    items: list[dict[str, JsonValue]] = Field(description="As its allow list keeps them.")


class PlanOut(WireModel):
    blocks: list[PlanBlockOut]
    kinds: list[ScenarioKind] = Field(description="The kinds that apply, as code picks them.")
    samples: list[SampleOut] = Field(
        description="The samples of what the version reads, recorded ones newest first, then the "
        "made-up ones."
    )


class NotTriedOut(WireModel):
    block: str
    why: str


class PlayOut(WireModel):
    block: str
    serve: Serve
    vary: list[Variation] = Field(default_factory=list[Variation])


class ResultOut(WireModel):
    name: str
    kind: ScenarioKind
    verdict: Verdict
    expected: str = Field(description="What code expects of this kind, in plain words.")
    happened: str = Field(description="What code read in the records, in plain words.")
    ran: list[str] = Field(description="The blocks that ran, pinned ones left out.")
    not_tried: list[NotTriedOut]
    ending: Ending | None = Field(description="How code read the run's end. None when not run.")
    stopped_at: str | None = Field(description="The block that stopped the run, when one did.")
    plays: list[PlayOut] = Field(
        description="How the scenario played each block other than as recorded."
    )
    reached: list[str] = Field(
        default_factory=list[str],
        description="What the run reached, from the gateway's record and n8n's: the source, card, "
        "change or place to tell each of our blocks asked for, each mock a block of n8n's ran "
        "against, and any address n8n could not reach, such as read:github_releases, mock:github "
        "or host:example.com.",
    )


class CoverageOut(WireModel):
    not_reached: list[str] = Field(description="Blocks that could run, but no scenario reached.")
    not_tried: list[NotTriedOut] = Field(description="Pinned blocks, and blocks after a write.")
    kinds_without_a_scenario: list[ScenarioKind]


class SimulationOut(WireModel):
    tried: int
    passed: int
    results: list[ResultOut]
    coverage: CoverageOut
    blocks: list[BlockModeOut]
    scenarios_from: Literal["given", "templates"]
    refused: list[str] = Field(
        description="Why the scenarios given didn't fit, when code's templates ran in their place."
    )
    named: list[str] = Field(
        default_factory=list[str],
        description="What the version names in plain values, in the words `reached` uses. An "
        "expression names nothing, and a pinned block never runs.",
    )


class SimulationRefusedOut(WireModel):
    detail: str
    problems: list[str]


class Health(WireModel):
    status: Literal["ok"] = "ok"


REFUSED = {401: error_response("Not signed with the simulation's start secret")}

control = APIRouter(prefix="/simulation/v1", tags=["simulation"])


def _problems(error: ValidationError) -> JSONResponse:
    """A refusal that names each field and never echoes what was sent."""
    problems = [{"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]
    return JSONResponse(status_code=422, content={"detail": problems})


@control.post(
    "/simulations",
    response_model=SimulationOut,
    description="Runs a workflow version through its scenarios, or code's templates, each on a "
    "copy of its own in the simulation n8n, grades each from the records and deletes each copy.",
    responses={
        **REFUSED,
        422: {"model": SimulationRefusedOut, "description": "A scenario doesn't fit the version"},
        503: error_response("The simulation n8n or a mock did not answer"),
    },
)
async def simulate(
    body: SignedBody, simulations: CurrentSimulations
) -> SimulationOut | JSONResponse:
    try:
        given = SimulationIn.model_validate_json(body)
    except ValidationError as error:
        return _problems(error)
    samples = _samples(given.samples)
    version = given.version.model_dump(by_alias=True, exclude_none=True)
    try:
        done = await simulations.simulate(
            version, given.scenarios, samples, fall_back=given.fall_back
        )
    except N8nError, httpx.HTTPError:
        log.warning("a simulation stopped: the simulation n8n or a mock did not answer")
        detail = "The simulation n8n or a mock did not answer, so nothing was graded."
        return JSONResponse(status_code=503, content={"detail": detail})
    match done:
        case SetupRefused(blocks=blocks):
            refused = CopyRefused(
                detail="The simulation can't run every block of this version.",
                blocks=[RefusedBlockOut(**asdict(block)) for block in blocks],
            )
            return JSONResponse(status_code=422, content=refused.model_dump())
        case SimulationRefused(problems=problems, detail=detail):
            out = SimulationRefusedOut(detail=detail, problems=list(problems))
            return JSONResponse(status_code=422, content=out.model_dump())
        case Simulation():
            return _simulation_out(done)


def _samples(given: Sequence[SampleIn]) -> RecordedSamples:
    """The samples sent, each scrubbed by its allow list as the store keeps it."""
    samples = RecordedSamples()
    for sample in given:
        samples.record(
            sample.answer, sample.items, "real_run", block=sample.block, sample_id=sample.id
        )
    return samples


def _not_tried(found: Sequence[NotTried]) -> list[NotTriedOut]:
    return [NotTriedOut(block=n.block, why=n.why) for n in found]


def _result_out(r: Graded) -> ResultOut:
    return ResultOut(
        name=r.name,
        kind=r.kind,
        verdict=r.verdict,
        expected=r.expected,
        happened=r.happened,
        ran=list(r.ran),
        not_tried=_not_tried(r.not_tried),
        ending=r.ending,
        stopped_at=r.stopped_at,
        plays=[PlayOut(block=p.block, serve=p.serve, vary=list(p.vary)) for p in r.plays],
        reached=list(r.reached),
    )


def _simulation_out(done: Simulation) -> SimulationOut:
    return SimulationOut(
        tried=done.tried,
        passed=done.passed,
        results=[_result_out(r) for r in done.results],
        coverage=CoverageOut(
            not_reached=list(done.coverage.not_reached),
            not_tried=_not_tried(done.coverage.not_tried),
            kinds_without_a_scenario=list(done.coverage.kinds_without_a_scenario),
        ),
        blocks=[BlockModeOut(**asdict(block)) for block in done.blocks],
        scenarios_from=done.scenarios_from,
        refused=list(done.refused),
        named=list(done.named),
    )


def plan_out(plan: SimulationPlan, samples: RecordedSamples) -> PlanOut:
    """The version as a simulation sees it, for the scenario writer: code's facts only."""
    answers: set[AnswerKind] = {b.answer for b in plan.reads if b.answer is not None}
    return PlanOut(
        blocks=[
            PlanBlockOut(
                name=b.name,
                node_type=b.node_type,
                role=b.role,
                mode=b.mode,
                mock=b.mock,
                answer=b.answer,
                plays=list(plays_of(b)),
                varies=[] if b.answer is None else list(ALLOW_LISTS[b.answer].varies),
            )
            for b in plan.blocks
        ],
        kinds=list(kinds_that_apply(plan)),
        samples=[
            SampleOut(
                id=s.id,
                answer=s.answer,
                block=s.block,
                items=[cast(dict[str, JsonValue], dict(item)) for item in s.items],
            )
            for s in samples.listed(answers)
        ],
    )


@control.post(
    "/plans",
    response_model=PlanOut,
    description="A workflow version as a simulation sees it, for the scenario writer: each block's "
    "role and plays, the kinds that apply and the samples, scrubbed. It makes nothing.",
    responses={
        **REFUSED,
        422: {"model": CopyRefused, "description": "A block is not on, or there is no start"},
    },
)
async def plan(body: SignedBody, simulations: CurrentSimulations) -> PlanOut | JSONResponse:
    try:
        given = PlanIn.model_validate_json(body)
    except ValidationError as error:
        return _problems(error)
    version = given.version.model_dump(by_alias=True, exclude_none=True)
    match simulations.plan(version):
        case SetupRefused(blocks=blocks):
            refused = CopyRefused(
                detail="The simulation can't run every block of this version.",
                blocks=[RefusedBlockOut(**asdict(block)) for block in blocks],
            )
            return JSONResponse(status_code=422, content=refused.model_dump())
        case SimulationRefused(problems=problems):
            out = SimulationRefusedOut(detail=problems[0], problems=list(problems))
            return JSONResponse(status_code=422, content=out.model_dump())
        case found:
            return plan_out(found, _samples(given.samples))


@control.post(
    "/copies",
    status_code=201,
    response_model=CopyOut,
    description="Makes a workflow version's copy in the simulation n8n, with only mock keys, and "
    "pinned output for each block with no mock. A block the class file does not turn on is "
    "refused, and nothing is made.",
    responses={**REFUSED, 422: {"model": CopyRefused, "description": "A block is not on"}},
)
async def copy(body: SignedBody, setups: CurrentSetups) -> CopyOut | JSONResponse:
    try:
        given = CopyIn.model_validate_json(body)
    except ValidationError as error:
        return _problems(error)
    version = given.version.model_dump(by_alias=True, exclude_none=True)
    copied = await setups.copy(version, given.pins)
    if isinstance(copied, SetupRefused):
        refused = CopyRefused(
            detail="The simulation can't run every block of this version.",
            blocks=[RefusedBlockOut(**asdict(block)) for block in copied.blocks],
        )
        return JSONResponse(status_code=422, content=refused.model_dump())
    return CopyOut(
        workflow_id=copied.workflow_id,
        blocks=[BlockModeOut(**asdict(block)) for block in copied.blocks],
        not_tried=list(copied.not_tried),
    )


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
        return _problems(error)
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
    setups: MockSetups,
    simulations: Simulations,
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
    app.state.setups = setups
    app.state.simulations = simulations
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
    # The copies go to the simulation n8n alone, through its own owner's API key.
    keys = mock_keys(settings.mock_github_url, settings.mock_jira_url, settings.mock_slack_token)
    setups = MockSetups(n8n, keys)
    simulations = Simulations(setups, calls, n8n, github)
    closers = [n8n.close, waker.close, *([] if github is None else [github.close])]
    log.info("the simulation gateway answers the simulation n8n at %s", settings.n8n_base_url)
    return gateway_app(settings, calls, setups, simulations, closers)


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
