"""The Confluence tool: a page the team allows, read through the platform."""

import json
from datetime import date
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_runtime.card_runner import CardRunner
from agent_runtime.confluence import (
    ConfluencePage,
    ConfluenceRefused,
    ConfluenceUnavailable,
    PlatformConfluenceFor,
)
from agent_runtime.contract import (
    AgentFailedEvent,
    AgentStepFinishedEvent,
    CardBlock,
    CardsInputs,
    CardToRun,
    TaskFailed,
    TaskFinished,
    TaskRequest,
)
from agent_runtime.contracts import card_request, version_checker_card
from agent_runtime.events import EventLog
from agent_runtime.planner import FixedPlanner, run_cards
from tests.fakes import FakeClock, FakeSource, ScriptedChat, asks, call, langgraph_tags
from tests.test_card_runner import tool_answers

BASE = "http://platform-api:8000"
TODAY = date(2026, 11, 13)
PAGE = ConfluencePage(
    id="123456",
    title="Software inventory",
    version=4,
    url="https://ncs-test.atlassian.net/wiki/pages/viewpage.action?pageId=123456",
    text="Software | Ours\nLangGraph | 1.2.14",
)


class FakeConfluence:
    def __init__(self, pages: dict[str, ConfluencePage] | None = None) -> None:
        self.pages = {PAGE.title: PAGE} if pages is None else pages
        self.reads: list[str] = []
        self.refuse: str | None = None

    def read(self, page: str) -> ConfluencePage | None:
        self.reads.append(page)
        if self.refuse is not None:
            raise ConfluenceRefused(self.refuse)
        return self.pages.get(page)


def request_with(*tools: str | None) -> TaskRequest:
    blocks = [CardBlock(say=f"Step {n}.", tool=tool) for n, tool in enumerate(tools, 1)]  # type: ignore[arg-type]
    card = version_checker_card().model_copy(update={"blocks": blocks, "inputs": []})
    inputs = CardsInputs(agents=[CardToRun(card=card, values={})])
    return card_request("run_01JD1").model_copy(update={"inputs": inputs})


def run(chat: ScriptedChat, confluence: FakeConfluence | None, request: TaskRequest):
    clock = FakeClock()
    runner = CardRunner(
        FakeSource(langgraph_tags()[:8]),
        lambda _: None,
        sleep=clock.sleep,
        confluence_for=lambda _: confluence,
    )
    inputs = request.inputs
    assert isinstance(inputs, CardsInputs)
    events = EventLog(clock, lambda _: None)
    return run_cards(request, inputs, FixedPlanner(), runner, lambda _: chat, TODAY, events)


def read_then_report(page: str = "Software inventory") -> list[AIMessage | Exception]:
    return [
        asks(call("confluence_read_page", {"page": page}, "t1")),
        AIMessage("LangGraph is at 1.2.14."),
    ]


def finished_steps(result: TaskFinished | TaskFailed) -> list[str]:
    return [e.summary for e in result.events if isinstance(e, AgentStepFinishedEvent)]


def test_a_page_the_platform_refuses_stops_the_agent_and_cannot_be_retried():
    confluence = FakeConfluence()
    confluence.refuse = "This run may not read that Confluence page"
    chat = ScriptedChat(script=read_then_report("Board salaries"))
    result = run(chat, confluence, request_with("confluence.read_page"))
    assert isinstance(result, TaskFailed)
    assert (result.error.type, result.error.retryable) == ("ConfluenceRefused", False)
    assert "may not read that Confluence page" in result.error.message
    failed = [e for e in result.events if isinstance(e, AgentFailedEvent)]
    assert failed[-1].data.step == "confluence_read_page"


def test_without_confluence_the_agent_stops_and_says_it_is_not_connected():
    chat = ScriptedChat(script=read_then_report())
    result = run(chat, None, request_with("confluence.read_page"))
    assert isinstance(result, TaskFailed)
    assert (result.error.type, result.error.message) == (
        "ConfluenceNotConnected",
        "Could not read the Confluence page Software inventory: Confluence is not connected.",
    )


def test_a_page_confluence_does_not_have_is_told_to_the_model():
    chat = ScriptedChat(
        script=[
            asks(call("confluence_read_page", {"page": "Gone"}, "t1")),
            AIMessage("That page is gone."),
        ]
    )
    result = run(chat, FakeConfluence(), request_with("confluence.read_page"))
    assert isinstance(result, TaskFinished)
    assert tool_answers(chat)[0] == {"error": "Confluence has no such page."}


def test_a_page_is_read_as_its_plain_lines():
    chat = ScriptedChat(
        script=[
            asks(call("confluence_read_page", {"page": "Software inventory"}, "t1")),
            AIMessage("Read it."),
        ]
    )
    result = run(chat, FakeConfluence(), request_with("confluence.read_page"))
    assert isinstance(result, TaskFinished)
    page = tool_answers(chat)[0]["data"]
    assert (page["title"], page["version"], page["text"]) == ("Software inventory", 4, PAGE.text)
    assert finished_steps(result) == [
        "Version checker read the Confluence page Software inventory."
    ]
    assert result.output.proposed == []


def reader(handler: httpx.MockTransport):
    request = card_request("run_01JD1")
    client = httpx.Client(transport=handler, follow_redirects=True)
    confluence = PlatformConfluenceFor(BASE, client)(request)
    assert confluence is not None
    return confluence, request


def test_a_read_asks_the_platform_by_the_pages_name_with_the_token_in_a_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=json.loads(PAGE.model_dump_json()))

    confluence, request = reader(httpx.MockTransport(handler))
    assert confluence.read("Software inventory / 2026") == PAGE
    [sent] = seen
    assert sent.url.raw_path.decode().split("?")[0] == (
        "/internal/v1/runs/run_01JD1/confluence/pages/Software%20inventory%20%2F%202026"
    )
    assert dict(sent.url.params) == {"task": request.task_id}
    assert sent.headers["x-callback-token"] == request.callback.token


@pytest.mark.parametrize(
    ("status", "body", "raised", "said"),
    [
        (403, {"detail": "This run may not read that Confluence page"}, ConfluenceRefused, "may"),
        (424, {"detail": "Confluence is not connected."}, ConfluenceRefused, "not connected"),
        (503, {"detail": "Confluence could not answer"}, ConfluenceUnavailable, "could not"),
        (200, {"id": "1"}, ConfluenceUnavailable, "could not be read"),
    ],
)
def test_the_platforms_refusals_and_outages_come_back_in_plain_words(
    status: int, body: dict[str, Any], raised: type[Exception], said: str
):
    confluence, _ = reader(httpx.MockTransport(lambda _: httpx.Response(status, json=body)))
    with pytest.raises(raised, match=said):
        confluence.read("Software inventory")


def test_a_page_the_platform_does_not_find_is_none():
    confluence, _ = reader(httpx.MockTransport(lambda _: httpx.Response(404, json={})))
    assert confluence.read("Gone") is None
