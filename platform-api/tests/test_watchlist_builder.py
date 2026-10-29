from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from platform_api.builder import Builder, Watchlist
from platform_api.builder.models import AddSoftware, WatchlistView
from platform_api.builder.service import NothingToCheck
from platform_api.builder.watchlist import (
    NoSuchSoftware,
    RepoAlreadyWatched,
    RepoWatchedAgain,
    WatchlistFull,
)
from platform_api.db import Database
from platform_api.orchestration import (
    Binding,
    Checked,
    CouldNotCheck,
    FromFirstCheck,
    FromTicketDone,
    Given,
    LastCheck,
    OpenTicket,
    PendingTicket,
    RunSpec,
    RunStarted,
    ScheduleBook,
    SoftwareFacts,
    SoftwareSource,
    Standing,
    WatchedSoftware,
    WatchlistStanding,
    WatchlistTask,
)
from platform_api.orchestration.watch import status_of
from platform_api.shared import ApprovalId, Principal, ProposalId, RunId, SoftwareId, UseCaseId
from tests.support import ALICE, CAROL, NOW

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
LATER = NOW + timedelta(hours=1)


def standing_of(facts: SoftwareFacts) -> Standing:
    return Standing(facts, status_of(facts))


@dataclass
class FakeFacts:
    """Orchestration's answer, by software id. Unknown software has no facts yet."""

    known: dict[SoftwareId, SoftwareFacts] = field(default_factory=lambda: {})
    last_check: LastCheck | None = None
    asked: list[tuple[UseCaseId, Mapping[SoftwareId, Given | None]]] = field(
        default_factory=lambda: []
    )

    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        self.asked.append((use_case_id, dict(given)))
        software = {
            software_id: standing_of(
                self.known.get(software_id, SoftwareFacts(typed, None, None, None))
            )
            for software_id, typed in given.items()
        }
        return WatchlistStanding(software, self.last_check)


@dataclass
class FakeRuns:
    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        return RunStarted(RunId("run_1"), created=True)


@pytest.fixture
def facts() -> FakeFacts:
    return FakeFacts()


@pytest.fixture
def watchlist(db: Database, facts: FakeFacts) -> Watchlist:
    return Watchlist(db, facts, ScheduleBook(db))


@pytest.fixture
def builder(db: Database, watchlist: Watchlist) -> Builder:
    return Builder(db, FakeRuns(), watchlist, "http://localhost:8080")


def software(name: str, repo: str, our_version: str | None = None) -> AddSoftware:
    return AddSoftware(name=name, repo=repo, our_version=our_version)


LANGGRAPH = software("LangGraph", "langchain-ai/langgraph", "1.2.14")
REDIS = software("Redis", "redis/redis")


async def added(watchlist: Watchlist, body: AddSoftware, by: Principal = ALICE) -> WatchlistView:
    result = await watchlist.add(by, body)
    assert isinstance(result, WatchlistView)
    return result


def ids(view: WatchlistView) -> dict[str, SoftwareId]:
    return {row.name: row.id for row in view.software}


async def test_there_is_no_watchlist_until_the_first_software_is_added(
    watchlist: Watchlist, facts: FakeFacts
):
    assert await watchlist.view() is None
    assert facts.asked == []


async def test_the_first_add_makes_the_watchlist_use_case_with_the_software_in_version_one(
    watchlist: Watchlist, builder: Builder
):
    view = await added(watchlist, LANGGRAPH, by=CAROL)
    assert view.use_case_id.startswith("uc_")
    assert (view.version, view.ticket_project, view.last_check) == (1, "MOCK", None)
    assert view.schedule is not None
    assert (view.schedule.day, view.schedule.at, view.schedule.time_zone) == (
        "monday",
        "09:00",
        "Asia/Singapore",
    )
    assert (view.schedule.owner, view.schedule.owner_name) == ("carol", "Carol")
    [row] = view.software
    assert row.id.startswith("sw_") and len(row.id) == 29
    assert (row.name, row.source.ref, row.source.kind) == (
        "LangGraph",
        "langchain-ai/langgraph",
        "github",
    )
    assert row.source.url == "https://github.com/langchain-ai/langgraph/releases"
    assert (row.our_version, row.status, row.added_by) == ("1.2.14", "not_checked", "carol")
    assert row.our_version_source is not None
    assert (row.our_version_source.kind, row.our_version_source.at) == ("given", row.added_at)
    assert (row.newest_version, row.checked_at, row.problem) == (None, None, None)
    assert (row.open_ticket, row.approval_id) == (None, None)

    use_case = await builder.get_use_case(view.use_case_id)
    assert use_case is not None
    assert (use_case.template, use_case.name, use_case.version, use_case.owner) == (
        "software_watchlist",
        "Software watchlist",
        1,
        "carol",
    )
    assert use_case.params == {"ticket_project": "MOCK"}
    assert use_case.instruction.startswith("Check the team's watched software")
    assert await watchlist.view() == view


async def test_adding_and_removing_make_new_versions_and_keep_the_rest_of_the_list(
    watchlist: Watchlist, builder: Builder, facts: FakeFacts
):
    first = await added(watchlist, LANGGRAPH)
    second = await added(watchlist, REDIS)
    assert (first.version, second.version) == (1, 2)
    assert second.use_case_id == first.use_case_id
    assert [row.name for row in second.software] == ["LangGraph", "Redis"]
    langgraph, redis = ids(second)["LangGraph"], ids(second)["Redis"]
    assert ids(first)["LangGraph"] == langgraph

    third = await watchlist.remove(langgraph)
    assert isinstance(third, WatchlistView)
    assert third.version == 3
    assert [row.id for row in third.software] == [redis]
    redis_row = third.software[0]
    assert (redis_row.our_version, redis_row.our_version_source) == (None, None)

    use_case = await builder.get_use_case(first.use_case_id)
    assert use_case is not None and use_case.version == 3
    assert facts.asked[-1] == (UseCaseId(first.use_case_id), {redis: None})
    assert facts.asked[-2][1] == {
        langgraph: Given("1.2.14", first.software[0].added_at),
        redis: None,
    }


async def test_a_repository_is_watched_once_whatever_its_case(watchlist: Watchlist):
    first = await added(watchlist, LANGGRAPH)
    again = await watchlist.add(ALICE, software("LangGraph again", "LangChain-AI/LangGraph"))
    assert again == RepoAlreadyWatched("LangChain-AI/LangGraph")
    view = await watchlist.view()
    assert view is not None and view.version == first.version == 1


async def test_removing_software_that_is_not_listed_changes_nothing(watchlist: Watchlist):
    assert await watchlist.remove(SoftwareId("sw_nope")) == NoSuchSoftware(SoftwareId("sw_nope"))
    view = await added(watchlist, LANGGRAPH)
    assert await watchlist.remove(SoftwareId("sw_nope")) == NoSuchSoftware(SoftwareId("sw_nope"))
    assert await watchlist.view() == view


async def test_restoring_removed_software_lists_it_again_as_it_was(
    watchlist: Watchlist, facts: FakeFacts
):
    first = await added(watchlist, LANGGRAPH)
    both = await added(watchlist, REDIS)
    langgraph, redis = ids(both)["LangGraph"], ids(both)["Redis"]
    facts.known = {
        langgraph: SoftwareFacts(Given("1.2.14", NOW), Checked(RUN, LATER, "1.2.16"), None, None)
    }
    shown = await watchlist.view()
    assert shown is not None
    before = next(row for row in shown.software if row.id == langgraph)
    removed = await watchlist.remove(langgraph)
    assert isinstance(removed, WatchlistView) and removed.version == 3

    restored = await watchlist.restore(langgraph)
    assert isinstance(restored, WatchlistView)
    assert restored.version == 4
    assert next(row for row in restored.software if row.id == langgraph) == before
    assert before.newest_version == "1.2.16", "what the platform learned comes back with it"
    assert facts.asked[-1][1] == {
        redis: None,
        langgraph: Given("1.2.14", first.software[0].added_at),
    }
    assert await watchlist.restore(langgraph) == restored, "a repeat restore changes nothing"
    again = await watchlist.view()
    assert again is not None and again.version == 4


async def test_restoring_software_that_was_never_listed_changes_nothing(watchlist: Watchlist):
    nope = SoftwareId("sw_nope")
    assert await watchlist.restore(nope) == NoSuchSoftware(nope)
    view = await added(watchlist, LANGGRAPH)
    assert await watchlist.restore(nope) == NoSuchSoftware(nope)
    assert await watchlist.view() == view


async def test_a_repository_added_again_since_its_removal_cannot_be_restored(
    watchlist: Watchlist,
):
    first = await added(watchlist, LANGGRAPH)
    old = first.software[0].id
    await watchlist.remove(old)
    again = await added(watchlist, software("LangGraph", "LangChain-AI/LangGraph"))
    assert ids(again)["LangGraph"] != old
    assert await watchlist.restore(old) == RepoWatchedAgain("langchain-ai/langgraph")
    assert await watchlist.view() == again


async def test_restoring_into_a_full_list_is_refused(watchlist: Watchlist):
    for n in range(100):
        await added(watchlist, software(f"Tool {n}", f"owner/tool-{n}"))
    full = await watchlist.view()
    assert full is not None
    gone = ids(full)["Tool 0"]
    await watchlist.remove(gone)
    refilled = await added(watchlist, software("One more", "owner/one-more"))
    assert await watchlist.restore(gone) == WatchlistFull(100)
    assert await watchlist.view() == refilled


async def test_the_list_holds_a_hundred_software_at_most(watchlist: Watchlist):
    for n in range(100):
        await added(watchlist, software(f"Tool {n}", f"owner/tool-{n}"))
    assert await watchlist.add(ALICE, software("One more", "owner/one-more")) == WatchlistFull(100)
    view = await watchlist.view()
    assert view is not None and (view.version, len(view.software)) == (100, 100)


async def listed(watchlist: Watchlist, *names: str) -> dict[str, SoftwareId]:
    view = None
    for name in names:
        view = await added(watchlist, software(name, f"owner/{name.lower()}", "1.0.0"))
    assert view is not None
    return ids(view)


async def test_software_that_needs_a_person_comes_first_then_by_name(
    watchlist: Watchlist, facts: FakeFacts
):
    by_name = await listed(watchlist, "Zed", "Yarn", "Xerox", "Wget", "Vim", "Uno", "Tmux", "ant")
    given = Given("1.0.0", NOW)
    pending = PendingTicket(ProposalId("prp_1"), 0, "2.0.0", ApprovalId("apr_1"))
    facts.known = {
        by_name["Zed"]: SoftwareFacts(given, Checked(RUN, LATER, "1.0.0"), None, None),
        by_name["Yarn"]: SoftwareFacts(given, Checked(RUN, LATER, "2.0.0"), None, None),
        by_name["Xerox"]: SoftwareFacts(given, Checked(RUN, LATER, "2.0.0"), pending, None),
        by_name["Wget"]: SoftwareFacts(given, CouldNotCheck(RUN, LATER, "GitHub 404"), None, None),
        by_name["Vim"]: SoftwareFacts(given, None, None, None),
        by_name["Uno"]: SoftwareFacts(
            given, Checked(RUN, LATER, "2.0.0"), None, OpenTicket("MOCK-1", "2.0.0")
        ),
        by_name["ant"]: SoftwareFacts(given, Checked(RUN, LATER, "1.0.0"), None, None),
        by_name["Tmux"]: SoftwareFacts(given, Checked(RUN, LATER, "1.0.0"), None, None),
    }
    view = await watchlist.view()
    assert view is not None
    assert [(row.name, row.status) for row in view.software] == [
        ("Wget", "cant_check"),
        ("Yarn", "behind"),
        ("Xerox", "awaiting_approval"),
        ("Uno", "ticket_open"),
        ("Vim", "not_checked"),
        ("ant", "up_to_date"),
        ("Tmux", "up_to_date"),
        ("Zed", "up_to_date"),
    ]


async def test_the_view_shows_each_fact_the_platform_learned(
    watchlist: Watchlist, facts: FakeFacts
):
    by_name = await listed(watchlist, "Alpha", "Beta", "Gamma")
    facts.known = {
        by_name["Alpha"]: SoftwareFacts(
            FromTicketDone("2.0.0", LATER, "MOCK-7"), Checked(RUN, LATER, "2.0.0"), None, None
        ),
        by_name["Beta"]: SoftwareFacts(
            FromFirstCheck("1.5.0", NOW),
            Checked(RUN, LATER, "1.6.0"),
            PendingTicket(ProposalId("prp_1"), 0, "1.6.0", None),
            None,
        ),
        by_name["Gamma"]: SoftwareFacts(
            Given("1.0.0", NOW),
            CouldNotCheck(RUN, LATER, "GitHub answered 404 Not Found."),
            None,
            OpenTicket("MOCK-9", "1.1.0"),
        ),
    }
    facts.last_check = LastCheck(RUN, "succeeded", NOW)
    view = await watchlist.view()
    assert view is not None
    assert view.last_check is not None
    assert (view.last_check.run_id, view.last_check.state, view.last_check.started_at) == (
        RUN,
        "succeeded",
        NOW,
    )
    rows = {row.name: row for row in view.software}
    alpha, beta, gamma = rows["Alpha"], rows["Beta"], rows["Gamma"]
    assert (alpha.our_version, alpha.status, alpha.newest_version, alpha.checked_at) == (
        "2.0.0",
        "up_to_date",
        "2.0.0",
        LATER,
    )
    assert alpha.our_version_source is not None
    assert (alpha.our_version_source.kind, alpha.our_version_source.ticket) == (
        "ticket_done",
        "MOCK-7",
    )
    assert alpha.our_version_source.at == LATER
    assert (beta.our_version, beta.status, beta.approval_id) == ("1.5.0", "awaiting_approval", None)
    assert beta.our_version_source is not None and beta.our_version_source.kind == "first_check"
    assert (gamma.status, gamma.problem, gamma.newest_version, gamma.checked_at) == (
        "cant_check",
        "GitHub answered 404 Not Found.",
        None,
        LATER,
    )
    assert gamma.open_ticket == "MOCK-9"


async def test_a_check_carries_our_version_the_open_ticket_and_the_waiting_approval(
    watchlist: Watchlist, builder: Builder, facts: FakeFacts
):
    by_name = await listed(watchlist, "Alpha", "Beta", "Gamma")
    view = await watchlist.view()
    assert view is not None
    facts.known = {
        by_name["Alpha"]: SoftwareFacts(
            FromTicketDone("2.0.0", LATER, "MOCK-7"), Checked(RUN, LATER, "2.0.0"), None, None
        ),
        by_name["Beta"]: SoftwareFacts(
            Given("1.0.0", NOW),
            Checked(RUN, LATER, "1.6.0"),
            PendingTicket(ProposalId("prp_1"), 0, "1.6.0", ApprovalId("apr_1")),
            None,
        ),
        by_name["Gamma"]: SoftwareFacts(
            Given("1.0.0", NOW), Checked(RUN, LATER, "1.1.0"), None, OpenTicket("MOCK-9", "1.1.0")
        ),
    }
    spec = await builder.run_spec_for(UseCaseId(view.use_case_id))
    assert isinstance(spec, RunSpec)
    assert (spec.use_case_version, spec.use_case_name, spec.owner, spec.workflow) == (
        3,
        "Software watchlist",
        "alice",
        "run",
    )
    assert spec.bindings == {"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})}
    assert spec.task == WatchlistTask(
        tag_pattern=r"^\d+\.\d+\.\d+$",
        software=(
            WatchedSoftware(
                by_name["Alpha"], "Alpha", SoftwareSource("owner/alpha"), "2.0.0", None, False
            ),
            WatchedSoftware(
                by_name["Beta"], "Beta", SoftwareSource("owner/beta"), "1.0.0", None, True
            ),
            WatchedSoftware(
                by_name["Gamma"], "Gamma", SoftwareSource("owner/gamma"), "1.0.0", "MOCK-9", False
            ),
        ),
    )
    assert isinstance(await builder.start_run(UseCaseId(view.use_case_id), ALICE, "k"), RunStarted)


async def test_an_emptied_watchlist_has_nothing_to_check(watchlist: Watchlist, builder: Builder):
    view = await added(watchlist, LANGGRAPH)
    await watchlist.remove(view.software[0].id)
    assert await builder.run_spec_for(UseCaseId(view.use_case_id)) == NothingToCheck()
    assert await builder.start_run(UseCaseId(view.use_case_id), ALICE, "k") == NothingToCheck()
