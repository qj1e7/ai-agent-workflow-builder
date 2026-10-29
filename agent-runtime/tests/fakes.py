from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from agent_runtime.jira import JiraTicket, JiraUnavailable
from agent_runtime.version_checker import Release, SourceRejected, SourceUnavailable


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 3, 2, 14, 2, tzinfo=UTC)
        self.slept: list[float] = []
        self.on_sleep: Callable[[], object] = lambda: None

    def __call__(self) -> datetime:
        self.now += timedelta(milliseconds=100)
        return self.now

    def sleep(self, seconds: float) -> None:
        self.on_sleep()
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class FakeSource:
    def __init__(self, tags: list[str], failures: Sequence[int | None] = ()) -> None:
        self.releases = [Release(tag=tag) for tag in tags]
        self.failures = list(failures)
        self.calls: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.calls.append(repo)
        if self.failures:
            raise SourceUnavailable(self.failures.pop(0))
        return self.releases


class RepoSource:
    """Answers per repository: its tags, a refusal (4xx) or an outage (5xx) that never ends."""

    def __init__(
        self,
        tags: dict[str, list[str]],
        refused: dict[str, int] | None = None,
        down: dict[str, int] | None = None,
    ) -> None:
        self.tags = tags
        self.refused = refused or {}
        self.down = down or {}
        self.calls: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.calls.append(repo)
        if repo in self.refused:
            raise SourceRejected(self.refused[repo])
        if repo in self.down:
            raise SourceUnavailable(self.down[repo])
        return [Release(tag=tag) for tag in self.tags[repo]]


def langgraph_tags() -> list[str]:
    older = [f"1.2.{patch}" for patch in range(13, -1, -1)]
    oldest = [f"1.1.{patch}" for patch in range(12, -1, -1)]
    return ["1.2.16", "1.2.15", "1.2.14", *older, *oldest][:30]


class ScriptedChat(BaseChatModel):
    """A chat model that answers from a script, one message per call. It records every call, the
    tools it was offered, and the shapes it was asked to answer in."""

    script: list[Any] = Field(default_factory=list[Any])
    structured: list[object] = Field(default_factory=list[object])
    calls: list[list[BaseMessage]] = Field(default_factory=list[list[BaseMessage]])
    offered: list[list[str]] = Field(default_factory=list[list[str]])
    asked: list[type[BaseModel]] = Field(default_factory=list[type[BaseModel]])
    on_call: Callable[[], object] = lambda: None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        self.calls.append(list(messages))
        self.on_call()
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ChatResult(generations=[ChatGeneration(message=step)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:  # type: ignore[override]
        self.offered.append([tool["function"]["name"] for tool in tools])
        return self  # type: ignore[return-value]

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:  # type: ignore[override]
        self.asked.append(schema)

        def answer(messages: Any) -> dict[str, object]:
            self.calls.append(list(messages))
            self.on_call()
            step = self.structured.pop(0)
            if isinstance(step, Exception):
                raise step
            return {"raw": AIMessage(""), "parsed": step, "parsing_error": None}

        return RunnableLambda(answer)


def call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def asks(*calls: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))  # type: ignore[arg-type]


class FakeJira:
    """A Jira with a few tickets. It records what it was asked."""

    def __init__(self, tickets: Sequence[JiraTicket] = ()) -> None:
        self.tickets = list(tickets)
        self.searches: list[tuple[str, str | None, str | None, str | None]] = []
        self.reads: list[str] = []

    def search(
        self, project: str, text: str | None, status: str | None, done_since: str | None
    ) -> list[JiraTicket]:
        self.searches.append((project, text, status, done_since))
        return [t for t in self.tickets if t.project == project]

    def read(self, key: str) -> JiraTicket:
        self.reads.append(key)
        for ticket in self.tickets:
            if ticket.key == key:
                return ticket
        raise JiraUnavailable("Jira has no such ticket.")
