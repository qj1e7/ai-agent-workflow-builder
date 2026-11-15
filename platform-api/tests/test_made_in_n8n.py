"""Workflows made in n8n, set up from Workflows (ENGINE-PLAN E15, ADR 0027, D13), on a fake n8n
that answers as P7 recorded: only someone who can open n8n lists and sets them up; each names its
maker by the n8n account the platform made for them, never by a name; setting one up moves it to
the platform's project and registers what n8n holds there; a safe one runs as its maker's work,
an unsafe one is set up with its writes refused, and its maker and the person who set it up can
never approve its runs."""

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from platform_api.builder.made_in_n8n import FIX_IN_N8N, NOT_READ, SET_UP_ALREADY, MadeInN8n
from platform_api.builder.models import (
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CardView,
)
from platform_api.builder.n8n_holds import NOT_MOVED
from platform_api.builder.versions import authors_from
from platform_api.orchestration import (
    TYPE_OF,
    N8nWorkflow,
    OwnWorkflow,
    Publisher,
    RanVersion,
    RunSpec,
)
from platform_api.orchestration.n8n_calls import (
    ExecutionFacts,
    NewRun,
    decide_link,
    refuses_writes,
    version_problem,
)
from platform_api.orchestration.n8n_staff import NO_ACCESS, OFF, Ended, StaffAccounts
from platform_api.shared import UseCaseId, UserId
from tests.support import ALICE, NOW
from tests.test_n8n_access import PLATFORM_PROJECT, Staffed, lab, s, staff_for
from tests.test_n8n_lifecycle import Workflows, made

pytestmark = pytest.mark.anyio

__all__ = ["lab", "s"]

CAROL, DANA = UserId("carol"), UserId("dana")
LISTED = "/api/v1/n8n/workflows"
SET_UP = "/api/v1/use-cases/from-n8n"


class Looks(Workflows):
    """n8n, which can be made to not show a workflow once."""

    blind: int = 0

    async def look(self, workflow_id: str) -> N8nWorkflow | None:
        if self.blind:
            self.blind -= 1
            raise httpx.ConnectError("n8n did not answer")
        return await super().look(workflow_id)


def made_in_n8n(s: Staffed, staff: StaffAccounts, n8n: Workflows) -> MadeInN8n:
    built = MadeInN8n(s.lab.h.db, n8n, staff, s.holding, s.lab.builder.facts)
    s.lab.app.state.made_in_n8n = built
    return built


@pytest.fixture(autouse=True)
async def looks(s: Staffed) -> AsyncIterator[Looks]:
    n8n = Looks(s.n8n, s.lab.h.db)
    made_in_n8n(s, s.staff, n8n)
    yield n8n


async def laid_out(s: Staffed) -> dict[str, Any]:
    """A workflow the Planner laid out from our blocks, which a member copies into their own
    space as their own, as ADR 0027 allows. The original is a workflow the platform runs."""
    use_case_id, workflow_id = await made(s.own, on=True)
    s.n8n.workflows[workflow_id]["shared"] = [
        {"projectId": PLATFORM_PROJECT, "role": "workflow:owner"}
    ]
    document = s.n8n.workflows[workflow_id]
    return copy.deepcopy({key: document[key] for key in ("nodes", "connections", "settings")})


def named(document: dict[str, Any], name: str) -> dict[str, Any]:
    return {**copy.deepcopy(document), "name": name}


def without_the_yes(document: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(document)
    changed["nodes"] = [n for n in changed["nodes"] if n["name"] != "Ask for a yes"]
    changed["connections"].pop("Ask for a yes")
    for exits in changed["connections"].values():
        for targets in exits["main"]:
            for target in targets:
                if target["node"] == "Ask for a yes":
                    target["node"] = "Create ticket"
    return changed


async def space_of(s: Staffed, person: str) -> tuple[str, str]:
    """The person's n8n user id and their own space, once they can open n8n."""
    n8n_user = await s.member(person)
    return n8n_user, s.n8n.personal_project(n8n_user)


async def waiting(s: Staffed, user: str) -> list[dict[str, Any]]:
    answer = await s.lab.call(user, "GET", LISTED, template=LISTED)
    assert answer.status_code == 200, answer.text
    workflows: list[dict[str, Any]] = answer.json()["workflows"]
    return workflows


async def set_up(s: Staffed, user: str, workflow_id: str) -> httpx.Response:
    return await s.lab.call(user, "POST", SET_UP, {"workflow_id": workflow_id}, template=SET_UP)


async def use_case(s: Staffed, use_case_id: str) -> dict[str, Any]:
    row = await s.own.row(
        "SELECT u.draft, u.engine, u.n8n_workflow_id, u.n8n_draft_id, u.made_in_n8n_by, u.owner,"
        " v.n8n_version_id, v.grade, v.findings, v.published_by, v.published_in, v.also,"
        " v.template FROM builder.use_cases u JOIN builder.use_case_versions v"
        " ON v.use_case_id = u.use_case_id AND v.version = 1 WHERE u.use_case_id = %s",
        use_case_id,
    )
    assert row is not None
    return row


def scheduled(workflow_id: str, version_id: str) -> ExecutionFacts:
    """An execution n8n's Schedule Trigger started, read on its first call."""
    return ExecutionFacts(workflow_id, "trigger", None, None, version_id)


async def test_only_someone_who_can_open_n8n_lists_and_sets_up(s: Staffed):
    _, space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(space, named(await laid_out(s), "Carol's check"), "carol-n8n")
    for user in ("bob", "alice"):
        listed = await s.lab.call(user, "GET", LISTED, template=LISTED)
        assert (listed.status_code, listed.json()["detail"]) == (403, NO_ACCESS), user
    refused = await set_up(s, "alice", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (403, NO_ACCESS)
    assert (await set_up(s, "bob", workflow_id)).status_code == 403, "an Approver never"

    made_in_n8n(s, staff_for(s.lab, s.n8n, switched_on=False), Workflows(s.n8n, s.lab.h.db))
    off = await s.lab.call("carol", "GET", LISTED, template=LISTED)
    assert (off.status_code, off.json()["detail"]) == (409, OFF)
    not_now = await set_up(s, "carol", workflow_id)
    assert (not_now.status_code, not_now.json()["detail"]) == (409, OFF)
    assert s.n8n.home_of(workflow_id) == space, "nothing moved"


async def test_each_workflow_in_a_member_s_space_waits_with_its_maker_and_its_grade(s: Staffed):
    document = await laid_out(s)
    carol_n8n, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    published = s.n8n.make_in(carol_space, named(document, "Morning check"), carol_n8n)
    unsafe = s.n8n.make_in(carol_space, named(without_the_yes(document), "Quick fix"))
    s.n8n.archived.add(s.n8n.make_in(carol_space, named(document, "Thrown away")))
    s.n8n.make_in(PLATFORM_PROJECT, named(document, "Nobody noted it"))

    listed = {w["workflow_id"]: w for w in await waiting(s, "carol")}
    assert set(listed) == {published, unsafe}, "not archived, not noted, not one a use case names"
    assert listed[published] == {
        "workflow_id": published,
        "name": "Morning check",
        "made_by": "carol",
        "published": True,
        "grade": "safe",
        "findings": [],
        "can_set_up": True,
        "why_not": None,
    }
    assert listed[unsafe] == {
        "workflow_id": unsafe,
        "name": "Quick fix",
        "made_by": "carol",
        "published": False,
        "grade": "writes_refused",
        "findings": ['"Create ticket" can run without a yes.'],
        "can_set_up": False,
        "why_not": FIX_IN_N8N,
    }
    await s.member(dana)
    assert {w["workflow_id"] for w in await waiting(s, dana)} == {published, unsafe}


async def test_a_published_safe_one_moves_in_and_runs_as_its_maker_s_work(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    await s.member(dana)
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Morning check"), carol_n8n)
    live = s.n8n.workflows[workflow_id]["activeVersionId"]
    published = copy.deepcopy(s.n8n.history[workflow_id][live]["nodes"])
    s.n8n.edit(workflow_id)
    draft = s.n8n.workflows[workflow_id]["versionId"]

    created = await set_up(s, dana, workflow_id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["n8n_workflow_id"], body["grade"]) == (workflow_id, "safe")
    assert "Ask for a yes" in [block["name"] for block in body["blocks"]]
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT, "moved to the platform's project"
    row = await use_case(s, body["use_case_id"])
    assert (row["draft"], row["engine"], row["made_in_n8n_by"], row["owner"]) == (
        False,
        "own",
        "carol",
        dana,
    )
    assert (row["n8n_version_id"], row["n8n_draft_id"]) == (live, draft), "what runs, not an edit"
    stored = await s.own.row(
        "SELECT document FROM builder.use_case_versions WHERE use_case_id = %s",
        body["use_case_id"],
    )
    assert stored is not None and stored["document"]["nodes"] == published
    assert (row["published_by"], row["published_in"]) == ("carol", "n8n")
    assert [a.by for a in authors_from(row["also"])] == [dana]
    view = await s.lab.call("alice", "GET", f"/api/v1/use-cases/{body['use_case_id']}")
    assert (view.json()["state"], view.json()["made_in_n8n_by"]) == ("on", "carol")
    assert view.json()["instruction"] == "Made in n8n by Carol."

    facts = s.lab.builder.facts
    own = await facts.workflow(workflow_id)
    assert isinstance(own, OwnWorkflow) and own.on
    ran = await facts.version(workflow_id, live)
    assert ran == RanVersion("safe", Publisher(CAROL), (Publisher(UserId(dana)),))
    assert version_problem(ran) is None and not refuses_writes(ran)
    link = decide_link(scheduled(workflow_id, live), None, None, None, ran, NOW)
    assert link == NewRun(CAROL, "schedule", (UserId(dana),)), (
        "a scheduled run is Carol's work, and Dana's, so neither approves it"
    )

    assert await waiting(s, "carol") == [], "set up, so it no longer waits"
    again = await set_up(s, dana, workflow_id)
    assert (again.status_code, again.json()["detail"]) == (409, SET_UP_ALREADY)
    assert s.lab.builder.sweep is not None
    assert await s.lab.builder.sweep.sweep() == [], "the sweep finds what was registered"


async def test_an_unsafe_published_one_is_set_up_with_its_writes_refused_and_its_findings(
    s: Staffed,
):
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(
        carol_space, named(without_the_yes(await laid_out(s)), "No yes"), carol_n8n
    )
    created = await set_up(s, "carol", workflow_id)
    assert created.status_code == 201, created.text
    use_case_id = created.json()["use_case_id"]
    view = (await s.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert (view["state"], view["grade"], view["findings"]) == (
        "on",
        "writes_refused",
        ['"Create ticket" can run without a yes.'],
    )
    live = s.n8n.workflows[workflow_id]["activeVersionId"]
    ran = await s.lab.builder.facts.version(workflow_id, live)
    assert ran is not None and refuses_writes(ran), "it never asks for a yes and never writes"
    assert version_problem(ran) is None, "it still reads"
    row = await use_case(s, use_case_id)
    assert (row["published_by"], authors_from(row["also"])) == ("carol", ())


async def test_a_draft_that_fails_the_check_waits_in_its_maker_s_space(s: Staffed):
    _, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(without_the_yes(await laid_out(s)), "Draft"))
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, FIX_IN_N8N)
    assert s.n8n.home_of(workflow_id) == carol_space, "still hers to fix"


async def test_a_safe_draft_is_set_up_as_a_draft_whose_maker_and_setter_join_its_runs(s: Staffed):
    _, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    await s.member(dana)
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Not yet on"))
    draft = s.n8n.workflows[workflow_id]["versionId"]
    created = await set_up(s, dana, workflow_id)
    assert created.status_code == 201, created.text
    use_case_id = created.json()["use_case_id"]
    row = await use_case(s, use_case_id)
    assert (row["draft"], row["n8n_version_id"], row["n8n_draft_id"]) == (True, draft, draft)
    assert (row["published_by"], row["published_in"]) == (None, None)

    turned_on = await s.lab.move("alice", "turn-on", use_case_id)
    assert turned_on.status_code == 200, turned_on.text
    assert s.n8n.workflows[workflow_id]["activeVersionId"] == draft
    ran = await s.lab.builder.facts.version(workflow_id, draft)
    assert ran is not None and ran.publisher == Publisher(UserId("alice"))
    assert set(ran.parties) == {UserId("alice"), CAROL, UserId(dana)}


async def test_the_maker_is_matched_by_id_so_a_shared_name_changes_nothing(s: Staffed):
    document = await laid_out(s)
    carol_n8n, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    dana_n8n, dana_space = await space_of(s, dana)
    taken = (await s.lab.listed())[0]["name"]
    carols = s.n8n.make_in(carol_space, named(document, taken), carol_n8n)
    danas = s.n8n.make_in(dana_space, named(document, taken), dana_n8n)
    s.n8n.change_email(carol_n8n, f"{dana}@example.test")

    makers = {w["workflow_id"]: w["made_by"] for w in await waiting(s, "carol")}
    assert makers == {carols: "carol", danas: dana}, "same name as each other and a use case"
    created = await set_up(s, "carol", danas)
    assert created.status_code == 201, created.text
    row = await use_case(s, created.json()["use_case_id"])
    assert (row["made_in_n8n_by"], row["published_by"]) == (dana, dana)
    assert s.n8n.home_of(carols) == carol_space, "only the one asked for moved"


async def test_an_ended_account_s_workflows_wait_with_the_maker_noted_as_it_ended(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    document = await laid_out(s)
    workflow_id = s.n8n.make_in(carol_space, named(document, "Left behind"), carol_n8n)
    s.n8n.make_in(PLATFORM_PROJECT, named(document, "Nobody noted it"))
    dana = await s.operator("dana")
    await s.member(dana)
    assert (await s.give("carol", on=False)).status_code == 200
    assert Ended(CAROL) in await s.settle()
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT, "n8n moved it as her account ended"

    [listed] = await waiting(s, dana)
    assert (listed["workflow_id"], listed["made_by"]) == (workflow_id, "carol"), "only noted"
    created = await set_up(s, dana, workflow_id)
    assert created.status_code == 201, created.text
    row = await use_case(s, created.json()["use_case_id"])
    assert (row["made_in_n8n_by"], row["published_by"], row["draft"]) == ("carol", "carol", False)
    live = s.n8n.workflows[workflow_id]["activeVersionId"]
    ran = await s.lab.builder.facts.version(workflow_id, live)
    assert ran is not None and not ran.unknown, "n8n emptied the timeline, the note kept her"


async def test_a_move_n8n_refuses_sets_up_nothing(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Stays"), carol_n8n)
    s.n8n.transfer_answers = [500]
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (503, NOT_MOVED)
    assert s.n8n.home_of(workflow_id) == carol_space
    assert [w["workflow_id"] for w in await waiting(s, "carol")] == [workflow_id]


async def test_a_set_up_cut_off_after_the_move_is_finished_by_asking_again(
    s: Staffed, looks: Looks
):
    carol_n8n, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    await s.member(dana)
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Moved"), carol_n8n)
    looks.blind = 1
    cut = await set_up(s, dana, workflow_id)
    assert (cut.status_code, cut.json()["detail"]) == (503, NOT_READ)
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT

    [still] = await waiting(s, dana)
    assert (still["workflow_id"], still["made_by"]) == (workflow_id, "carol"), "noted before"
    finished = await set_up(s, dana, workflow_id)
    assert finished.status_code == 201, finished.text


async def test_when_one_made_in_n8n_runs_is_changed_in_n8n_not_laid_out_again(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Mine"), carol_n8n)
    use_case_id = (await set_up(s, "carol", workflow_id)).json()["use_case_id"]
    before = copy.deepcopy(s.n8n.workflows[workflow_id]["nodes"])
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    refused = await s.lab.call(
        "alice",
        "PUT",
        path,
        {"day": "monday", "at": "07:30", "via": "chat", "expected_version": 1},
        template="/api/v1/use-cases/{use_case_id}/schedule",
    )
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("This workflow was made in n8n")
    assert s.n8n.workflows[workflow_id]["nodes"] == before


async def test_a_long_space_is_read_page_by_page(s: Staffed):
    document = await laid_out(s)
    carol_n8n, carol_space = await space_of(s, "carol")
    made_ids = {
        s.n8n.make_in(carol_space, named(document, f"Check {n}"), carol_n8n) for n in range(5)
    }
    s.n8n.list_page = 2
    assert {w["workflow_id"] for w in await waiting(s, "carol")} == made_ids


async def test_the_grade_is_of_the_version_n8n_runs_not_an_unpublished_edit(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    document = named(await laid_out(s), "Edited after")
    workflow_id = s.n8n.make_in(carol_space, document, carol_n8n)
    s.n8n.workflows[workflow_id].update(without_the_yes(document))
    s.n8n.workflows[workflow_id]["versionId"] = "an-unpublished-edit"
    [listed] = await waiting(s, "carol")
    assert (listed["workflow_id"], listed["grade"], listed["published"]) == (
        workflow_id,
        "safe",
        True,
    )


async def test_its_requests_ask_as_many_approvers_as_the_cards_its_agent_blocks_name(s: Staffed):
    two = CardDefinition(
        name="Ticket raiser",
        purpose="Raises a ticket.",
        inputs=[CardInput(name="Where", kind="jira_project", example="MOCK")],
        blocks=[CardBlock(say="Raise a ticket.", tool="jira.create_ticket")],
        approvals=[CardApprovalView(tool="jira.create_ticket", approvers=2)],
    )
    card = await s.lab.builder.create_card(ALICE, two)
    assert isinstance(card, CardView)
    document = await laid_out(s)
    for node in document["nodes"]:
        if node["type"] == TYPE_OF["agent"]:
            node["parameters"]["agent"] = card.card_id
            node["parameters"]["inputs"] = {"input": [{"name": "Where", "value": "MOCK"}]}
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(document, "Two yeses"), carol_n8n)
    created = await set_up(s, "carol", workflow_id)
    assert (created.status_code, created.json()["grade"]) == (201, "safe"), created.text
    spec = await s.lab.builder.run_spec_for(UseCaseId(created.json()["use_case_id"]))
    assert isinstance(spec, RunSpec)
    assert len(spec.approval_policy.steps) == 2, "the card asks two Approvers, one after the other"
