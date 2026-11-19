from collections.abc import Callable, Mapping

from agent_runtime.contract import TaskOutput, WatchlistInputs
from agent_runtime.events import Draft
from agent_runtime.release_source import (
    CHECKER,
    DEFAULT_RETRY,
    MovableSource,
    ReleaseSource,
    RetryPolicy,
)
from agent_runtime.summary import Summarizer
from agent_runtime.vulnerabilities import AdvisoryReader
from agent_runtime.watchlist import NothingChecked, WatchlistChecker

__all__ = ["CHECKER", "VersionChecker"]


class VersionChecker:
    def __init__(
        self,
        source: MovableSource,
        summarizer: Summarizer,
        sleep: Callable[[float], None],
        retry: RetryPolicy = DEFAULT_RETRY,
        registries: Mapping[str, ReleaseSource] | None = None,
        advisories: AdvisoryReader | None = None,
    ) -> None:
        self._source = source
        self._summarizer = summarizer
        self._sleep = sleep
        self._retry = retry
        self._registries = registries
        self._advisories = advisories
        self._watchlist = WatchlistChecker(
            source, summarizer, sleep, retry, registries=registries, advisories=advisories
        )

    def with_summarizer(self, summarizer: Summarizer) -> VersionChecker:
        return VersionChecker(
            self._source,
            summarizer,
            self._sleep,
            self._retry,
            registries=self._registries,
            advisories=self._advisories,
        )

    def check_watchlist(
        self, inputs: WatchlistInputs, emit: Callable[[Draft], None]
    ) -> TaskOutput | NothingChecked:
        return self._watchlist.check(inputs, emit)
