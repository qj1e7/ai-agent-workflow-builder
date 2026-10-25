import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from agent_runtime.api import HttpCallbacks, Runtime, Settings, build_runtime, create_app
from agent_runtime.card_runner import CardRunner
from agent_runtime.contract import ModelAccess
from agent_runtime.contracts import (
    CARD_REPORT,
    CARD_TICKET_BODY,
    CARD_TICKET_TITLE,
    EXAMPLE_KEY,
    GATEWAY,
    card_request,
    choose_request,
    draft_request,
)
from agent_runtime.drafting import AgentAnswer, ChoiceAnswer
from agent_runtime.jira import PracticeJiraFor
from agent_runtime.release_checker import ReleaseChecker
from agent_runtime.room import FixedRoomLead
from agent_runtime.summary import ChatFor, TemplateSummarizer
from tests.fakes import FakeClock, FakeJira, FakeSource, ScriptedChat, langgraph_tags
from tests.test_api import BASE_ENV, KEY, ORIGIN, SETTINGS, Posts
from tests.test_card_runner import releases_then_search_then_create
from tests.test_drafting import answer as draft_answer


def make_app(chat: ScriptedChat | None, posts: Posts | None = None) -> TestClient:
    clock = FakeClock()
    callbacks = HttpCallbacks(transport=httpx.MockTransport(posts or Posts()))
    checker = ReleaseChecker(FakeSource(langgraph_tags()), TemplateSummarizer(), sleep=clock.sleep)
    runner = CardRunner(FakeSource(langgraph_tags()[:8]), lambda _: FakeJira(), sleep=clock.sleep)

    def chat_source(access: ModelAccess | None) -> ChatFor | None:
        if chat is None or access is None:
            return None
        model = chat
        return lambda timeout: model

    runtime = Runtime(
        checker=checker,
        lead=FixedRoomLead(),
        clock=clock,
        callbacks=callbacks,
        cards=runner,
        chat_source=chat_source,
    )
    return TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})


def card_body(with_model: bool = True) -> dict[str, Any]:
    body = json.loads(card_request("run_01JD1").model_dump_json())
    if with_model:
        body["model"] = {
            "style": "anthropic",
            "base_url": GATEWAY,
            "model": "claude-sonnet-5-5",
            "api_key": EXAMPLE_KEY,
        }
    return body


def test_the_tool_list_needs_the_key_and_is_the_four_tools():
    client = make_app(None)
    assert client.get("/v1/tools", headers={"X-Agent-Key": "wrong"}).status_code == 401
    tools = client.get("/v1/tools").json()["tools"]
    assert [t["id"] for t in tools] == [
        "github.read_releases",
        "jira.search",
        "jira.read_ticket",
        "jira.create_ticket",
    ]


def test_a_card_task_runs_and_returns_the_proposed_ticket():
    chat = ScriptedChat(script=releases_then_search_then_create())
    result = make_app(chat).post("/v1/tasks", json=card_body()).json()
    assert result["status"] == "finished"
    assert result["output"]["summary"] == CARD_REPORT
    [intent] = result["output"]["proposed"]
    assert intent["fields"] == {"title": CARD_TICKET_TITLE, "body": CARD_TICKET_BODY}
    assert intent["subject"] == "crd_release_checker"


def test_a_card_task_posts_every_event_to_the_callback():
    posts = Posts()
    chat = ScriptedChat(script=releases_then_search_then_create())
    result = make_app(chat, posts).post("/v1/tasks", json=card_body()).json()
    assert len(posts.requests) == len(result["events"])
    assert posts.requests[0].headers["x-callback-token"] == card_body()["callback"]["token"]


def test_a_card_task_without_any_model_says_connect_one_and_is_not_remembered():
    client = make_app(ScriptedChat(script=releases_then_search_then_create()))
    first = client.post("/v1/tasks", json=card_body(with_model=False)).json()
    assert first["status"] == "failed"
    assert first["error"] == {
        "type": "ModelNeeded",
        "message": "Connect an AI model in Settings to run agents.",
        "retryable": False,
    }
    assert first["events"] == []
    # The same task id runs once a model is connected, because the failure was not stored.
    again = client.post("/v1/tasks", json=card_body()).json()
    assert again["status"] == "finished"


def test_a_value_that_does_not_fit_its_input_kind_is_refused_before_anything_runs():
    body = card_body()
    body["inputs"]["agents"][0]["values"]["Jira project"] = "not a key"
    chat = ScriptedChat(script=[])
    response = make_app(chat).post("/v1/tasks", json=body)
    assert response.status_code == 422
    assert "not a key" not in response.text
    assert chat.calls == []


def test_drafting_returns_the_draft_and_needs_the_key():
    answer = {
        "can_do": True,
        "name": "Release checker",
        "purpose": "Checks a repository.",
        "blocks": [{"say": "Read.", "tool": "github.read_releases"}],
    }
    chat = ScriptedChat(structured=[draft_answer(**answer)])
    client = make_app(chat)
    body = json.loads(draft_request().model_dump_json())
    assert (
        client.post("/v1/cards/draft", json=body, headers={"X-Agent-Key": "no"}).status_code == 401
    )
    reply = client.post("/v1/cards/draft", json=body).json()
    assert reply["status"] == "drafted"
    assert reply["draft"]["blocks"] == [{"say": "Read.", "tool": "github.read_releases"}]


def test_choosing_returns_the_choice():
    chat = ScriptedChat(
        structured=[
            ChoiceAnswer(
                decision="use_one",
                reason="It fits.",
                agents=[AgentAnswer(card_id="crd_release_checker", part="Do it.")],
            )
        ]
    )
    body = json.loads(choose_request().model_dump_json())
    reply = make_app(chat).post("/v1/room/choose", json=body).json()
    assert reply["status"] == "chosen"
    assert reply["choice"]["decision"] == "use_one"


def test_a_model_that_fails_is_a_problem_not_an_http_error():
    chat = ScriptedChat(structured=[RuntimeError(f"bad key {EXAMPLE_KEY}")])
    body = json.loads(draft_request().model_dump_json())
    response = make_app(chat).post("/v1/cards/draft", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "problem"
    assert EXAMPLE_KEY not in response.text


def test_the_practice_jira_address_comes_from_the_environment():
    assert SETTINGS.practice_jira_url is None
    settings = Settings.from_env({**BASE_ENV, "PRACTICE_JIRA_URL": ORIGIN})
    assert settings.practice_jira_url == ORIGIN
    runtime = build_runtime(settings)
    assert runtime.cards is not None
    reader = PracticeJiraFor(ORIGIN)(card_request("run_01JD1"))
    assert reader is not None


def test_without_a_practice_jira_address_the_jira_tools_have_no_reader():
    runtime = build_runtime(SETTINGS)
    assert runtime.cards is not None
    assert runtime.cards.jira_for(card_request("run_01JD1")) is None


def test_the_runtime_has_no_model_of_its_own_unless_one_is_set():
    assert build_runtime(SETTINGS).chat_source(None) is None
    configured = Settings.from_env({**BASE_ENV, "AGENT_SUMMARY_MODEL": "claude-haiku-5-5"})
    assert build_runtime(configured).chat_source(None) is not None
