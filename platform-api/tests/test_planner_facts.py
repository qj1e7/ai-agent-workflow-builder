import json

import pytest

from platform_api.builder.home import HomeOut
from platform_api.builder.models import UseCaseList, UseCaseView, WatchlistView
from platform_api.builder.planner_facts import PlannerFactsReader
from platform_api.orchestration import OTHER_WORKFLOWS, WORKFLOW_FACTS, PlannerFacts
from tests.support import ALICE, FIXTURES

pytestmark = pytest.mark.anyio

STOPPED = UseCaseView.model_validate(
    json.loads((FIXTURES / "builder" / "use-case.stopped.json").read_text())
)


def workflows(count: int) -> list[UseCaseView]:
    """`count` workflows, the newest first as the Workflows page lists them: Check {count} first.
    Each one's last run stopped."""
    return [
        STOPPED.model_copy(update={"use_case_id": f"uc_{n}", "name": f"Check {n}"})
        for n in range(count, 0, -1)
    ]


def healthy(count: int) -> list[UseCaseView]:
    """`count` workflows that need nobody: on, safe, and never run."""
    return [u.model_copy(update={"last_run": None, "grade": "safe"}) for u in workflows(count)]


class Listed:
    def __init__(self, use_cases: list[UseCaseView]) -> None:
        self.use_cases = use_cases

    async def list_use_cases(self) -> UseCaseList:
        return UseCaseList(use_cases=self.use_cases)


class NoWatchlist:
    async def view(self) -> WatchlistView | None:
        return None


class UnreadHome:
    async def for_person(self, viewer: object) -> HomeOut:
        raise RuntimeError("not read in these tests")


def reader(use_cases: list[UseCaseView]) -> PlannerFactsReader:
    return PlannerFactsReader(NoWatchlist(), Listed(use_cases), UnreadHome())


def names_of(facts: PlannerFacts) -> list[str]:
    return [w.name for w in facts.workflows or []] + (facts.other_workflows or [])


async def test_the_planner_knows_every_workflows_name_past_the_detail_cap():
    listed = workflows(120)

    facts = await reader(listed).read(ALICE, "what needs me?")

    assert sorted(names_of(facts)) == sorted(u.name for u in listed), "all 120 names"
    assert facts.workflows is not None and len(facts.workflows) == WORKFLOW_FACTS
    assert [w.name for w in facts.workflows] == [u.name for u in listed[:WORKFLOW_FACTS]]
    assert facts.other_workflows == [u.name for u in listed[WORKFLOW_FACTS:]]
    assert {w.last_run for w in facts.workflows} == {"Stopped"}


async def test_a_workflow_the_request_names_gets_its_last_run_whatever_its_place():
    listed = workflows(120)

    facts = await reader(listed).read(ALICE, "Why did check 3 stop? And pause Check 12")

    assert facts.workflows is not None
    assert [w.name for w in facts.workflows[:2]] == ["Check 12", "Check 3"]
    assert facts.workflows[0].last_run == "Stopped"
    assert facts.other_workflows is not None
    assert "Check 3" not in facts.other_workflows and "Check 12" not in facts.other_workflows
    assert sorted(names_of(facts)) == sorted(u.name for u in listed), "still every name once"


async def test_a_word_inside_a_longer_name_is_not_that_workflow():
    listed = workflows(60)

    facts = await reader(listed).read(ALICE, "pause Check 1")

    assert facts.workflows is not None
    assert [w.name for w in facts.workflows[:2]] == ["Check 1", "Check 60"], "not Check 10 to 19"


async def test_with_few_workflows_the_facts_are_as_before_whatever_the_request_names():
    facts = await reader(workflows(3)).read(ALICE, "pause Check 1")

    assert [w.name for w in facts.workflows or []] == ["Check 3", "Check 2", "Check 1"]
    assert facts.other_workflows is None


async def test_a_name_too_long_for_the_facts_leaves_out_the_workflows_alone():
    listed = workflows(60)
    listed[-1] = listed[-1].model_copy(update={"name": "x" * 81})

    facts = await reader(listed).read(ALICE, "what needs me?")

    assert (facts.workflows, facts.other_workflows) == (None, None)


async def test_past_the_names_cap_the_named_workflow_survives_and_the_rest_are_counted():
    listed = workflows(WORKFLOW_FACTS + OTHER_WORKFLOWS + 7)

    facts = await reader(listed).read(ALICE, "pause Check 1")

    assert facts.workflows is not None and facts.workflows[0].name == "Check 1"
    assert len(facts.workflows) == WORKFLOW_FACTS
    assert facts.other_workflows is not None and len(facts.other_workflows) == OTHER_WORKFLOWS
    assert facts.left_out_workflows == 7, "the names not sent are counted, never dropped silently"


async def test_with_every_name_sent_nothing_is_counted_as_left_out():
    facts = await reader(workflows(120)).read(ALICE, "what needs me?")

    assert facts.left_out_workflows is None


async def test_workflows_that_need_someone_get_their_last_run_before_the_newest():
    listed = healthy(120)
    stopped = STOPPED.model_copy(update={"use_case_id": "uc_old_stop", "name": "Old stop"})
    paused = listed[90].model_copy(update={"use_case_id": "uc_paused", "name": "Paused one"})
    paused = paused.model_copy(update={"state": "paused"})
    unsafe = listed[100].model_copy(update={"use_case_id": "uc_unsafe", "name": "Unsafe one"})
    unsafe = unsafe.model_copy(update={"grade": "needs_a_fix"})
    listed += [stopped, paused, unsafe]

    facts = await reader(listed).read(ALICE, "did anything stop?")

    assert facts.workflows is not None
    assert [w.name for w in facts.workflows[:3]] == ["Old stop", "Paused one", "Unsafe one"]
    assert facts.workflows[0].last_run == "Stopped"
    assert facts.other_workflows is not None and "Old stop" not in facts.other_workflows


async def test_with_50_workflows_or_fewer_the_runtime_gets_the_facts_it_got_before():
    """The runtime refuses fields it doesn't know, and the two deploy in one apply but not in one
    instant, so a runtime from before other_workflows still takes what is sent then."""
    facts = await reader(workflows(3)).read(ALICE, "what needs me?")

    sent = facts.model_dump(mode="json")

    assert set(sent) == {"watchlist", "workflows", "needs_you", "watchlist_schedule"}


async def test_past_50_the_names_and_the_count_are_sent():
    facts = await reader(workflows(WORKFLOW_FACTS + OTHER_WORKFLOWS + 1)).read(ALICE, "hi")

    sent = facts.model_dump(mode="json")

    assert len(sent["other_workflows"]) == OTHER_WORKFLOWS
    assert sent["left_out_workflows"] == 1


class Watched:
    def __init__(self, view: WatchlistView) -> None:
        self._view = view

    async def view(self) -> WatchlistView | None:
        return self._view


@pytest.mark.parametrize("state", ["on", "paused"])
async def test_the_facts_name_the_project_the_watchlist_raises_its_tickets_in(state: str):
    view = WatchlistView.model_validate(
        json.loads((FIXTURES / "watchlist" / "statuses.json").read_text())
    ).model_copy(update={"state": state})

    facts = await PlannerFactsReader(Watched(view), Listed([]), UnreadHome()).read(ALICE, "hi")

    assert facts.watchlist_project == "MOCK"
