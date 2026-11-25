"""Starting a refinement of a drafted workflow's Check in the runtime (ADR 0054, section 7).
platform-api keeps the refinement and mints its token, then asks the runtime to run the
coordinator on the draft. The runtime runs each refinement once, sends its token only to an
allowed origin, and calls platform-api's routes for that drafted workflow's refinement, never a
stopped run's."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi.testclient import TestClient

from agent_runtime.api import create_app
from agent_runtime.catalogue import CatalogueUnusable
from agent_runtime.contract import CauseFound, DrafterFacts
from agent_runtime.contracts import draft_request
from agent_runtime.fixing.coordinator import HandedBack
from agent_runtime.fixing.drafter import REFINE_WORDS, WORDS, fix_ask, refine_ask
from agent_runtime.fixing.platform_parts import FIX_TOKEN_HEADER, PlatformParts
from agent_runtime.fixing.ports import FixDraftRequest, ScenarioResult
from agent_runtime.fixing.starter import FixStart, RefineStart, Starter, run_refinement
from tests.test_api import KEY, ORIGIN, SETTINGS, make_runtime
from tests.test_fix_platform import Platform, ok, plenty
from tests.test_fix_start import ENDS_BY, TOKEN, VERSION
from tests.test_fix_start import body as fix_body

FIX = "fix_01REFINE"
DRAFTED = "dw_01DRAFTED"
BASE = "http://platform-api:8000"


def body(platform_url: str = ORIGIN, fix_id: str = FIX) -> dict[str, Any]:
    return {
        "drafted_id": DRAFTED,
        "request": {
            "fix_id": fix_id,
            "asked_by": "alice",
            "ends_by": ENDS_BY.isoformat(),
            "version": VERSION.model_dump(mode="json"),
            "failed": [{"kind": "odd_data", "step": "Read new releases", "why": "stopped"}],
            "not_reached": [],
        },
        "facts": {"repositories": ["langchain-ai/langgraph"]},
        "model": json.loads(draft_request().model.model_dump_json()),
        "platform_url": platform_url,
        "token": TOKEN,
    }


class Ran:
    def __init__(self) -> None:
        self.fixes: list[FixStart] = []
        self.refinements: list[RefineStart] = []

    def starter(self) -> Starter:
        return Starter(self.fixes.append, spawn=lambda work: work(), refine=self.refinements.append)


def app_with(starter: Starter) -> TestClient:
    return TestClient(
        create_app(SETTINGS, make_runtime(), fixes=starter), headers={"X-Agent-Key": KEY}
    )


def test_a_refinement_runs_once_for_its_id_and_never_as_a_fix():
    ran = Ran()
    client = app_with(ran.starter())
    first = client.post("/v1/refinements", json=body())
    again = client.post("/v1/refinements", json=body())
    assert (first.status_code, first.json()) == (202, {"fix_id": FIX, "started": True})
    assert (again.status_code, again.json()) == (202, {"fix_id": FIX, "started": False})
    [started] = ran.refinements
    assert (started.drafted_id, started.token) == (DRAFTED, TOKEN)
    assert ran.fixes == []


def test_a_fix_and_a_refinement_never_share_an_id():
    ran = Ran()
    client = app_with(ran.starter())
    assert client.post("/v1/fixes", json=fix_body(fix_id=FIX)).json()["started"] is True
    assert client.post("/v1/refinements", json=body()).json()["started"] is False
    assert ran.refinements == []


def test_the_refinement_s_token_goes_only_to_an_allowed_origin():
    ran = Ran()
    answer = app_with(ran.starter()).post(
        "/v1/refinements", json=body(platform_url="https://elsewhere.example")
    )
    assert answer.status_code == 422
    assert ran.refinements == []


def test_only_platform_api_with_the_agent_key_starts_a_refinement():
    ran = Ran()
    client = app_with(ran.starter())
    client.headers.pop("X-Agent-Key")
    assert client.post("/v1/refinements", json=body()).status_code == 401
    assert ran.refinements == []


def test_a_refinement_that_names_no_failure_and_no_gap_starts_nothing():
    ran = Ran()
    empty = body()
    empty["request"]["failed"] = []
    assert app_with(ran.starter()).post("/v1/refinements", json=empty).status_code == 422
    assert ran.refinements == []


def test_each_call_goes_to_the_drafted_workflow_s_refinement_with_its_token():
    platform = Platform()
    platform.answer("checks", ok({"passes": True, "findings": []}))
    client = httpx.Client(transport=httpx.MockTransport(platform))
    parts = PlatformParts.of_a_draft(BASE, DRAFTED, FIX, TOKEN, client=client)
    assert parts.passes(VERSION, 30.0, plenty) is True
    [(_, _, request)] = platform.asked
    assert str(request.url) == f"{BASE}/internal/v1/drafted/{DRAFTED}/refinements/{FIX}/checks"
    assert request.headers[FIX_TOKEN_HEADER] == TOKEN


def test_a_round_zero_hand_in_is_stored_with_no_cause():
    platform = Platform()
    digest = "sha256:" + "a" * 64
    platform.answer("revisions", ok({"version": 3, "digest": digest}))
    client = httpx.Client(transport=httpx.MockTransport(platform))
    parts = PlatformParts.of_a_draft(BASE, DRAFTED, FIX, TOKEN, client=client)
    stored = parts.store(VERSION, None, 30.0)
    assert (stored.version, stored.digest) == (3, digest)
    [(_, sent, _)] = platform.asked
    assert sent["cause"] is None


def test_the_fix_drafter_refines_a_draft_with_the_failed_scenarios_and_no_cause():

    failed = ScenarioResult(name="odd_data", verdict="failed", step="Read new releases")
    cause = CauseFound(
        failed_part=["Read new releases"], system=None, failure_kind="unknown", detail=None
    )
    asked = FixDraftRequest(VERSION, cause, ("Read new releases",), (failed,), 1, of_a_draft=True)
    text = refine_ask(asked, DrafterFacts())
    assert "practice systems" in text and "odd_data" in text
    assert "Why the run stopped" not in text
    assert "Why the run stopped" in fix_ask(asked, DrafterFacts())
    assert REFINE_WORDS != WORDS


def test_a_catalogue_the_drafter_can_t_use_hands_the_refinement_back_at_once():

    platform = Platform()
    platform.answer("events", ok({"refused": None}))
    client = httpx.Client(transport=httpx.MockTransport(platform))

    def unusable():  # noqa: ANN202
        raise CatalogueUnusable("no catalogue")

    outcome = run_refinement(
        RefineStart.model_validate(body(platform_url=BASE)),
        lambda _model: None,
        "claude-sonnet-5-5",
        unusable,
        client=client,
        sleep=lambda _s: None,
        now=lambda: datetime(2026, 11, 25, 6, 0, tzinfo=UTC),
    )
    assert isinstance(outcome, HandedBack) and outcome.why == "gave_up"
    [(route, sent, request)] = platform.asked
    assert route == "events" and sent["kind"] == "fix_handed_back"
    assert f"/drafted/{DRAFTED}/refinements/{FIX}/" in str(request.url)
