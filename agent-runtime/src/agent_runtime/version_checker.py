from collections.abc import Callable

from agent_runtime.contract import TaskError, TaskOutput, WatchlistInputs
from agent_runtime.events import Draft
from agent_runtime.release_source import CHECKER, DEFAULT_RETRY, ReleaseSource, RetryPolicy
from agent_runtime.summary import Summarizer
from agent_runtime.watchlist import WatchlistChecker

__all__ = ["CHECKER", "VersionChecker"]


class VersionChecker:
    """The agent that reads the sources of the team's watched software and finds what is behind."""

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

    def with_summarizer(self, summarizer: Summarizer) -> VersionChecker:
        return VersionChecker(self._source, summarizer, self._sleep, self._retry)

    def check_watchlist(
        self, inputs: WatchlistInputs, emit: Callable[[Draft], None]
    ) -> TaskOutput | TaskError:
        return self._watchlist.check(inputs, emit)
