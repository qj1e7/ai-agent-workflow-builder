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

CHECKER = AgentRef(id="version_checker", display="Version checker")
SOURCE_NAME = "GitHub"
LIMITED = f"{SOURCE_NAME} is limiting how often we can ask it. Try again later"


def limited_message(source_name: str) -> str:
    return f"{source_name} is limiting how often we can ask it. Try again later"


NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


@dataclass(frozen=True)
class Release:
    tag: str
    prerelease: bool = False
    draft: bool = False
    name: str | None = None
    published_at: str | None = None
    notes: str | None = None


class SourceUnavailable(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(status)
        self.status = status


class SourceRejected(Exception):
    def __init__(self, status: int, limited: bool = False) -> None:
        super().__init__(status)
        self.status = status
        # GitHub refuses with a 403 when asked too often. Only its headers or message say so.
        self.limited = limited


@dataclass(frozen=True)
class Fetched:
    releases: list[Release]
    # GitHub sent the request to another address, as it does for a renamed repository.
    redirected: bool = False


class ReleaseSource(Protocol):
    def fetch(self, repo: str) -> list[Release]: ...


class MovableSource(ReleaseSource, Protocol):
    def fetch_noting_move(self, repo: str) -> Fetched: ...

    def current_name(self, repo: str) -> str: ...


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
    agent: AgentRef = CHECKER,
    source_name: str = SOURCE_NAME,
) -> list[Release] | TaskError:
    """Reads one source. A 5xx or no answer is tried again, a 4xx stops at once."""
    for attempt in range(1, retry.tries + 1):
        try:
            return source.fetch(repo)
        except SourceRejected as refused:
            if refused.limited:
                return TaskError(
                    type="UpstreamUnavailable",
                    message=limited_message(source_name),
                    retryable=True,
                )
            return TaskError(
                type="UpstreamRejected",
                message=f"{source_name} answered {phrase(refused.status)}",
                retryable=False,
            )
        except SourceUnavailable as unavailable:
            gave_up = attempt == retry.tries
            wait = f"Waiting {retry.wait_seconds:g} s before trying again."
            ending = "I am giving up." if gave_up else wait
            write(try_failed(unavailable, attempt, retry.tries, ending, agent, source_name))
            if gave_up:
                return TaskError(
                    type="UpstreamUnavailable",
                    message=f"{gave_up_message(unavailable, source_name)} "
                    f"{word(retry.tries)} times",
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


def could_not_check(name: str, detail: str) -> str:
    return f"Could not check {name}: {detail}"


def gave_up_message(error: SourceUnavailable, source_name: str = SOURCE_NAME) -> str:
    if error.status:
        return f"{source_name} returned {phrase(error.status)}"
    return f"{source_name} could not be reached"


def started(step: str, what: str) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Version checker is {what}",
        data=AgentStepStartedData(step=step),
    )


def finished(step: str, what: str, result: dict[str, object]) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Version checker {what}",
        data=AgentStepFinishedData(step=step, result=result),
    )


def to_room(summary_tail: str, text: str, agent: AgentRef = CHECKER) -> Draft:
    data = AgentMessageData(speaker=agent, addressee=RoomAddressee(), text=text)
    return Draft(agent=agent, summary=f"{agent.display} {summary_tail}", data=data)


def try_failed(
    error: SourceUnavailable,
    attempt: int,
    tries: int,
    ending: str,
    agent: AgentRef = CHECKER,
    source_name: str = SOURCE_NAME,
) -> Draft:
    short = f"answered {error.status}" if error.status else "could not be reached"
    long = f"answered {phrase(error.status)}" if error.status else "could not be reached"
    return to_room(
        f"reported that {source_name} {short} (try {attempt} of {tries}).",
        f"{source_name} {long} (try {attempt} of {tries}). {ending}",
        agent,
    )


def failed(step: str | None, error: TaskError, reason: str) -> Draft:
    data = AgentFailedData(
        step=step, error_type=error.type, message=error.message, retryable=error.retryable
    )
    return Draft(agent=CHECKER, summary=f"Version checker failed: {reason}", data=data)
