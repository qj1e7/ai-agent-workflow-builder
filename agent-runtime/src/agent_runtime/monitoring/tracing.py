"""The port the runtime records traces through (ADR 0050). Run monitoring owns the trace's shape
and the score names. Agent code never imports an adapter: only the API's start-up code picks one
and wraps the chat models with it."""

import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from agent_runtime import free_reply
from agent_runtime.contract import (
    Answered,
    AnswerRequest,
    AnswerResult,
    TaskRequest,
)
from agent_runtime.fixed_replies import says_it_didnt_follow
from agent_runtime.summary import ChatFor

type CodeFlag = Literal["flag_didnt_follow", "flag_fallback", "flag_parts_crossed", "flag_slow"]

# ADR 0049's bar for a Planner answer.
SLOW_SECONDS: Final = 13.0
# A free reply that fell back because its model call failed was not rejected by a check.
CALL_FAILED: Final = "call"


@dataclass(frozen=True)
class TurnOutcome:
    result: AnswerResult
    seconds: float
    fell_back: str | None = None
    """Why the free reply fell back, if it did: the guard's check, the verifier's flag, or
    `call` when its model call failed."""

    @property
    def answered(self) -> Answered | None:
        return self.result if isinstance(self.result, Answered) else None


CODE_FLAGS: Final[Mapping[CodeFlag, Callable[[TurnOutcome], bool]]] = {
    "flag_didnt_follow": lambda o: (
        o.answered is not None and says_it_didnt_follow(o.answered.answer)
    ),
    "flag_fallback": lambda o: o.fell_back is not None and o.fell_back != CALL_FAILED,
    "flag_parts_crossed": lambda o: (
        o.answered is not None and any(part.mark == "cant" for part in o.answered.parts)
    ),
    "flag_slow": lambda o: o.seconds > SLOW_SECONDS,
}


def code_flags(outcome: TurnOutcome) -> list[CodeFlag]:
    """The code flags a turn raised. A flag is written only when it is true."""
    return [name for name, raised in CODE_FLAGS.items() if raised(outcome)]


def answer_kind(result: AnswerResult) -> str:
    return result.answer.kind if isinstance(result, Answered) else result.reason


class Traced(Protocol):
    def models(self, chat_for: ChatFor) -> ChatFor:
        """The same chat models, each recording its calls in this trace."""
        ...


class TracedTurn(Traced, Protocol):
    def answered(self, result: AnswerResult, fell_back: str | None = None) -> None:
        """Records the answer the person saw, and writes the turn's code flags. `fell_back` is
        why the turn fell back, when the caller knows it: the AI-led Planner says so itself."""
        ...


class Tracing(Protocol):
    def turn(self, request: AnswerRequest) -> AbstractContextManager[TracedTurn]:
        """One Planner turn, as one trace in the Portal chat's session."""
        ...

    def run(self, request: TaskRequest) -> AbstractContextManager[Traced]:
        """One agent task, as one trace in its run's session."""
        ...


class _Untraced:
    def models(self, chat_for: ChatFor) -> ChatFor:
        return chat_for

    def answered(self, result: AnswerResult, fell_back: str | None = None) -> None:
        pass


class NoTracing:
    """Tracing is off: nothing is recorded and nothing leaves."""

    @contextmanager
    def turn(self, request: AnswerRequest) -> Generator[TracedTurn]:
        yield _Untraced()

    @contextmanager
    def run(self, request: TaskRequest) -> Generator[Traced]:
        yield _Untraced()


# The free reply logs why it fell back in its record's `fell_back` field. A filter that drops
# nothing collects it for the turn being traced, and only for that turn. A filter rather than a
# handler, so the runtime's warnings still reach the console as before.
_fell_back: ContextVar[list[str] | None] = ContextVar("fell_back", default=None)


class _FellBack(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        notes = _fell_back.get()
        reason: object = getattr(record, "fell_back", None)
        if notes is not None and isinstance(reason, str):
            notes.append(reason)
        return True


free_reply.log.addFilter(_FellBack())


@contextmanager
def fell_back_notes() -> Generator[list[str]]:
    notes: list[str] = []
    token = _fell_back.set(notes)
    try:
        yield notes
    finally:
        _fell_back.reset(token)
