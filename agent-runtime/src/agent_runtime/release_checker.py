# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_runtime.contract import (
    CarryForward,
    ProposedIntent,
    ReleaseCheckInputs,
    TaskError,
    TaskOutput,
    WatchlistInputs,
)
from agent_runtime.events import Draft
from agent_runtime.release_source import (
    CHECKER,
    DEFAULT_RETRY,
    Release,
    ReleaseSource,
    RetryPolicy,
    SourceRejected,
    SourceUnavailable,
    candidates,
    failed,
    finished,
    plural,
    read_releases,
    started,
    tag_list,
    to_room,
    word,
)
from agent_runtime.summary import Summarizer
from agent_runtime.tags import family_of, highest, newer_than
from agent_runtime.watchlist import WatchlistChecker

__all__ = [
    "CHECKER",
    "Release",
    "ReleaseChecker",
    "ReleaseSource",
    "RetryPolicy",
    "SourceRejected",
    "SourceUnavailable",
]

REPO_NAMES = {"langchain-ai/langgraph": "LangGraph"}


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
        self._watchlist = WatchlistChecker(source, summarizer, sleep, retry)
        self._graph = self._build()

    def with_summarizer(self, summarizer: Summarizer) -> ReleaseChecker:
        return ReleaseChecker(self._source, summarizer, self._sleep, self._retry)

    def check(
        self,
        inputs: ReleaseCheckInputs,
        last_known_tag: str | None,
        emit: Callable[[Draft], None],
    ) -> TaskOutput | TaskError:
        if rejection := _reject_unusable(last_known_tag):
            emit(failed(None, rejection, "the task could not be read."))
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

    def check_watchlist(
        self, inputs: WatchlistInputs, emit: Callable[[Draft], None]
    ) -> TaskOutput | TaskError:
        return self._watchlist.check(inputs, emit)

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
        write(started("fetch_releases", f"fetching releases from {inputs.repo}."))
        outcome = read_releases(self._source, inputs.repo, self._retry, self._sleep, write)
        if isinstance(outcome, TaskError):
            gone = "GitHub was unavailable." if outcome.retryable else "GitHub refused the request."
            write(failed("fetch_releases", outcome, gone))
            return {"error": outcome}
        found = candidates(outcome, inputs.tag_pattern)
        latest = found[0] if found else None
        tail = f" The latest is {latest}." if latest else ""
        write(
            finished(
                "fetch_releases",
                f"fetched {len(outcome)} releases.{tail}",
                {"release_count": len(outcome), "latest": latest},
            )
        )
        return {"releases": outcome, "candidates": found}

    def _find_new(self, state: CheckerState) -> Update:
        write = get_stream_writer()
        last, candidates = state.last_known_tag, state.candidates
        write(
            started("find_new", f"comparing them with the last known tag {last}.")
            if last
            else started("find_new", "looking for a starting point, as there is no last known tag.")
        )
        new_tags = newer_than(last, candidates) if last else []
        baseline = None if last else highest(candidates)
        if last:
            said = (
                f"found {plural(len(new_tags), 'new release')}: {', '.join(new_tags)}."
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
        write(finished("find_new", said, result))
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
                to_room(
                    "reported no new releases to the room.",
                    f"Nothing is newer than {last}. I have nothing to propose.",
                )
            )
            output = _nothing(f"No new releases since {last}", last)
        elif baseline:
            write(
                to_room(
                    "reported a starting point to the room.",
                    f"There was no last known tag, so I will remember {baseline} "
                    "as the starting point. I have nothing to propose.",
                )
            )
            output = _nothing(f"Starting point recorded: {baseline}", baseline)
        else:
            write(
                to_room(
                    "reported to the room that no release matches.",
                    "No release has a plain version number I can compare. "
                    "I have nothing to propose.",
                )
            )
            output = _nothing("No releases match the pattern", None)
        return {"output": output}


def _stop_on_error(next_node: str) -> Callable[[CheckerState], str]:
    def route(state: CheckerState) -> str:
        return END if state.error else next_node

    return route


def _reject_unusable(last_known_tag: str | None) -> TaskError | None:
    if last_known_tag and family_of(last_known_tag) is None:
        return TaskError(
            type="InvalidTask", message=f"{last_known_tag!r} is not a version tag", retryable=False
        )
    return None


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


def _report_new(last: str, new_tags: list[str]) -> Draft:
    count = len(new_tags)
    verb = "release is" if count == 1 else "releases are"
    suggestion = (
        "a ticket for it"
        if count == 1
        else ("one ticket for both" if count == 2 else "one ticket for all")
    )
    return to_room(
        f"reported {plural(count, 'new release')} to the room and suggested one ticket.",
        f"{word(count).capitalize()} {verb} newer than {last}: {tag_list(new_tags)}. "
        f"I suggest {suggestion}.",
    )
