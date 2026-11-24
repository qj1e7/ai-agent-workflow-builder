import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from agent_runtime.api import Settings, create_app
from agent_runtime.contract import (
    AgentCards,
    AgentEventPost,
    AnswerRequest,
    CapabilityList,
    CauseRequest,
    CheckPartRequest,
    ChooseRequest,
    ChooseResult,
    ConnectRequest,
    ConnectResult,
    DraftRequest,
    DraftResult,
    ExplainReworded,
    ExplainWordingRequest,
    FindSoftwareRequest,
    FindSoftwareResult,
    GitHubCheckResult,
    KeyShapes,
    ModelAccess,
    ModelTestResult,
    ReadReleasesRequest,
    ReadReleasesResult,
    ScenarioExplainRequest,
    ScenarioWriteRequest,
    TaskRequest,
    ToolList,
    answer_result_adapter,
    cause_result_adapter,
    check_part_result_adapter,
    explain_wording_result_adapter,
    scenario_explain_result_adapter,
    scenario_write_result_adapter,
    task_result_adapter,
)
from agent_runtime.contracts import answer_request
from agent_runtime.explain_wording import explain_guard, fact_check
from agent_runtime.fixing.starter import FixAccepted, FixStart
from agent_runtime.monitoring.masking import KEY_SHAPE_SOURCES, KEY_SHAPES

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "agent"
WORDINGS = sorted((FIXTURES.parent / "builder").glob("explain-wording.*.json"))
"""The wording requests platform-api builds from its golden n8n documents."""

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="contracts/ is not in the test image. CI runs this on the host."
)

PARSERS: dict[str, TypeAdapter[Any]] = {
    "task-request.json": TypeAdapter(TaskRequest),
    "task-finished.json": task_result_adapter,
    "task-failed.json": task_result_adapter,
    "watchlist-task-request.json": TypeAdapter(TaskRequest),
    "watchlist-task-finished.json": task_result_adapter,
    "callback-event.json": TypeAdapter(AgentEventPost),
    "agent-cards.json": TypeAdapter(AgentCards),
    "model-connect-request.json": TypeAdapter(ConnectRequest),
    "model-connected.json": TypeAdapter(ConnectResult),
    "model-test-request.json": TypeAdapter(ModelAccess),
    "model-test-passed.json": TypeAdapter(ModelTestResult),
    "model-problem.json": TypeAdapter(ModelTestResult),
    "github-check-working.json": TypeAdapter(GitHubCheckResult),
    "github-check-expiring.json": TypeAdapter(GitHubCheckResult),
    "github-check-refused.json": TypeAdapter(GitHubCheckResult),
    "tools.json": TypeAdapter(ToolList),
    "capabilities.json": TypeAdapter(CapabilityList),
    "card-task-request.json": TypeAdapter(TaskRequest),
    "card-task-finished.json": task_result_adapter,
    "card-draft-request.json": TypeAdapter(DraftRequest),
    "card-drafted.json": TypeAdapter(DraftResult),
    "planner-choose-request.json": TypeAdapter(ChooseRequest),
    "planner-chosen.json": TypeAdapter(ChooseResult),
    "software-find-request.json": TypeAdapter(FindSoftwareRequest),
    "software-found.json": TypeAdapter(FindSoftwareResult),
    "releases-read-request.json": TypeAdapter(ReadReleasesRequest),
    "releases-read.json": TypeAdapter(ReadReleasesResult),
    "planner-answer-request.json": TypeAdapter(AnswerRequest),
    "planner-answered-card.json": answer_result_adapter,
    "planner-answered-card-24-hour.json": answer_result_adapter,
    "planner-answered-cant.json": answer_result_adapter,
    "planner-answered-watchlist.json": answer_result_adapter,
    "planner-answered-refused.json": answer_result_adapter,
    "planner-answered-edit.json": answer_result_adapter,
    "planner-answered-pause.json": answer_result_adapter,
    "planner-answered-remove.json": answer_result_adapter,
    "planner-answered-explain.json": answer_result_adapter,
    "planner-question-request.json": TypeAdapter(AnswerRequest),
    "planner-answered-question.json": answer_result_adapter,
    "planner-answered-reply.json": answer_result_adapter,
    "planner-answered-reply-clarify.json": answer_result_adapter,
    "planner-answered-reply-cant.json": answer_result_adapter,
    "planner-answered-reply-about.json": answer_result_adapter,
    "planner-answered-didnt-follow.json": answer_result_adapter,
    "explain-wording-request.json": TypeAdapter(ExplainWordingRequest),
    "explain-wording-reworded.json": explain_wording_result_adapter,
    "explain-wording-kept.json": explain_wording_result_adapter,
    "troubleshooter-cause-request.json": TypeAdapter(CauseRequest),
    "troubleshooter-cause-found.json": cause_result_adapter,
    "troubleshooter-cause-kept.json": cause_result_adapter,
    "scenario-write-request.json": TypeAdapter(ScenarioWriteRequest),
    "scenario-write-written.json": scenario_write_result_adapter,
    "scenario-write-kept.json": scenario_write_result_adapter,
    "scenario-explain-request.json": TypeAdapter(ScenarioExplainRequest),
    "scenario-explain-explained.json": scenario_explain_result_adapter,
    "planner-check-part-request.json": TypeAdapter(CheckPartRequest),
    "planner-check-part-cant.json": check_part_result_adapter,
    "planner-check-part-fits.json": check_part_result_adapter,
    "key-shapes.json": TypeAdapter(KeyShapes),
    "fix-start-request.json": TypeAdapter(FixStart),
    "fix-accepted.json": TypeAdapter(FixAccepted),
}


def load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_fixture_parses(name: str):
    PARSERS[name].validate_python(load(name))


def test_the_key_shapes_platform_api_holds_to_are_the_masker_s_own():
    """platform-api refuses every shape in this file before it keeps anything (ADR 0051)."""
    shapes = KeyShapes.model_validate(load("key-shapes.json")).shapes
    assert shapes == list(KEY_SHAPE_SOURCES)
    assert KEY_SHAPES.pattern == "|".join(KEY_SHAPE_SOURCES)


def test_every_fixture_file_has_a_parser():
    assert {p.name for p in FIXTURES.glob("*.json")} == set(PARSERS)


def test_callback_token_travels_in_a_header_not_the_url():
    request = TaskRequest.model_validate(load("task-request.json"))
    assert request.callback.token not in request.callback.url
    assert "token" not in request.callback.url and "sig" not in request.callback.url


def client_get(path: str) -> object:
    client = TestClient(
        create_app(
            Settings.from_env(
                {
                    "AGENT_API_KEY": "test-agent-key-not-a-secret",
                    "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000",
                }
            )
        ),
        headers={"X-Agent-Key": "test-agent-key-not-a-secret"},
    )
    return client.get(path).json()


def test_app_serves_the_cards_and_health():
    client = TestClient(
        create_app(
            Settings.from_env(
                {
                    "AGENT_API_KEY": "test-agent-key-not-a-secret",
                    "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000",
                }
            )
        )
    )
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/v1/agents").json() == load("agent-cards.json")


def test_the_tool_fixture_is_the_runtimes_tool_list():
    assert client_get("/v1/tools") == load("tools.json")


def test_the_capabilities_fixture_is_the_runtimes_registry():
    assert client_get("/v1/capabilities") == load("capabilities.json")


def test_the_card_task_request_runs_a_card_with_its_values():
    request = TaskRequest.model_validate(load("card-task-request.json"))
    assert request.inputs.kind == "cards"


def test_no_fixture_holds_a_model_key_that_looks_real():
    # key-shapes.json holds the shapes of keys as patterns, not a key.
    for path in FIXTURES.glob("*.json"):
        assert path.name == "key-shapes.json" or "sk-" not in path.read_text()


def test_the_reworded_fixture_passes_every_check_against_the_request_fixture():
    request = ExplainWordingRequest.model_validate(load("explain-wording-request.json"))
    reworded = ExplainReworded.model_validate(load("explain-wording-reworded.json"))
    assert fact_check(request.wording, request) is None
    assert explain_guard(reworded.text, request) is None


def test_platform_api_wrote_a_wording_for_each_golden_document():
    assert len(WORDINGS) >= 4


@pytest.mark.parametrize("path", WORDINGS, ids=lambda path: path.stem)
def test_codes_own_wording_in_each_platform_request_keeps_to_its_facts(path: Path):
    body = {**json.loads(path.read_text()), "model": answer_request().model.model_dump()}
    request = ExplainWordingRequest.model_validate(body)
    assert fact_check(request.wording, request) is None
