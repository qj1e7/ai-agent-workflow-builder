from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from platform_api.builder import Builder, Watchlist
from platform_api.builder.models import AddSoftware, WatchlistView
from platform_api.db import Database
from platform_api.orchestration import (
    Given,
    RunSpec,
    RunStarted,
    ScheduleBook,
    SoftwareFacts,
    Standing,
    WatchlistStanding,
    WatchlistTask,
)
from platform_api.shared import Principal, Role, RunId, SoftwareId, UseCaseId, UserId

pytestmark = pytest.mark.anyio

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")


@dataclass
class FakeRuns:
    started: list[tuple[RunSpec, Principal, str]] = field(default_factory=lambda: [])

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.started.append((spec, principal, idempotency_key))
        return RunStarted(RunId("run_1"), created=True)


class NothingLearned:
    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        return WatchlistStanding(
            {
                software_id: Standing(SoftwareFacts(typed, None, None, None), "not_checked")
                for software_id, typed in given.items()
            },
            None,
        )


@pytest.fixture
def runs() -> FakeRuns:
    return FakeRuns()


@pytest.fixture
def watchlist(db: Database) -> Watchlist:
    return Watchlist(db, NothingLearned(), ScheduleBook(db))


@pytest.fixture
def builder(db: Database, runs: FakeRuns, watchlist: Watchlist) -> Builder:
    return Builder(db, runs, watchlist, "http://localhost:8080")


async def watch_langgraph(watchlist: Watchlist) -> WatchlistView:
    added = await watchlist.add(
        ALICE, AddSoftware(name="LangGraph", repo="langchain-ai/langgraph", our_version="1.2.14")
    )
    assert isinstance(added, WatchlistView)
    return added


async def test_the_watchlist_reads_back_as_a_use_case_owned_by_who_added_the_first_software(
    builder: Builder, watchlist: Watchlist
):
    added = await watch_langgraph(watchlist)
    view = await builder.get_use_case(added.use_case_id)
    assert view is not None
    assert (view.version, view.owner, view.template, view.name) == (
        1,
        "alice",
        "software_watchlist",
        "Software watchlist",
    )
    assert view.params == {"ticket_project": "MOCK"}
    assert view.agents == []
    assert [b.key for b in view.plan] == ["read_versions", "approval_gate", "create_tickets"]
    listed = await builder.list_use_cases()
    assert [u.use_case_id for u in listed.use_cases] == [added.use_case_id]


async def test_a_missing_use_case_is_none(builder: Builder):
    assert await builder.get_use_case("uc_nope") is None
    assert await builder.run_spec_for(UseCaseId("uc_nope")) is None


async def test_the_run_spec_snapshots_the_current_version(builder: Builder, watchlist: Watchlist):
    added = await watch_langgraph(watchlist)
    spec = await builder.run_spec_for(UseCaseId(added.use_case_id))
    assert isinstance(spec, RunSpec)
    assert (spec.use_case_id, spec.use_case_version, spec.use_case_name) == (
        added.use_case_id,
        1,
        "Software watchlist",
    )
    assert (spec.owner, spec.workflow) == ("alice", "run")
    assert isinstance(spec.task, WatchlistTask)
    assert [s.name for s in spec.task.software] == ["LangGraph"]
    assert [step.label for step in spec.approval_policy.steps] == ["Team approver"]


async def test_start_run_hands_the_spec_principal_and_key_to_the_starter(
    builder: Builder, runs: FakeRuns, watchlist: Watchlist
):
    added = await watch_langgraph(watchlist)
    started = await builder.start_run(UseCaseId(added.use_case_id), ALICE, "key-1")
    assert started == RunStarted(RunId("run_1"), created=True)
    [(spec, principal, key)] = runs.started
    assert (spec.use_case_id, principal, key) == (added.use_case_id, ALICE, "key-1")


async def test_start_run_on_a_missing_use_case_starts_nothing(builder: Builder, runs: FakeRuns):
    assert await builder.start_run(UseCaseId("uc_nope"), ALICE, "k") is None
    assert runs.started == []
