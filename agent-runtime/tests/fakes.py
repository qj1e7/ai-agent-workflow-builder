from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from agent_runtime.release_checker import Release, SourceUnavailable


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
    def __init__(self, tags: list[str], failures: list[int | None] | None = None) -> None:
        self.releases = [Release(tag=tag) for tag in tags]
        self.failures = list(failures or [])
        self.calls: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.calls.append(repo)
        if self.failures:
            raise SourceUnavailable(self.failures.pop(0))
        return self.releases


def langgraph_tags() -> list[str]:
    older = [f"1.2.{patch}" for patch in range(13, -1, -1)]
    oldest = [f"1.1.{patch}" for patch in range(12, -1, -1)]
    return ["1.2.16", "1.2.15", "1.2.14", *older, *oldest][:30]
