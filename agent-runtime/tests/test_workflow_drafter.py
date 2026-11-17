"""The workflow drafter's turns with the model, and its route (ADR 0051). A scripted model plays
the drafter, so every test runs without a real model. CI mounts contracts/ into the test image,
where it is /contracts."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import SecretStr

from agent_runtime.api import Runtime, Settings, create_app
from agent_runtime.catalogue import Catalogue, load
from agent_runtime.contract import (
    COULDNT_DRAFT,
    KEY_PASTED,
    DrafterFacts,
    KeyPasted,
    LibraryCard,
    ModelAccess,
    ModelProblem,
    PlanBlock,
    WorkflowDrafted,
    WorkflowDraftRequest,
    WorkflowNotDrafted,
    WorkflowPlan,
    workflow_draft_result_adapter,
)
from agent_runtime.planner import FixedPlanner
from agent_runtime.summary import ChatFor, TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from agent_runtime.workflow_drafter import (
    BRIEFING,
    DEFAULT_DRAFTER_MODEL,
    MOST_TURNS,
    _bound,  # pyright: ignore[reportPrivateUsage]
    _system,  # pyright: ignore[reportPrivateUsage]
    draft_workflow,
    drafting,
)
from tests.fakes import FakeClock, FakeSource, ScriptedChat, asks, call, langgraph_tags
from tests.test_api import BASE_ENV, KEY

CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "n8n" / "catalogue.json"
WORDS = "Every Monday at 9am, check langchain-ai/langgraph for new releases and tell the team."
FACTS = DrafterFacts(jira_projects=["MOCK"], repositories=["langchain-ai/langgraph"])
ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm.example", model="claude-haiku-5-5", api_key="unused"
)

type Json = dict[str, Any]


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load(CATALOGUE)


def request(words: str = WORDS) -> WorkflowDraftRequest:
    return WorkflowDraftRequest(words=words, facts=FACTS, model=ACCESS)


def block(name: str, node_type: str, **parameters: object) -> Json:
    return {"name": name, "type": node_type, "version": 1, "parameters": json.dumps(parameters)}


GOOD: Json = {
    "name": "LangGraph release news",
    "blocks": [
        {
            "name": "Every Monday",
            "type": "n8n-nodes-base.scheduleTrigger",
            "version": 1.4,
            "parameters": '{"rule": "<<run_time>>"}',
        },
        block("Read releases", "CUSTOM.wabRead", source="github_releases", place="<<repo>>"),
        block("Tell the team", "CUSTOM.wabTell", where="channel", what="result"),
    ],
    "wires": [
        {"from_block": "Every Monday", "exit": "main", "to_block": "Read releases"},
        {"from_block": "Read releases", "exit": "main", "to_block": "Tell the team"},
    ],
    "settings": [
        {"id": "run_time", "kind": "run_time", "label": "When it runs", "value": None},
        {"id": "repo", "kind": "repository", "label": "The repository", "value": None},
    ],
}
INVENTED: Json = GOOD | {
    "blocks": [*GOOD["blocks"][:2], block("Tell the team", "CUSTOM.wabTell", channel="ops")]
}


def submit(plan: Json, number: int) -> AIMessage:
    return asks(call("submit_plan", plan, f"call_{number}"))


def scripted(*steps: AIMessage | Exception) -> ScriptedChat:
    return ScriptedChat(script=list(steps))


def test_it_finds_describes_and_submits_a_plan_that_passes(catalogue: Catalogue):
    chat = scripted(
        asks(call("find_blocks", {"words": "read jira issues"}, "call_1")),
        asks(
            call(
                "describe_block",
                {"type": "CUSTOM.wabRead", "version": None, "resource": None, "operation": None},
                "call_2",
            )
        ),
        submit(GOOD, 3),
    )

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, WorkflowDrafted)
    assert (result.turns, result.sent_back, result.catalogue) == (3, [], catalogue.image)
    assert [b.name for b in result.plan.blocks] == [
        "Every Monday",
        "Read releases",
        "Tell the team",
    ]
    assert {s.id: s.mark for s in result.plan.settings} == {"run_time": "filled", "repo": "filled"}
    assert chat.offered == [["find_blocks", "describe_block", "submit_plan"]]
    assert chat.bound_with == [{"strict": True}]
    first, *_ = chat.calls
    assert first[0] == SystemMessage(content=BRIEFING)
    assert "langchain-ai/langgraph" in str(first[1].content)
    found = chat.calls[1][-1]
    assert isinstance(found, ToolMessage) and found.status == "success"
    assert "CUSTOM.wabRead" in [b["type"] for b in json.loads(str(found.content))]


def test_the_fixed_part_comes_first_and_the_person_s_part_after_it(catalogue: Catalogue):
    chat = scripted(submit(GOOD, 1))

    draft_workflow(request("one thing"), lambda _: chat, catalogue)
    draft_workflow(request("another thing"), lambda _: chat, catalogue)

    one, two = chat.calls
    assert one[0] == two[0]
    assert isinstance(one[1], HumanMessage) and one[1] != two[1]
    assert str(one[1].content).index("facts") < str(one[1].content).index("one thing")


def test_a_failing_plan_goes_back_with_its_reasons_then_the_fixed_one_passes(catalogue: Catalogue):
    chat = scripted(submit(INVENTED, 1), submit(GOOD, 2))

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, WorkflowDrafted)
    assert [[p.code for p in s.problems] for s in result.sent_back] == [["no_parameter"]]
    told = chat.calls[1][-1]
    assert isinstance(told, ToolMessage) and told.status == "error"
    assert "there is no parameter 'channel'" in str(told.content)
    assert "Fix each problem and submit the whole plan again" in str(told.content)


def test_after_three_times_back_the_answer_is_i_couldn_t_draft_that(catalogue: Catalogue):
    chat = scripted(*(submit(INVENTED, n) for n in range(1, 5)), submit(GOOD, 5))

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, WorkflowNotDrafted)
    assert (result.why, result.message, result.turns) == ("gave_up", COULDNT_DRAFT, 4)
    assert len(result.sent_back) == 4
    assert len(chat.script) == 1  # The fifth plan was never asked for.


def test_a_turn_with_no_tool_call_ends_the_draft(catalogue: Catalogue):
    chat = scripted(AIMessage(content="Here is my plan: a schedule, then Slack."))

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, WorkflowNotDrafted)
    assert (result.why, result.turns) == ("no_tool_call", 1)


def test_it_stops_when_it_runs_out_of_turns(catalogue: Catalogue):
    looking = [asks(call("find_blocks", {"words": "slack"}, f"c{n}")) for n in range(MOST_TURNS)]
    chat = scripted(*looking)

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, WorkflowNotDrafted)
    assert (result.why, result.turns) == ("too_long", MOST_TURNS)


def test_it_stops_when_it_runs_out_of_time(catalogue: Catalogue):
    chat = scripted(asks(call("find_blocks", {"words": "slack"}, "c1")), submit(GOOD, 2))
    ticks = iter([0.0, 0.0, 500.0])

    result = draft_workflow(request(), lambda _: chat, catalogue, clock=lambda: next(ticks))

    assert isinstance(result, WorkflowNotDrafted) and result.why == "too_long"


@pytest.mark.parametrize(
    "words",
    [
        "Use my key sk-ant-example-not-a-key to read Jira every day at 9:00.",
        "Call the API with Bearer abc123def456 every Monday.",
    ],
)
def test_words_with_the_shape_of_a_key_never_reach_a_model(catalogue: Catalogue, words: str):
    result, draft = drafting(request(words), no_model, catalogue)

    assert isinstance(result, KeyPasted)
    assert result.message == KEY_PASTED
    assert draft.turns == 0


def no_model(_timeout: float) -> ScriptedChat:
    raise AssertionError("a model was built")


def with_key_in_the_current_plan() -> WorkflowDraftRequest:
    keyed = {"name": "Note", "type": "n8n-nodes-base.set", "version": 3.4}
    current = WorkflowPlan(
        name="A plan",
        blocks=[PlanBlock(**keyed, parameters={"note": "token sk-ant-example-not-a-key"})],
        wires=[],
        settings=[],
    )
    return WorkflowDraftRequest(words="change the note", facts=FACTS, model=ACCESS, current=current)


def with_key_in_the_facts() -> WorkflowDraftRequest:
    card = LibraryCard(
        card_id="crd_keyed", name="Keyed", purpose="Calls with ghp_ABCDEFGHIJKLMNOPQRSTUV"
    )
    facts = FACTS.model_copy(update={"agent_cards": [card]})
    return WorkflowDraftRequest(words="use the keyed agent", facts=facts, model=ACCESS)


@pytest.mark.parametrize("keyed", [with_key_in_the_current_plan, with_key_in_the_facts])
def test_a_key_anywhere_the_drafter_would_read_never_reaches_a_model(
    catalogue: Catalogue, keyed: Any
):
    result, draft = drafting(keyed(), no_model, catalogue)

    assert isinstance(result, KeyPasted)
    assert draft.turns == 0


class BrokenCatalogue(Catalogue):
    def find_blocks(self, words: str, limit: int = 8) -> list[dict[str, Any]]:
        raise RuntimeError("internal detail that must not leak")


def test_an_error_inside_a_tool_is_an_honest_i_couldn_t_draft_that(catalogue: Catalogue):
    broken = BrokenCatalogue(json.loads(CATALOGUE.read_bytes()))
    chat = scripted(asks(call("find_blocks", {"words": "slack"}, "c1")), submit(GOOD, 2))

    result = draft_workflow(request(), lambda _: chat, broken)

    assert isinstance(result, WorkflowNotDrafted)
    assert (result.why, result.message) == ("failed", COULDNT_DRAFT)
    assert "internal detail" not in result.model_dump_json()


def test_the_route_answers_an_error_inside_a_tool_without_a_500(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Catalogue, "find_blocks", BrokenCatalogue.find_blocks)
    chat = scripted(asks(call("find_blocks", {"words": "slack"}, "c1")))
    client = app(chat, {"N8N_CATALOGUE": str(CATALOGUE)}, [])

    answer = client.post("/v1/workflows/draft", json=body())

    assert answer.status_code == 200
    assert answer.json()["status"] == "not_drafted"
    assert "internal detail" not in answer.text


def test_a_failed_model_call_is_a_model_problem(catalogue: Catalogue):
    timeout = type("ReadTimeout", (Exception,), {})
    chat = scripted(timeout())

    result = draft_workflow(request(), lambda _: chat, catalogue)

    assert isinstance(result, ModelProblem) and result.reason == "too_slow"


def test_a_block_that_can_t_be_used_is_never_described(catalogue: Catalogue):
    chat = scripted(
        asks(
            call(
                "describe_block",
                {
                    "type": "n8n-nodes-base.executeCommand",
                    "version": 1,
                    "resource": None,
                    "operation": None,
                },
                "c1",
            )
        ),
        asks(call("describe_block", {"type": "nope", "version": None}, "c2")),
        submit(GOOD, 3),
    )

    draft_workflow(request(), lambda _: chat, catalogue)

    refused = chat.calls[1][-1]
    assert isinstance(refused, ToolMessage) and refused.status == "error"
    assert "Execute Command never loads" in str(refused.content)
    bad_args = chat.calls[2][-1]
    assert "the arguments don't fit describe_block" in str(bad_args.content)


def test_an_edit_sends_the_current_plan_as_data(catalogue: Catalogue):
    first = draft_workflow(request(), lambda _: scripted(submit(GOOD, 1)), catalogue)
    assert isinstance(first, WorkflowDrafted)
    chat = scripted(submit(GOOD, 1))
    edit = WorkflowDraftRequest(
        words="post at 17:00 instead", facts=FACTS, model=ACCESS, current=first.plan
    )

    result = draft_workflow(edit, lambda _: chat, catalogue)

    assert "The current plan, as data" in str(chat.calls[0][1].content)
    assert isinstance(result, WorkflowDrafted)
    run_time = next(s for s in result.plan.settings if s.id == "run_time")
    assert (run_time.value, run_time.mark) == ("monday 17:00", "filled")


def test_anthropic_gets_strict_tools_and_the_prompt_cache():
    model = ChatAnthropic(
        model_name="claude-sonnet-5-5", api_key=SecretStr("unused"), stop=None, timeout=60.0
    )
    bound = _bound(model)
    kwargs: dict[str, Any] = bound.kwargs  # type: ignore[attr-defined]

    payload = model._get_request_payload(  # pyright: ignore[reportPrivateUsage]
        [_system(model), HumanMessage("words")], **kwargs
    )

    assert [t["name"] for t in payload["tools"]] == ["find_blocks", "describe_block", "submit_plan"]
    assert all(t["strict"] is True for t in payload["tools"])
    plan = payload["tools"][2]["input_schema"]
    assert plan["additionalProperties"] is False
    assert set(plan["required"]) == {"name", "blocks", "wires", "settings"}
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in payload


# The route.


def app(chat: ScriptedChat, env: dict[str, str], asked: list[ModelAccess]) -> TestClient:
    clock = FakeClock()

    def chat_source(access: ModelAccess | None) -> ChatFor | None:
        if access is None:
            return None
        asked.append(access)
        return lambda _timeout: chat

    runtime = Runtime(
        checker=VersionChecker(
            FakeSource(langgraph_tags()), TemplateSummarizer(), sleep=clock.sleep
        ),
        planner=FixedPlanner(),
        clock=clock,
        callbacks=None,  # type: ignore[arg-type]
        chat_source=chat_source,
    )
    return TestClient(
        create_app(Settings.from_env({**BASE_ENV, **env}), runtime), headers={"X-Agent-Key": KEY}
    )


def body(words: str = WORDS) -> Json:
    return json.loads(request(words).model_dump_json())


def test_the_route_drafts_on_the_drafter_s_model_through_the_planner_s_connection():
    asked: list[ModelAccess] = []
    client = app(scripted(submit(GOOD, 1)), {"N8N_CATALOGUE": str(CATALOGUE)}, asked)

    answer = client.post("/v1/workflows/draft", json=body())

    assert answer.status_code == 200
    result = workflow_draft_result_adapter.validate_python(answer.json())
    assert isinstance(result, WorkflowDrafted)
    assert [a.model for a in asked] == [DEFAULT_DRAFTER_MODEL]
    assert asked[0].base_url == ACCESS.base_url


def test_drafter_model_names_another_model():
    asked: list[ModelAccess] = []
    env = {"N8N_CATALOGUE": str(CATALOGUE), "DRAFTER_MODEL": "claude-opus-5-5"}
    client = app(scripted(submit(GOOD, 1)), env, asked)

    client.post("/v1/workflows/draft", json=body())

    assert [a.model for a in asked] == ["claude-opus-5-5"]


def test_the_route_needs_the_agent_key():
    client = app(scripted(), {"N8N_CATALOGUE": str(CATALOGUE)}, [])

    assert (
        client.post("/v1/workflows/draft", json=body(), headers={"X-Agent-Key": "no"}).status_code
        == 401
    )


def test_the_route_fails_clearly_when_the_catalogue_is_missing(tmp_path: Path):
    client = app(scripted(), {"N8N_CATALOGUE": str(tmp_path / "catalogue.json")}, [])

    answer = client.post("/v1/workflows/draft", json=body())

    assert answer.status_code == 503
    assert "The n8n block catalogue is missing at" in answer.json()["detail"]


@pytest.mark.parametrize(
    "image", ["n8nio/n8n:2.42.6", "n8nio/n8n:2.42.6@sha256:not-a-digest", None]
)
def test_the_route_fails_clearly_when_the_catalogue_s_digest_is_unknown(
    tmp_path: Path, image: str | None
):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"image": image, "blocks": {}}))
    client = app(scripted(), {"N8N_CATALOGUE": str(path)}, [])

    answer = client.post("/v1/workflows/draft", json=body())

    assert answer.status_code == 503
    assert "by its digest" in answer.json()["detail"]


def test_the_image_s_path_is_the_default():
    assert Settings.from_env(BASE_ENV).n8n_catalogue == Path("/app/contracts/n8n/catalogue.json")
