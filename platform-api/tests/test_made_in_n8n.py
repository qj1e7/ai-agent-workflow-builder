"""Workflows made in n8n, set up from Workflows (ENGINE-PLAN E15, ADR 0027, D13), on a fake n8n
that answers as P7 recorded: only someone who can open n8n lists and sets them up; each names its
maker by the n8n account the platform made for them, never by a name; setting one up moves it to
the platform's project and registers what n8n holds there; a safe one runs as its maker's work,
an unsafe one is set up with its writes refused, and its maker and the person who set it up can
never approve its runs."""

import copy
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from platform_api.bootstrap import LoadedWorkflow, record_status
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.made_in_n8n import (
    CHANGED_AS_SET_UP,
    FIX_IN_N8N,
    FIX_N8N_BLOCKS,
    NOT_READ,
    SET_UP_ALREADY,
    MadeInN8n,
)
from platform_api.builder.models import (
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CardView,
)
from platform_api.builder.n8n_holds import CHANGED_AS_TAKEN, NOT_MOVED
from platform_api.builder.n8n_http import SEE_MADE_IN_N8N
from platform_api.builder.versions import authors_from
from platform_api.orchestration import (
    TYPE_OF,
    CardsTask,
    ListedWorkflow,
    N8nWorkflow,
    OwnWorkflow,
    Publisher,
    RanVersion,
    RunSpec,
)
from platform_api.orchestration.cards import read_projects
from platform_api.orchestration.n8n_calls import (
    ExecutionFacts,
    NewRun,
    decide_link,
    refuses_writes,
    version_problem,
)
from platform_api.orchestration.n8n_staff import NO_ACCESS, OFF, Ended, StaffAccounts
from platform_api.orchestration.workflow_check import ERROR_WORKFLOW as ERROR_WORKFLOW_NAME
from platform_api.orchestration.workflow_check import SELF_TEST
from platform_api.shared import UseCaseId, UserId
from tests.fake_n8n import FakeN8n
from tests.support import ALICE, NOW
from tests.test_builder_lifecycle import VALUES
from tests.test_n8n_access import PLATFORM_PROJECT, Staffed, lab, s, staff_for
from tests.test_n8n_builder import ERROR_WORKFLOW, REPO
from tests.test_n8n_lifecycle import Workflows, made

pytestmark = pytest.mark.anyio

__all__ = ["lab", "s"]

CAROL, DANA = UserId("carol"), UserId("dana")
LISTED = "/api/v1/n8n/workflows"
SET_UP = "/api/v1/use-cases/from-n8n"


class Looks(Workflows):
    """n8n, which can be made to not show a workflow once, or to have a member change one in
    their editor just after the platform listed it."""

    blind: int = 0
    edited: tuple[FakeN8n, str] | None = None

    async def look(self, workflow_id: str) -> N8nWorkflow | None:
        if self.blind:
            self.blind -= 1
            raise httpx.ConnectError("n8n did not answer")
        return await super().look(workflow_id)

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]:
        listed = await super().workflows_in(project_id)
        if self.edited is not None:
            n8n, workflow_id = self.edited
            n8n.workflows[workflow_id].update(without_the_yes(n8n.workflows[workflow_id]))
            n8n.edit(workflow_id)
            self.edited = None
        return listed


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
    approver = await s.lab.call("bob", "GET", LISTED, template=LISTED)
    assert (approver.status_code, approver.json()["detail"]) == (403, SEE_MADE_IN_N8N)
    listed = await s.lab.call("alice", "GET", LISTED, template=LISTED)
    assert (listed.status_code, listed.json()["detail"]) == (403, NO_ACCESS)
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
        "fixed_for_you": [],
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
        "fixed_for_you": [],
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
    live = s.n8n.workflows[workflow_id]["activeVersionId"]
    s.n8n.transfer_answers = [500]
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (503, NOT_MOVED)
    assert s.n8n.home_of(workflow_id) == carol_space
    assert s.n8n.workflows[workflow_id]["activeVersionId"] == live, "back on, in her space"
    assert [w["workflow_id"] for w in await waiting(s, "carol")] == [workflow_id]
    assert workflow_id not in await s.staff.makers(), "no note left for a workflow still hers"


async def test_a_draft_changed_to_fail_the_check_as_it_is_set_up_goes_back_to_its_maker(
    s: Staffed, looks: Looks
):
    _, carol_space = await space_of(s, "carol")
    dana = await s.operator("dana")
    await s.member(dana)
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Edited meanwhile"))
    looks.edited = (s.n8n, workflow_id)
    refused = await set_up(s, dana, workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, CHANGED_AS_SET_UP)
    assert s.n8n.home_of(workflow_id) == carol_space, "back in her space, where she can fix it"
    assert (
        await s.own.row("SELECT 1 FROM builder.use_cases WHERE n8n_workflow_id = %s", workflow_id)
        is None
    ), "nothing set up"
    assert workflow_id not in await s.staff.makers()
    [listed] = await waiting(s, dana)
    assert (listed["grade"], listed["can_set_up"]) == ("writes_refused", False)


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


async def test_its_runs_read_and_write_where_its_agent_blocks_say(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Reads MOCK"), carol_n8n)
    created = await set_up(s, "carol", workflow_id)
    assert created.status_code == 201, created.text
    spec = await s.lab.builder.run_spec_for(UseCaseId(created.json()["use_case_id"]))
    assert isinstance(spec, RunSpec) and isinstance(spec.task, CardsTask)
    assert [(run.card.id, dict(run.values)) for run in spec.task.agents] == [
        (VERSION_CHECKER_ID, VALUES)
    ], "no card is pinned, so the task holds what its Agent block runs"
    assert read_projects(spec.task) == {"MOCK"}, "so the agent may read the Jira project it names"
    targets = [dict(b.target) for run in spec.task.agents for b in run.bindings.values()]
    assert targets == [{"project": "MOCK"}], "and its change lands there"


async def test_an_n8n_error_while_noting_never_keeps_an_ended_account(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    s.n8n.make_in(carol_space, named(await laid_out(s), "Left behind"), carol_n8n)
    assert (await s.give("carol", on=False)).status_code == 200
    s.n8n.list_answers = [500]
    assert Ended(CAROL) in await s.settle(), "removing access never waits on the note"
    assert carol_n8n in [user for user, _ in s.n8n.deleted_users]
    assert (await s.person("carol"))["n8n_user_id"] is None


async def test_an_account_delete_n8n_refuses_is_tried_again(s: Staffed):
    carol_n8n, _ = await space_of(s, "carol")
    assert (await s.give("carol", on=False)).status_code == 200
    s.n8n.user_delete_answers = [500]
    assert Ended(CAROL) not in await s.settle()
    assert (await s.person("carol"))["n8n_user_id"] == carol_n8n, "still marked for ending"
    assert Ended(CAROL) in await s.settle(), "the next settle ends it"
    assert carol_n8n in [user for user, _ in s.n8n.deleted_users]


def posting_with(document: dict[str, Any], key: str) -> dict[str, Any]:
    """n8n's own Slack block, after the release check's read, posting with this key."""
    changed = copy.deepcopy(document)
    changed["nodes"].append(
        {
            "id": "slack",
            "name": "Tell Slack",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2.7,
            "position": [900, 200],
            "parameters": {"channelId": {"__rl": True, "value": "C1", "mode": "id"}},
            "credentials": {"slackApi": {"id": key, "name": "Mine"}},
        }
    )
    changed["connections"]["Read release"]["main"][0].append(
        {"node": "Tell Slack", "type": "main", "index": 0}
    )
    return changed


@pytest.mark.parametrize("published", [True, False], ids=["published", "a-draft"])
async def test_a_workflow_naming_a_member_s_own_key_needs_a_fix_before_set_up(
    s: Staffed, published: bool
):
    """In the platform's project n8n lets a workflow use every key there is, so one that names a
    key the platform did not make never moves there, published or not (E15's review)."""
    carol_n8n, space = await space_of(s, "carol")
    hers = s.n8n.add_credential(space, "slackApi")
    document = named(posting_with(await laid_out(s), hers), "Posts with mine")
    workflow_id = s.n8n.make_in(space, document, carol_n8n if published else None)
    [listed] = [w for w in await waiting(s, "carol") if w["workflow_id"] == workflow_id]
    assert (listed["grade"], listed["can_set_up"], listed["why_not"]) == (
        "needs_a_fix",
        False,
        FIX_N8N_BLOCKS,
    )
    assert '"Tell Slack" uses a key the platform did not make.' in listed["findings"]
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, FIX_N8N_BLOCKS)
    assert s.n8n.home_of(workflow_id) == space, "never moved where n8n would run it with any key"


async def test_a_published_one_changed_to_name_a_member_s_key_as_it_moves_goes_back(
    s: Staffed, looks: Looks
):
    carol_n8n, space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(space, named(await laid_out(s), "Morning check"), carol_n8n)
    hers = s.n8n.add_credential(space, "slackApi")
    original = looks.workflows_in

    async def changed_after_listing(project_id: str) -> list[ListedWorkflow]:
        listed = await original(project_id)
        live = s.n8n.workflows[workflow_id]["activeVersionId"]
        version = s.n8n.history[workflow_id][live]
        version.update(posting_with({**version, "settings": {}}, hers))
        return listed

    looks.workflows_in = changed_after_listing  # type: ignore[method-assign]
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, CHANGED_AS_TAKEN)
    assert s.n8n.home_of(workflow_id) == space, "never in the platform's project, live"


async def test_the_platform_s_own_workflows_never_wait_to_be_set_up(s: Staffed):
    """Such as the daily self-test's copy in a member's space (M4), found by the id the platform
    recorded, whatever its name."""
    carol_n8n, space = await space_of(s, "carol")
    copy_id = s.n8n.make_in(space, named(await laid_out(s), "Anything"), carol_n8n)
    record_status(
        s.postgres.owner,
        ready=True,
        detail="d",
        workflows=[
            LoadedWorkflow(ERROR_WORKFLOW_NAME, ERROR_WORKFLOW, True, "sha", PLATFORM_PROJECT),
            LoadedWorkflow(SELF_TEST, copy_id, True, "sha", space),
        ],
    )
    assert copy_id not in {w["workflow_id"] for w in await waiting(s, "carol")}
    refused = await set_up(s, "carol", copy_id)
    assert refused.status_code == 404


async def published_with_draft(s: Staffed, change: Callable[[dict[str, Any]], None]) -> str:
    """Carol's published workflow, as checked, whose draft she then changed and saved."""
    carol_n8n, space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(space, named(await laid_out(s), "Draft differs"), carol_n8n)
    change(s.n8n.workflows[workflow_id])
    s.n8n.edit(workflow_id)
    return workflow_id


async def test_a_published_one_whose_draft_n8n_would_run_unchecked_waits_for_a_fix(s: Staffed):
    """A test run runs the draft, in the platform's project, so the draft is checked too."""

    def deletes(workflow: dict[str, Any]) -> None:
        changed = posting_with(workflow, "any")
        changed["nodes"][-1]["parameters"]["operation"] = "delete"
        workflow.update(nodes=changed["nodes"], connections=changed["connections"])

    workflow_id = await published_with_draft(s, deletes)
    [listed] = [w for w in await waiting(s, "carol") if w["workflow_id"] == workflow_id]
    assert (listed["can_set_up"], listed["why_not"]) == (False, FIX_N8N_BLOCKS)
    assert listed["findings"][-1] == (
        'In its draft: "Tell Slack" does something that is off: message delete.'
    )
    refused = await set_up(s, "carol", workflow_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, FIX_N8N_BLOCKS)


async def test_set_up_puts_the_platform_s_keys_back_on_the_draft_it_takes_in(s: Staffed):
    """Her key in the draft is taken off as it comes in, so no test run could use it."""
    hers = "her-own-key"

    def posts(workflow: dict[str, Any]) -> None:
        changed = posting_with(workflow, hers)
        workflow.update(nodes=changed["nodes"], connections=changed["connections"])

    workflow_id = await published_with_draft(s, posts)
    assert (await set_up(s, "carol", workflow_id)).status_code == 201
    [slack] = [n for n in s.n8n.workflows[workflow_id]["nodes"] if n["name"] == "Tell Slack"]
    assert "credentials" not in slack, "this platform holds no Slack key, so the block has none"


async def test_a_move_that_stops_in_the_platform_s_project_leaves_it_off(s: Staffed):
    """It took her version off to move it. Stuck in the platform's project, where n8n lets it use
    every key there is, it stays off: nothing goes back on there unchecked."""
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Stuck"), carol_n8n)
    s.n8n.transfer_keeps = lambda settings: {}
    s.n8n.after_put = s.n8n.edit
    s.n8n.transfer_answers = [204, 500]
    refused = await set_up(s, "carol", workflow_id)
    assert refused.status_code == 503
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert s.n8n.workflows[workflow_id]["activeVersionId"] is None


SCHEDULE_TRIGGER = "Schedule Trigger"
START = "Start from the Portal"
FIXED_FOR_YOU = [
    "sends its failures to the platform's error workflow",
    "runs it on Singapore time",
    "keeps its test runs",
    "saves its progress",
    "adds Start from the Portal for Run now",
]


async def a_watched_repository(s: Staffed) -> None:
    """A release check that reads REPO, which makes it a place a Read may name."""
    await made(s.own)


def as_the_editor_saves(name: str) -> dict[str, Any]:
    """A Schedule Trigger at 3am, then our Read, as n8n's editor saves a new workflow: each block
    with the id the editor gives it, no parameter it shows at its default (the field, the minute
    and the Read's source), and only the editor's own setting, since a member's editor offers no
    error workflow of the platform's."""
    return {
        "name": name,
        "nodes": [
            {
                "id": "6f0d4c2e-8b1a-4e3f-9c7d-1a2b3c4d5e6f",
                "name": SCHEDULE_TRIGGER,
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.3,
                "position": [0, 0],
                "parameters": {"rule": {"interval": [{"triggerAtHour": 3}]}},
            },
            {
                "id": "0b9e8d7c-6a5f-4e3d-2c1b-a0f9e8d7c6b5",
                "name": "Read",
                "type": TYPE_OF["read"],
                "typeVersion": 1,
                "position": [220, 0],
                "parameters": {"place": REPO},
            },
        ],
        "connections": {
            SCHEDULE_TRIGGER: {"main": [[{"node": "Read", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1"},
    }


async def test_one_saved_as_n8n_s_editor_saves_it_waits_safe_with_what_set_up_fixes(s: Staffed):
    _, carol_space = await space_of(s, "carol")
    await a_watched_repository(s)
    workflow_id = s.n8n.make_in(carol_space, as_the_editor_saves("React read"))
    [found] = await waiting(s, "carol")
    assert (found["workflow_id"], found["grade"], found["findings"]) == (workflow_id, "safe", [])
    assert (found["can_set_up"], found["fixed_for_you"]) == (True, FIXED_FOR_YOU)


async def test_set_up_fixes_its_settings_and_adds_start_from_the_portal_in_n8n(s: Staffed):
    _, carol_space = await space_of(s, "carol")
    await a_watched_repository(s)
    workflow_id = s.n8n.make_in(carol_space, as_the_editor_saves("React read"))
    created = await set_up(s, "carol", workflow_id)
    assert created.status_code == 201, created.text
    assert created.json()["grade"] == "safe"
    held = s.n8n.workflows[workflow_id]
    assert held["settings"] == {
        "executionOrder": "v1",
        "errorWorkflow": ERROR_WORKFLOW,
        "timezone": "Asia/Singapore",
        "saveManualExecutions": True,
        "saveExecutionProgress": True,
    }
    [start] = [n for n in held["nodes"] if n["type"] == TYPE_OF["start"]]
    assert start["name"] == START and start["webhookId"]
    assert held["connections"][START] == held["connections"][SCHEDULE_TRIGGER]
    row = await use_case(s, created.json()["use_case_id"])
    assert (row["draft"], row["n8n_version_id"]) == (True, held["versionId"])

    view = (await s.lab.call("alice", "GET", f"/api/v1/use-cases/{row_id(created)}")).json()
    assert (view["name"], view["state"], view["grade"], view["findings"]) == (
        "React read",
        "draft",
        "safe",
        [],
    )
    assert (view["schedule"]["day"], view["schedule"]["at"]) == ("every_day", "03:00")
    assert view["start_refused"] is None
    assert [(step["name"], step["kind"]) for step in view["plan"]] == [("Read", "agent")]
    test_run = await s.lab.call(
        "alice", "POST", f"/api/v1/use-cases/{row_id(created)}/runs", {"test": True}
    )
    assert test_run.status_code == 201, test_run.text


async def test_a_published_one_keeps_its_own_name_and_shows_when_it_runs(s: Staffed):
    carol_n8n, carol_space = await space_of(s, "carol")
    await a_watched_repository(s)
    workflow_id = s.n8n.make_in(carol_space, as_the_editor_saves("React read"), carol_n8n)
    created = await set_up(s, "carol", workflow_id)
    assert created.status_code == 201, created.text
    held = s.n8n.workflows[workflow_id]
    live = s.n8n.history[workflow_id][held["activeVersionId"]]
    assert START in {n["name"] for n in live["nodes"]}, "the version n8n runs has the start"
    view = (await s.lab.call("alice", "GET", f"/api/v1/use-cases/{row_id(created)}")).json()
    assert (view["name"], view["state"], view["grade"]) == ("React read", "on", "safe")
    at = datetime.fromisoformat(view["next_run_at"]).astimezone(ZoneInfo("Asia/Singapore"))
    assert (at.hour, at.minute) == (3, 0)
    stored = await s.own.row(
        "SELECT name FROM builder.use_case_versions WHERE use_case_id = %s", row_id(created)
    )
    assert stored == {"name": "React read"}


def row_id(created: httpx.Response) -> str:
    use_case_id: str = created.json()["use_case_id"]
    return use_case_id
