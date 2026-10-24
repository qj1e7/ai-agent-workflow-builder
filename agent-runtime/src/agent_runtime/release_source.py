import re
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Protocol

from agent_runtime.contract import (
    AgentFailedData,
    AgentMessageData,
    AgentRef,
    AgentStepFinishedData,
    AgentStepStartedData,
    RoomAddressee,
    TaskError,
)
from agent_runtime.events import Draft

CHECKER = AgentRef(id="release_checker", display="Release checker")
SOURCE_NAME = "GitHub"
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


@dataclass(frozen=True)
class Release:
    tag: str
    prerelease: bool = False
    draft: bool = False


class SourceUnavailable(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(status)
        self.status = status


class SourceRejected(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class ReleaseSource(Protocol):
    def fetch(self, repo: str) -> list[Release]: ...


@dataclass(frozen=True)
class RetryPolicy:
    tries: int = 3
    wait_seconds: float = 2.0


DEFAULT_RETRY = RetryPolicy()


def read_releases(
    source: ReleaseSource,
    repo: str,
    retry: RetryPolicy,
    sleep: Callable[[float], None],
    write: Callable[[Draft], None],
) -> list[Release] | TaskError:
    """Reads one source. A 5xx or no answer is tried again, a 4xx stops at once."""
    for attempt in range(1, retry.tries + 1):
        try:
            return source.fetch(repo)
        except SourceRejected as refused:
            return TaskError(
                type="UpstreamRejected",
                message=f"{SOURCE_NAME} answered {phrase(refused.status)}",
                retryable=False,
            )
        except SourceUnavailable as unavailable:
            gave_up = attempt == retry.tries
            wait = f"Waiting {retry.wait_seconds:g} s before trying again."
            ending = "I am giving up." if gave_up else wait
            write(try_failed(unavailable, attempt, retry.tries, ending))
            if gave_up:
                return TaskError(
                    type="UpstreamUnavailable",
                    message=f"{gave_up_message(unavailable)} {word(retry.tries)} times",
                    retryable=True,
                )
            sleep(retry.wait_seconds)
    raise AssertionError("the retry loop always returns")


def candidates(releases: list[Release], tag_pattern: str) -> list[str]:
    pattern = re.compile(tag_pattern)
    return [r.tag for r in releases if not (r.draft or r.prerelease) and pattern.search(r.tag)]


def word(number: int) -> str:
    return NUMBER_WORDS[number] if number < len(NUMBER_WORDS) else str(number)


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def tag_list(tags: list[str]) -> str:
    return tags[0] if len(tags) == 1 else f"{', '.join(tags[:-1])} and {tags[-1]}"


def phrase(status: int) -> str:
    return f"{status} {HTTPStatus(status).phrase}"


def gave_up_message(error: SourceUnavailable) -> str:
    if error.status:
        return f"{SOURCE_NAME} returned {phrase(error.status)}"
    return f"{SOURCE_NAME} could not be reached"


def started(step: str, what: str) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Release checker is {what}",
        data=AgentStepStartedData(step=step),
    )


def finished(step: str, what: str, result: dict[str, object]) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Release checker {what}",
        data=AgentStepFinishedData(step=step, result=result),
    )


def to_room(summary_tail: str, text: str) -> Draft:
    data = AgentMessageData(speaker=CHECKER, addressee=RoomAddressee(), text=text)
    return Draft(agent=CHECKER, summary=f"Release checker {summary_tail}", data=data)


def try_failed(error: SourceUnavailable, attempt: int, tries: int, ending: str) -> Draft:
    short = f"answered {error.status}" if error.status else "could not be reached"
    long = f"answered {phrase(error.status)}" if error.status else "could not be reached"
    return to_room(
        f"reported that {SOURCE_NAME} {short} (try {attempt} of {tries}).",
        f"{SOURCE_NAME} {long} (try {attempt} of {tries}). {ending}",
    )


def failed(step: str | None, error: TaskError, reason: str) -> Draft:
    data = AgentFailedData(
        step=step, error_type=error.type, message=error.message, retryable=error.retryable
    )
    return Draft(agent=CHECKER, summary=f"Release checker failed: {reason}", data=data)
