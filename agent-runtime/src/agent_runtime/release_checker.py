# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Protocol, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_runtime.contract import (
    AgentFailedData,
    AgentMessageData,
    AgentRef,
    AgentStepFinishedData,
    AgentStepStartedData,
    CarryForward,
    ProposedIntent,
    ReleaseCheckInputs,
    RoomAddressee,
    TaskError,
    TaskOutput,
)
from agent_runtime.events import Draft
from agent_runtime.summary import Summarizer
from agent_runtime.tags import family_of, highest, newer_than

CHECKER = AgentRef(id="release_checker", display="Release checker")
SOURCE_NAME = "GitHub"
REPO_NAMES = {"langchain-ai/langgraph": "LangGraph"}
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


@dataclass
class CheckerState:
    inputs: ReleaseCheckInputs
    last_known_tag: str | None
    releases: list[Release] = field(default_factory=list[Release])
    candidates: list[str] = field(default_factory=list[str])
    new_tags: list[str] = field(default_factory=list[str])
    baseline: str | None = None
    output: TaskOutput | None = None
    error: TaskError | None = None


type Update = dict[str, object]


class ReleaseChecker:
    def __init__(
        self,
        source: ReleaseSource,
        summarizer: Summarizer,
        sleep: Callable[[float], None],
        retry: RetryPolicy = DEFAULT_RETRY,
    ) -> None:
        self._source = source
        self._summarizer = summarizer
        self._sleep = sleep
        self._retry = retry
        self._graph = self._build()

    def check(
        self,
        inputs: ReleaseCheckInputs,
        last_known_tag: str | None,
        emit: Callable[[Draft], None],
    ) -> TaskOutput | TaskError:
        if rejection := _reject_unusable(inputs, last_known_tag):
            emit(_failed(None, rejection, "the task could not be read."))
            return rejection
        start = CheckerState(inputs=inputs, last_known_tag=last_known_tag)
        final: dict[str, object] = {}
        for mode, chunk in self._graph.stream(start, stream_mode=["custom", "values"]):
            if mode == "custom" and isinstance(chunk, Draft):
                emit(chunk)
            elif mode == "values" and isinstance(chunk, dict):
                final = cast(dict[str, object], chunk)
        outcome = final.get("error") or final.get("output")
        assert isinstance(outcome, TaskError | TaskOutput)
        return outcome

    def _build(self):
        graph = StateGraph(CheckerState)
        graph.add_node("fetch_releases", self._fetch_releases)
        graph.add_node("find_new", self._find_new)
        graph.add_node("report", self._report)
        graph.add_edge(START, "fetch_releases")
        graph.add_conditional_edges("fetch_releases", _stop_on_error("find_new"), ["find_new", END])
        graph.add_edge("find_new", "report")
        graph.add_edge("report", END)
        return graph.compile()

    def _fetch_releases(self, state: CheckerState) -> Update:
        write = get_stream_writer()
        inputs = state.inputs
        write(_started("fetch_releases", f"fetching releases from {inputs.repo}."))
        tries = self._retry.tries
        for attempt in range(1, tries + 1):
            try:
                releases = self._source.fetch(inputs.repo)
            except SourceRejected as refused:
                error = TaskError(
                    type="UpstreamRejected",
                    message=f"{SOURCE_NAME} answered {_phrase(refused.status)}",
                    retryable=False,
                )
                write(_failed("fetch_releases", error, "GitHub refused the request."))
                return {"error": error}
            except SourceUnavailable as unavailable:
                gave_up = attempt == tries
                wait = f"Waiting {self._retry.wait_seconds:g} s before trying again."
                write(
                    _try_failed(unavailable, attempt, tries, "I am giving up." if gave_up else wait)
                )
                if gave_up:
                    error = TaskError(
                        type="UpstreamUnavailable",
                        message=f"{_gave_up_message(unavailable)} {_word(tries)} times",
                        retryable=True,
                    )
                    write(_failed("fetch_releases", error, "GitHub was unavailable."))
                    return {"error": error}
                self._sleep(self._retry.wait_seconds)
            else:
                candidates = _candidates(releases, inputs.tag_pattern)
                latest = candidates[0] if candidates else None
                tail = f" The latest is {latest}." if latest else ""
                write(
                    _finished(
                        "fetch_releases",
                        f"fetched {len(releases)} releases.{tail}",
                        {"release_count": len(releases), "latest": latest},
                    )
                )
                return {"releases": releases, "candidates": candidates}
        raise AssertionError("the retry loop always returns")

    def _find_new(self, state: CheckerState) -> Update:
        write = get_stream_writer()
        last, candidates = state.last_known_tag, state.candidates
        write(
            _started("find_new", f"comparing them with the last known tag {last}.")
            if last
            else _started(
                "find_new", "looking for a starting point, as there is no last known tag."
            )
        )
        new_tags = newer_than(last, candidates) if last else []
        baseline = None if last else highest(candidates)
        if last:
            said = (
                f"found {_plural(len(new_tags), 'new release')}: {', '.join(new_tags)}."
                if new_tags
                else "found no new releases."
            )
        else:
            said = (
                f"took {baseline} as the starting point."
                if baseline
                else "found no release to start from."
            )
        result: dict[str, object] = {"new_count": len(new_tags), "tags": new_tags}
        if baseline:
            result["baseline"] = baseline
        write(_finished("find_new", said, result))
        return {"new_tags": new_tags, "baseline": baseline}

    def _report(self, state: CheckerState) -> Update:
        inputs, last = state.inputs, state.last_known_tag
        new_tags, baseline = state.new_tags, state.baseline
        write = get_stream_writer()
        if last and new_tags:
            write(_report_new(last, new_tags))
            output = TaskOutput(
                summary=self._summarizer.summarise(inputs.repo, last, new_tags),
                new_tags=new_tags,
                proposed=[_ticket(inputs.repo, last, new_tags)],
                carry_forward=CarryForward(last_known_tag=new_tags[0]),
            )
        elif last:
            write(
                _to_room(
                    "reported no new releases to the room.",
                    f"Nothing is newer than {last}. I have nothing to propose.",
                )
            )
            output = _nothing(f"No new releases since {last}", last)
        elif baseline:
            write(
                _to_room(
                    "reported a starting point to the room.",
                    f"There was no last known tag, so I will remember {baseline} "
                    "as the starting point. I have nothing to propose.",
                )
            )
            output = _nothing(f"Starting point recorded: {baseline}", baseline)
        else:
            write(
                _to_room(
                    "reported to the room that no release matches.",
                    "No release matches the tag pattern. I have nothing to propose.",
                )
            )
            output = _nothing("No releases match the pattern", None)
        return {"output": output}


def _stop_on_error(next_node: str) -> Callable[[CheckerState], str]:
    def route(state: CheckerState) -> str:
        return END if state.error else next_node

    return route


def _reject_unusable(inputs: ReleaseCheckInputs, last_known_tag: str | None) -> TaskError | None:
    try:
        re.compile(inputs.tag_pattern)
    except re.error as bad_pattern:
        return TaskError(
            type="InvalidTask",
            message=f"The tag pattern cannot be used: {bad_pattern}",
            retryable=False,
        )
    if last_known_tag and family_of(last_known_tag) is None:
        return TaskError(
            type="InvalidTask", message=f"{last_known_tag!r} is not a version tag", retryable=False
        )
    return None


def _candidates(releases: list[Release], tag_pattern: str) -> list[str]:
    pattern = re.compile(tag_pattern)
    return [r.tag for r in releases if not (r.draft or r.prerelease) and pattern.search(r.tag)]


def _nothing(summary: str, last_known_tag: str | None) -> TaskOutput:
    return TaskOutput(
        summary=summary,
        new_tags=[],
        proposed=[],
        carry_forward=CarryForward(last_known_tag=last_known_tag),
    )


def _ticket(repo: str, last: str, new_tags: list[str]) -> ProposedIntent:
    bullets = "\n".join(f"- {tag}" for tag in new_tags)
    return ProposedIntent(
        kind="create_ticket",
        fields={
            "title": f"New {REPO_NAMES.get(repo, repo)} releases: {', '.join(new_tags)}",
            "body": f"Releases newer than {last} on {repo}:\n{bullets}\n\n"
            "Proposed by the AI workflow builder.",
        },
        reason=f"New {family_of(last) or 'plain-version'} releases since {last}",
    )


def _word(number: int) -> str:
    return NUMBER_WORDS[number] if number < len(NUMBER_WORDS) else str(number)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _tag_list(tags: list[str]) -> str:
    return tags[0] if len(tags) == 1 else f"{', '.join(tags[:-1])} and {tags[-1]}"


def _phrase(status: int) -> str:
    return f"{status} {HTTPStatus(status).phrase}"


def _gave_up_message(error: SourceUnavailable) -> str:
    if error.status:
        return f"{SOURCE_NAME} returned {_phrase(error.status)}"
    return f"{SOURCE_NAME} could not be reached"


def _started(step: str, what: str) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Release checker is {what}",
        data=AgentStepStartedData(step=step),
    )


def _finished(step: str, what: str, result: dict[str, object]) -> Draft:
    return Draft(
        agent=CHECKER,
        summary=f"Release checker {what}",
        data=AgentStepFinishedData(step=step, result=result),
    )


def _to_room(summary_tail: str, text: str) -> Draft:
    data = AgentMessageData(speaker=CHECKER, addressee=RoomAddressee(), text=text)
    return Draft(agent=CHECKER, summary=f"Release checker {summary_tail}", data=data)


def _try_failed(error: SourceUnavailable, attempt: int, tries: int, ending: str) -> Draft:
    short = f"answered {error.status}" if error.status else "could not be reached"
    long = f"answered {_phrase(error.status)}" if error.status else "could not be reached"
    return _to_room(
        f"reported that {SOURCE_NAME} {short} (try {attempt} of {tries}).",
        f"{SOURCE_NAME} {long} (try {attempt} of {tries}). {ending}",
    )


def _report_new(last: str, new_tags: list[str]) -> Draft:
    count = len(new_tags)
    verb = "release is" if count == 1 else "releases are"
    suggestion = (
        "a ticket so the team can review it"
        if count == 1
        else (
            "one ticket so the team reviews both"
            if count == 2
            else "one ticket so the team reviews them all"
        )
    )
    return _to_room(
        f"reported {_plural(count, 'new release')} to the room and suggested one ticket.",
        f"{_word(count).capitalize()} {verb} newer than {last}: {_tag_list(new_tags)}. "
        f"I suggest {suggestion}.",
    )


def _failed(step: str | None, error: TaskError, reason: str) -> Draft:
    data = AgentFailedData(
        step=step, error_type=error.type, message=error.message, retryable=error.retryable
    )
    return Draft(agent=CHECKER, summary=f"Release checker failed: {reason}", data=data)
