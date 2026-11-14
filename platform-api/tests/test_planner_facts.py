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
    """`count` workflows, the newest first as the Workflows page lists them: Check {count} first."""
    return [
        STOPPED.model_copy(update={"use_case_id": f"uc_{n}", "name": f"Check {n}"})
        for n in range(count, 0, -1)
    ]


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


async def test_with_few_workflows_there_are_no_other_names():
    facts = await reader(workflows(3)).read(ALICE, "check my workflows")

    assert [w.name for w in facts.workflows or []] == ["Check 3", "Check 2", "Check 1"]
    assert facts.other_workflows is None


async def test_past_the_names_cap_the_section_is_left_out_so_the_planner_says_it_could_not_look():
    facts = await reader(workflows(WORKFLOW_FACTS + OTHER_WORKFLOWS + 1)).read(ALICE, "hi")

    assert (facts.workflows, facts.other_workflows) == (None, None)
