"""n8n access per person, staff accounts, Open in n8n and Take back (ENGINE-PLAN 2.9, D14, D15,
D17, E7), on a fake n8n that answers as P7 recorded: only an Operator who is no Approver holds the
flag; nothing opens while staff access is off or the allow list unproven; the account follows the
flag, its password link is shown only to its person and never logged; a move keeps the workflow's
settings; and a publish by a member is matched by the n8n user id the platform stored."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import psycopg
import pytest

from platform_api.bootstrap import LoadedWorkflow, record_status
from platform_api.builder import Builder, Home, TeamRequests
from platform_api.builder.n8n_holds import (
    MOVE_GRACE,
    NO_SPACE,
    STRANDED,
    STRAYS_EVERY,
    Holding,
)
from platform_api.builder.n8n_view import InN8nViews
from platform_api.builder.planner import HERE_IN_N8N, WHICH_IN_N8N, AnswerIn, PlannerFront
from platform_api.orchestration import Publisher
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n import N8nExecutions
from platform_api.orchestration.n8n_run_view import RunsInN8n
from platform_api.orchestration.n8n_staff import (
    INVITE_LIFE,
    NO_ACCESS,
    NO_ADDRESS,
    NOT_READY,
    OFF,
    SET_PASSWORD,
    Ended,
    Made,
    Reissued,
    StaffAccounts,
)
from platform_api.orchestration.workflow_check import ERROR_WORKFLOW as ERROR_WORKFLOW_NAME
from platform_api.shared import Principal, Role, UserId
from tests.conftest import PostgresUrls
from tests.fake_n8n import OWNER_ID, FakeN8n
from tests.support import NOW
from tests.test_builder_lifecycle import Lab, ModelConnected
from tests.test_connections import Rig
from tests.test_home import NoTeams
from tests.test_n8n_api import api_for
from tests.test_n8n_builder import ERROR_WORKFLOW, WRITES, N8nLab, lab
from tests.test_n8n_lifecycle import Workflows, made, version_row
from tests.test_people_http import model_settings_for

pytestmark = pytest.mark.anyio

__all__ = ["lab"]

PLATFORM_PROJECT = "proj-platform"
EDITOR = "https://n8n.example"
CAROL = UserId("carol")
APPROVERS = "Approvers can't have n8n access. An Operator with n8n access can open it."


@dataclass
class Staffed:
    own: N8nLab
    staff: StaffAccounts
    holding: Holding
    postgres: PostgresUrls

    @property
    def n8n(self) -> FakeN8n:
        return self.own.n8n

    @property
    def lab(self) -> Lab:
        return self.own.lab

    async def call(self, user: str, method: str, path: str, body: Any = None) -> httpx.Response:
        return await self.lab.call(user, method, path, body)

    async def give(self, person: str, on: bool = True, by: str = "alice") -> httpx.Response:
        path = f"/api/v1/people/{person}/n8n-access"
        return await self.call(by, "PUT", path, {"n8n_access": on})

    async def settle(self) -> list[object]:
        await self.holding.release()
        return list(await self.staff.settle(self.holding.holds))

    def bootstrapped(self, ready: bool, project: str | None = PLATFORM_PROJECT) -> None:
        loaded = LoadedWorkflow(ERROR_WORKFLOW_NAME, ERROR_WORKFLOW, True, "sha", project)
        record_status(self.postgres.owner, ready=ready, detail="d", workflows=[loaded])

    async def person(self, person: str) -> dict[str, Any]:
        async with self.lab.h.db.connection("orchestration") as conn:
            row = await (
                await conn.execute(
                    "SELECT n8n_access, n8n_user_id, n8n_invite FROM orchestration.people"
                    " WHERE id = %s",
                    (person,),
                )
            ).fetchone()
        assert row is not None
        return dict(row)

    async def member(self, person: str = "carol") -> str:
        """Gives the person n8n access; the platform makes the account and they set their
        password."""
        assert (await self.give(person)).status_code == 200
        await self.settle()
        user_id = (await self.person(person))["n8n_user_id"]
        self.n8n.accept(user_id)
        return str(user_id)

    async def operator(self, name: str) -> str:
        body = {"email": f"{name}@example.test", "display": name.title(), "operator": True}
        added = await self.call("alice", "POST", "/api/v1/people", body)
        assert added.status_code == 201, added.text
        return str(added.json()["id"])

    async def open(self, user: str, use_case_id: str) -> httpx.Response:
        return await self.call(user, "POST", f"/api/v1/use-cases/{use_case_id}/open-in-n8n")

    async def take_back(self, user: str, use_case_id: str) -> httpx.Response:
        return await self.call(user, "POST", f"/api/v1/use-cases/{use_case_id}/take-back")

    async def held_by(self, use_case_id: str) -> str | None:
        row = await self.own.row(
            "SELECT held_by FROM builder.use_cases WHERE use_case_id = %s", use_case_id
        )
        assert row is not None
        return row["held_by"]


def staff_for(
    lab: Lab, n8n: FakeN8n, switched_on: bool = True, editor_url: str | None = EDITOR
) -> StaffAccounts:
    return StaffAccounts(
        lab.h.db, api_for(n8n), KeyBox("test-secret-not-real"), switched_on, editor_url
    )


@pytest.fixture
async def s(lab: Lab, postgres: PostgresUrls) -> AsyncIterator[Staffed]:
    n8n = FakeN8n()
    n8n.projects.append(
        {"id": PLATFORM_PROJECT, "type": "personal", "name": "Platform", "creatorId": OWNER_ID}
    )
    staff = staff_for(lab, n8n)
    workflows = Workflows(n8n, lab.h.db)
    holding = Holding(lab.h.db, workflows, staff)
    lab.builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=workflows,
        writes=WRITES,
        accounts=staff,
        holding=holding,
    )
    lab.app.state.builder = lab.builder
    lab.app.state.staff = staff
    lab.app.state.model_settings = model_settings_for(lab.h.db, lab.app.state.people)
    runs = RunsInN8n(lab.h.db, N8nExecutions(api_for(n8n)))
    lab.app.state.in_n8n = InN8nViews(lab.h.db, holding, staff, runs, EDITOR)
    staffed = Staffed(N8nLab(lab, n8n), staff, holding, postgres)
    staffed.bootstrapped(ready=True)
    yield staffed


async def version_rows(s: Staffed, use_case_id: str) -> list[int]:
    async with s.lab.h.db.connection("builder") as conn:
        rows = await (
            await conn.execute(
                "SELECT version FROM builder.use_case_versions WHERE use_case_id = %s",
                (use_case_id,),
            )
        ).fetchall()
    return [row["version"] for row in rows]


async def held(s: Staffed) -> tuple[str, str]:
    """A workflow that is on, in the platform's project, held by nobody."""
    use_case_id, workflow_id = await made(s.own, on=True)
    s.n8n.workflows[workflow_id]["shared"] = [
        {"projectId": PLATFORM_PROJECT, "role": "workflow:owner"}
    ]
    return use_case_id, workflow_id


async def test_only_an_operator_who_is_no_approver_may_hold_n8n_access(s: Staffed):
    given = await s.give("carol")
    assert given.status_code == 200, given.text
    assert (given.json()["n8n_access"], given.json()["n8n_account"]) == (True, "none")
    for approver in ("bob", "alice"):
        refused = await s.give(approver)
        assert refused.status_code == 409
        assert refused.json()["refusal"] == "n8n_operators_only"
    assert (await s.give("carol", by="bob")).status_code == 403, "only an Operator gives it"
    me = (await s.call("carol", "GET", "/api/v1/me")).json()
    assert me["n8n_access"] is True


async def test_gaining_the_approver_role_ends_n8n_access_takes_back_and_ends_the_account(
    s: Staffed,
):
    n8n_user = await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200
    asked = await s.call("alice", "POST", "/api/v1/people/carol/approver")
    assert asked.status_code == 202
    confirmation = asked.json()["pending_approver"]["confirmation_id"]
    pending = (await s.call("bob", "GET", "/api/v1/confirmations")).json()["confirmations"]
    [mine] = [c for c in pending if c["confirmation_id"] == confirmation]
    decided = await s.call(
        "bob",
        "POST",
        f"/api/v1/confirmations/{confirmation}/decisions",
        {"verdict": "confirm", "digest": mine["digest"]},
    )
    assert decided.status_code == 201, decided.text
    people = (await s.call("alice", "GET", "/api/v1/people")).json()["people"]
    carol = next(p for p in people if p["id"] == "carol")
    assert (carol["approver"], carol["n8n_access"]) == (True, False)
    history = (await s.call("alice", "GET", "/api/v1/settings/history")).json()["changes"]
    assert history[0]["summary"].endswith(
        "Carol's n8n access ended, because Approvers can't have it."
    )

    assert await s.staff.settle(s.holding.holds) == [], "never ended while they hold one"
    assert await s.settle() == [Ended(CAROL)]
    assert await s.held_by(use_case_id) is None
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT, "taken back before the account ends"
    assert s.n8n.deleted_users == [(n8n_user, PLATFORM_PROJECT)], "nothing deleted with it"
    assert (await s.person("carol"))["n8n_user_id"] is None


async def test_approvers_get_403_on_open_in_n8n(s: Staffed):
    use_case_id, workflow_id = await held(s)
    assert (await s.open("bob", use_case_id)).status_code == 403
    refused = await s.open("alice", use_case_id)
    assert (refused.status_code, refused.json()["detail"]) == (403, APPROVERS)
    mine = (await s.call("bob", "GET", "/api/v1/me/n8n")).json()
    assert (mine["can_open"], mine["why_not"]) == (False, APPROVERS)
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT


async def test_open_in_n8n_is_409_while_staff_access_is_off_or_the_allow_list_unproven(
    s: Staffed,
):
    await s.member()
    use_case_id, workflow_id = await held(s)
    s.holding = Holding(s.lab.h.db, Workflows(s.n8n, s.lab.h.db), staff_for(s.lab, s.n8n, False))
    s.lab.builder.holding = s.holding
    off = await s.open("carol", use_case_id)
    assert (off.status_code, off.json()["detail"]) == (409, OFF)

    s.lab.builder.holding = s.holding = Holding(s.lab.h.db, Workflows(s.n8n, s.lab.h.db), s.staff)
    s.bootstrapped(ready=False)
    unproven = await s.open("carol", use_case_id)
    assert (unproven.status_code, unproven.json()["detail"]) == (409, NOT_READY)
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT

    dana = await s.operator("dana")
    assert (await s.give(dana)).status_code == 200
    made_now = [m for m in await s.settle() if isinstance(m, Made)]
    assert made_now == [], "no staff account is made while the allow list is unproven"
    assert (await s.person(dana))["n8n_user_id"] is None


async def test_unproven_allow_list_takes_every_held_workflow_back(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200
    s.bootstrapped(ready=False)
    await s.settle()
    assert await s.held_by(use_case_id) is None
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert (await s.person("carol"))["n8n_user_id"] is not None, "the account stays"


async def test_take_back_by_the_holder_and_by_another_operator_with_n8n_access(s: Staffed):
    await s.member()
    dana = await s.operator("dana")
    await s.member(dana)
    erin = await s.operator("erin")
    use_case_id, workflow_id = await held(s)

    opened = await s.open("carol", use_case_id)
    assert opened.status_code == 200, opened.text
    assert (opened.json()["held_by"], opened.json()["editor_url"]) == (
        "carol",
        f"{EDITOR}/workflow/{workflow_id}",
    )
    member_space = s.n8n.personal_project((await s.person("carol"))["n8n_user_id"])
    assert s.n8n.home_of(workflow_id) == member_space
    assert (await s.open("carol", use_case_id)).json()["held_by"] == "carol", "again: no change"
    other = await s.open(dana, use_case_id)
    assert (other.status_code, other.json()["detail"]) == (
        409,
        f"Carol has it open in n8n since {NOW.astimezone(s.holding._zone):%H:%M}.",
    )

    refused = await s.take_back(erin, use_case_id)
    assert refused.status_code == 403, "an Operator without n8n access cannot"
    taken = await s.take_back(dana, use_case_id)
    assert (taken.status_code, taken.json()["held_by"]) == (200, None)
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT

    assert (await s.open("carol", use_case_id)).status_code == 200
    assert (await s.take_back("carol", use_case_id)).status_code == 200
    assert (await s.take_back("carol", use_case_id)).json()["held_by"] is None, "again: no change"
    holds = await s.own.row(
        "SELECT count(*) AS n, count(*) FILTER (WHERE taken_back_by = %s) AS by_dana"
        " FROM builder.n8n_holds WHERE use_case_id = %s",
        dana,
        use_case_id,
    )
    assert holds == {"n": 2, "by_dana": 1}


async def test_a_move_that_loses_the_settings_puts_them_back(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    laid_out = dict(s.n8n.workflows[workflow_id]["settings"])
    assert laid_out["errorWorkflow"] == ERROR_WORKFLOW
    s.n8n.transfer_keeps = lambda settings: {}
    assert (await s.open("carol", use_case_id)).status_code == 200
    assert s.n8n.workflows[workflow_id]["settings"] == laid_out
    assert (await s.take_back("carol", use_case_id)).status_code == 200
    assert s.n8n.workflows[workflow_id]["settings"] == laid_out


async def test_a_failed_move_that_cannot_go_back_is_stranded_until_release_moves_it(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    s.n8n.transfer_keeps = lambda settings: {}
    s.n8n.after_put = s.n8n.edit
    s.n8n.transfer_answers = [204, 500]
    opened = await s.open("carol", use_case_id)
    assert (opened.status_code, opened.json()["detail"]) == (503, STRANDED)
    assert await s.held_by(use_case_id) is None
    assert s.n8n.home_of(workflow_id) != PLATFORM_PROJECT, "it sits in Carol's space"
    assert (await s.lab.move("alice", "pause", use_case_id)).status_code == 200, "pause still"
    resumed = await s.lab.move("alice", "resume", use_case_id)
    assert (resumed.status_code, resumed.json()["detail"]) == (409, STRANDED)

    s.n8n.transfer_keeps = lambda settings: settings
    s.n8n.after_put = None
    await s.settle()
    assert s.n8n.home_of(workflow_id) != PLATFORM_PROJECT, "left to its own Open for a while"
    s.lab.h.advance(MOVE_GRACE)
    s.n8n.transfer_answers = [500]
    await s.settle()
    assert s.n8n.home_of(workflow_id) != PLATFORM_PROJECT, "a refused retry keeps it stranded"
    await s.settle()
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert (await s.lab.move("alice", "resume", use_case_id)).status_code == 200


async def test_a_hold_that_fails_to_save_after_the_move_leaves_a_mark_the_settle_loop_follows(
    s: Staffed,
):
    await s.member()
    use_case_id, workflow_id = await held(s)
    async with s.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "INSERT INTO builder.n8n_holds (use_case_id, held_by, opened_at) VALUES (%s, 'x', %s)",
            (use_case_id, NOW),
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        await s.open("carol", use_case_id)
    assert await s.held_by(use_case_id) is None
    assert s.n8n.home_of(workflow_id) != PLATFORM_PROJECT, "n8n moved it before the save failed"
    assert (await s.lab.move("alice", "pause", use_case_id)).status_code == 200
    resumed = await s.lab.move("alice", "resume", use_case_id)
    assert (resumed.status_code, resumed.json()["detail"]) == (409, STRANDED)
    s.lab.h.advance(MOVE_GRACE)
    await s.settle()
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT


async def test_a_workflow_found_outside_the_platform_s_project_with_nobody_holding_it_comes_back(
    s: Staffed,
):
    n8n_user = await s.member()
    use_case_id, workflow_id = await held(s)
    member_space = s.n8n.personal_project(n8n_user)
    s.n8n.workflows[workflow_id]["shared"] = [{"projectId": member_space, "role": "workflow:owner"}]
    s.lab.h.advance(STRAYS_EVERY)
    await s.settle()
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert await s.held_by(use_case_id) is None


async def test_an_account_n8n_lost_is_forgotten_and_made_again(s: Staffed):
    lost = await s.member()
    assert (await s.call("carol", "GET", "/api/v1/me/n8n")).json()["account"] == "ready"
    use_case_id, workflow_id = await held(s)
    s.n8n.users.pop(lost)
    s.n8n.projects = [p for p in s.n8n.projects if p.get("creatorId") != lost]
    refused = await s.open("carol", use_case_id)
    assert (refused.status_code, refused.json()["detail"]) == (503, NO_SPACE)
    assert (await s.person("carol"))["n8n_user_id"] is None, "forgotten, never stuck"
    assert s.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert await s.settle() == [Made(CAROL)]
    s.n8n.accept((await s.person("carol"))["n8n_user_id"])
    assert (await s.open("carol", use_case_id)).status_code == 200


async def test_an_unused_password_link_is_replaced_after_a_week(s: Staffed):
    assert (await s.give("carol")).status_code == 200
    assert await s.settle() == [Made(CAROL)]
    first = (await s.call("carol", "GET", "/api/v1/me/n8n")).json()["set_password_url"]
    old_user = (await s.person("carol"))["n8n_user_id"]
    s.lab.h.advance(INVITE_LIFE - timedelta(minutes=1))
    assert await s.settle() == [], "a link younger than a week stays"
    s.lab.h.advance(timedelta(minutes=1))
    assert await s.settle() == [Reissued(CAROL)]
    assert s.n8n.deleted_users == [(old_user, PLATFORM_PROJECT)], "the old link opens nothing"
    second = (await s.call("carol", "GET", "/api/v1/me/n8n")).json()["set_password_url"]
    assert second and second != first
    theirs = (await s.call("alice", "GET", "/api/v1/me/n8n")).json()
    assert theirs["set_password_url"] is None, "shown to Carol alone"


async def test_a_move_whose_answer_was_lost_is_read_back_not_taken_as_failed(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    s.n8n.transfers_lost = 1
    opened = await s.open("carol", use_case_id)
    assert (opened.status_code, opened.json()["held_by"]) == (200, "carol")
    assert s.n8n.home_of(workflow_id) == s.n8n.personal_project(
        (await s.person("carol"))["n8n_user_id"]
    ), "n8n moved it, so the platform holds it on record"


async def test_the_sweep_names_a_publish_by_the_stored_user_id_after_an_email_change(s: Staffed):
    n8n_user = await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200
    s.n8n.change_email(n8n_user, "someone-else@example.test")

    def later(workflow: dict[str, Any]) -> None:
        workflow["nodes"][0]["notes"] = "changed by Carol in n8n"

    s.n8n.publish_as(workflow_id, n8n_user, later)
    assert s.lab.builder.sweep is not None
    assert len(await s.lab.builder.sweep.sweep()) == 1
    second = await version_row(s.own, use_case_id, 2)
    assert (second["published_by"], second["published_in"]) == ("carol", "n8n")
    ran = await s.lab.builder.facts.version(workflow_id, second["n8n_version_id"])
    assert ran is not None and ran.publisher == Publisher(CAROL)
    assert CAROL in ran.parties, "a run of their version is their work, so never theirs to approve"


async def test_a_publish_by_an_account_since_ended_is_kept_with_nobody_guessed(s: Staffed):
    n8n_user = await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200

    def later(workflow: dict[str, Any]) -> None:
        workflow["nodes"][0]["notes"] = "changed by Carol in n8n"

    s.n8n.publish_as(workflow_id, n8n_user, later)
    assert (await s.give("carol", on=False)).status_code == 200
    assert await s.settle() == [Ended(CAROL)]
    assert s.lab.builder.sweep is not None
    assert len(await s.lab.builder.sweep.sweep()) == 1
    second = await version_row(s.own, use_case_id, 2)
    assert (second["published_by"], second["published_in"]) == (None, "n8n")


async def test_a_delete_takes_the_workflow_back_before_it_ends_the_hold(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200
    s.bootstrapped(ready=True, project=None)
    refused = await s.lab.move("alice", "delete", use_case_id)
    assert refused.status_code == 503, "n8n could not take it back, so nothing was deleted"
    assert await s.held_by(use_case_id) == "carol"
    assert s.n8n.home_of(workflow_id) != PLATFORM_PROJECT

    s.bootstrapped(ready=True)
    s.n8n.calls.clear()
    assert (await s.lab.move("alice", "delete", use_case_id)).status_code == 200
    assert await s.held_by(use_case_id) is None
    assert not await s.holding.holds(CAROL)
    moved = s.n8n.calls.index(f"PUT /api/v1/workflows/{workflow_id}/transfer")
    archived = s.n8n.calls.index(f"POST /api/v1/workflows/{workflow_id}/archive")
    assert moved < archived, "back in the platform's project before n8n removes it"


async def test_platform_writes_wait_while_someone_holds_the_workflow(s: Staffed):
    n8n_user = await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200

    def later(workflow: dict[str, Any]) -> None:
        workflow["nodes"][0]["notes"] = "changed by Carol in n8n"

    s.n8n.publish_as(workflow_id, n8n_user, later)
    assert s.lab.builder.sweep is not None
    assert len(await s.lab.builder.sweep.sweep()) == 1
    held_words = f"Carol has it open in n8n since {NOW.astimezone(s.holding._zone):%H:%M}."
    take_it_back = f"{held_words} Take it back to change it here."
    ask_for_it = f"{held_words} Ask Carol, or anyone with n8n access, to take it back."
    for path in (
        f"/api/v1/use-cases/{use_case_id}/versions/1/rollback",
        f"/api/v1/use-cases/{use_case_id}/add-the-yes-back",
    ):
        refused = await s.call("alice", "POST", path, {"via": "page", "in_use": 2})
        assert (refused.status_code, refused.json()["detail"]) == (409, ask_for_it), (
            f"{path}: Alice has no n8n access, so Alice can't take it back"
        )
        mine = await s.call("carol", "POST", path, {"via": "page", "in_use": 2})
        assert (mine.status_code, mine.json()["detail"]) == (409, take_it_back), (
            f"{path}: Carol holds it, so they can"
        )
    assert (await s.lab.move("alice", "pause", use_case_id)).status_code == 200, "pause still"
    resumed = await s.lab.move("alice", "resume", use_case_id)
    assert (resumed.status_code, resumed.json()["detail"]) == (409, ask_for_it)
    assert len(await version_rows(s, use_case_id)) == 2, "nothing was published over their work"

    assert (await s.take_back("carol", use_case_id)).status_code == 200
    assert (await s.lab.move("alice", "resume", use_case_id)).status_code == 200
    rolled = await s.call(
        "alice",
        "POST",
        f"/api/v1/use-cases/{use_case_id}/versions/1/rollback",
        {"via": "page", "in_use": 2},
    )
    assert rolled.status_code == 200, rolled.text


async def test_a_schedule_edit_is_refused_while_someone_holds_the_workflow(s: Staffed):
    await s.member()
    use_case_id, _ = await held(s)
    assert (await s.open("carol", use_case_id)).status_code == 200
    saved = await s.call(
        "alice",
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        {"day": "monday", "at": "07:30", "via": "page", "expected_version": 1},
    )
    assert saved.status_code == 409
    assert saved.json()["detail"].startswith("Carol has it open in n8n since ")
    assert saved.json()["detail"].endswith("Ask Carol, or anyone with n8n access, to take it back.")
    hers = await s.call(
        "carol",
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        {"day": "monday", "at": "07:30", "via": "page", "expected_version": 1},
    )
    assert hers.status_code == 409
    assert hers.json()["detail"].endswith("Take it back to change it here."), "they hold it"


async def test_my_n8n_shows_the_password_link_only_to_its_person_and_only_until_used(
    s: Staffed, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG)
    assert (await s.give("carol")).status_code == 200
    assert await s.settle() == [Made(CAROL)]
    stored = await s.person("carol")
    mine = await s.call("carol", "GET", "/api/v1/me/n8n")
    assert mine.headers["cache-control"] == "no-store"
    link = mine.json()["set_password_url"]
    assert link.startswith(f"{EDITOR}/signup?token=secret-"), "where people open n8n"
    [token] = parse_qs(urlsplit(link).query)["token"]
    assert mine.json() | {"set_password_url": None} == {
        "access": True,
        "account": "invited",
        "set_password_url": None,
        "can_open": False,
        "why_not": SET_PASSWORD,
        "editor_url": None,
    }
    assert link not in stored["n8n_invite"], "kept sealed"
    theirs = (await s.call("alice", "GET", "/api/v1/me/n8n")).json()
    assert (theirs["access"], theirs["set_password_url"]) == (False, None)
    people = (await s.call("alice", "GET", "/api/v1/people")).json()
    assert link not in str(people)

    s.n8n.accept(stored["n8n_user_id"])
    after = (await s.call("carol", "GET", "/api/v1/me/n8n")).json()
    assert (after["account"], after["set_password_url"], after["can_open"]) == (
        "ready",
        None,
        True,
    )
    assert after["editor_url"] == EDITOR
    assert (await s.person("carol"))["n8n_invite"] is None, "forgotten once used"
    assert token not in caplog.text, "never logged"


@pytest.mark.parametrize(
    ("from_n8n", "editor_url", "shown"),
    [
        (
            "http://n8n:5678/signup?token=abc",
            "http://localhost:5678",
            "http://localhost:5678/signup?token=abc",
        ),
        (
            "http://n8n:5678/signup?token=a.B-c_~%2Bd%3D",
            "https://example.test/n8n",
            "https://example.test/n8n/signup?token=a.B-c_~%2Bd%3D",
        ),
        (
            "http://n8n:5678/n8n/signup?token=abc",
            "https://example.test/n8n",
            "https://example.test/n8n/signup?token=abc",
        ),
    ],
    ids=["local", "path prefix", "n8n under the same prefix"],
)
async def test_the_password_link_points_where_people_open_n8n(
    s: Staffed, from_n8n: str, editor_url: str, shown: str
):
    """n8n builds the link from its own address, which inside the platform's network is one a
    browser can't reach."""
    s.n8n.invite_link = from_n8n
    s.lab.app.state.staff = staff_for(s.lab, s.n8n, editor_url=editor_url)
    assert (await s.give("carol")).status_code == 200
    assert await s.settle() == [Made(CAROL)]
    mine = (await s.call("carol", "GET", "/api/v1/me/n8n")).json()
    assert mine["set_password_url"] == shown


async def test_with_no_editor_address_no_link_is_shown_and_the_words_say_who_to_ask(s: Staffed):
    """n8n's own link would open nothing, so none is shown rather than a dead one."""
    no_address = staff_for(s.lab, s.n8n, editor_url=None)
    s.lab.app.state.staff = no_address
    s.lab.builder.holding = Holding(s.lab.h.db, Workflows(s.n8n, s.lab.h.db), no_address)
    use_case_id, _ = await held(s)
    assert (await s.give("carol")).status_code == 200
    assert await s.settle() == [Made(CAROL)]
    mine = (await s.call("carol", "GET", "/api/v1/me/n8n")).json()
    assert (mine["account"], mine["set_password_url"], mine["why_not"]) == (
        "invited",
        None,
        NO_ADDRESS,
    )
    refused = await s.open("carol", use_case_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, NO_ADDRESS), "same words"


async def test_an_account_follows_the_flag_and_is_never_taken_by_email(s: Staffed):
    s.n8n.users["n8n-user-made-by-hand"] = {"email": "carol@example.test", "isPending": False}
    assert (await s.give("carol")).status_code == 200
    assert await s.settle() == []
    assert (await s.person("carol"))["n8n_user_id"] is None, "an account it did not make"

    s.n8n.users.clear()
    assert await s.settle() == [Made(CAROL)]
    n8n_user = (await s.person("carol"))["n8n_user_id"]
    assert await s.staff.people_by_n8n_user() == {n8n_user: CAROL}
    assert await s.settle() == [], "settling again changes nothing"
    assert (await s.give("carol", on=False)).status_code == 200
    assert await s.settle() == [Ended(CAROL)]
    assert s.n8n.deleted_users == [(n8n_user, PLATFORM_PROJECT)]
    assert await s.staff.people_by_n8n_user() == {}


async def test_the_in_n8n_views_are_for_people_with_n8n_access(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    assert (await s.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/n8n")).status_code == (
        403
    )
    view = (await s.call("carol", "GET", f"/api/v1/use-cases/{use_case_id}/n8n")).json()
    document = s.n8n.workflows[workflow_id]
    assert [n["name"] for n in view["nodes"]] == [n["name"] for n in document["nodes"]]
    assert {(e["source"], e["target"]) for e in view["edges"]} == {
        (source, target["node"])
        for source, outputs in document["connections"].items()
        for targets in outputs["main"]
        for target in targets or []
    }
    kinds = {n["name"]: n["kind"] for n in view["nodes"]}
    assert kinds["Ask for a yes"] == "ask"
    assert (view["workflow_id"], view["version"], view["holder"], view["can_open"]) == (
        workflow_id,
        1,
        None,
        True,
    )
    assert (view["published_by"], view["published_by_name"]) == ("alice", "Alice")
    versions = (await s.call("carol", "GET", f"/api/v1/use-cases/{use_case_id}/versions")).json()
    assert view["published_at"] == versions["versions"][0]["at"], "the versions list's time"
    assert view["editor_url"] is None, "the editor opens it only for the person who holds it"
    assert (await s.open("carol", use_case_id)).status_code == 200
    view = (await s.call("carol", "GET", f"/api/v1/use-cases/{use_case_id}/n8n")).json()
    assert (view["holder"]["id"], view["holder"]["name"]) == ("carol", "Carol")
    assert view["editor_url"] == f"{EDITOR}/workflow/{workflow_id}"


async def test_a_run_in_n8n_has_each_block_s_state_from_its_calls_then_n8n_s_record(s: Staffed):
    await s.member()
    use_case_id, workflow_id = await held(s)
    version_id = s.n8n.workflows[workflow_id]["activeVersionId"]
    async with s.lab.h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec,"
            " started_by, started_at, updated_at, state, state_data)"
            " VALUES ('run_n8n', %s, 'k', '{}', 'carol', %s, %s, 'AwaitingApproval', '{}')",
            (use_case_id, NOW, NOW),
        )
        await uow.conn.execute(
            "INSERT INTO orchestration.executions (execution_id, run_id, n8n_workflow_id, mode,"
            " version_id, linked_at) VALUES ('901', 'run_n8n', %s, 'webhook', %s, %s)",
            (workflow_id, version_id, NOW),
        )
        for node, kind in (("Version checker", "agent"), ("Ask for a yes", "ask")):
            await uow.conn.execute(
                "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind,"
                " content_hash, attempts, outcome, call_id, claimed_at, answer, answered_at)"
                " VALUES ('901', %s, 'run_n8n', %s, 'h', 1, %s, %s, %s, '{}', %s)",
                (node, kind, "answered", f"call-{node}", NOW, NOW),
            )
    waiting = (await s.call("carol", "GET", "/api/v1/runs/run_n8n/n8n")).json()
    assert waiting["states"] == {
        "Version checker": "done",
        "Newer?": "done",
        "Ask for a yes": "waiting",
    }, "the IF never calls the platform, so the yes waiting after it says it ran"
    assert (waiting["from_n8n"], waiting["n8n_version_id"]) == (False, version_id)
    assert "Nothing to change" in [n["name"] for n in waiting["nodes"]]
    blocks = {block["name"]: block for block in waiting["blocks"]}
    assert set(blocks) == {n["name"] for n in waiting["nodes"]} - {"About this workflow"}
    assert {(exit["exit"], exit["to"]) for exit in blocks["Newer?"]["next"]} == {
        ("true", "Ask for a yes"),
        ("false", "Nothing to change"),
    }

    async with s.lab.h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.runs SET state = 'Rejected' WHERE run_id = 'run_n8n'"
        )
    s.n8n.execution("901", "success", workflow_id=workflow_id)
    s.n8n.executions["901"]["data"]["resultData"]["runData"] = {
        "Start from the Portal": [{"executionStatus": "success"}],
        "Version checker": [{"executionStatus": "success"}],
        "Ask for a yes": [{"executionStatus": "error"}],
    }
    ended = (await s.call("carol", "GET", "/api/v1/runs/run_n8n/n8n")).json()
    assert ended["from_n8n"] is True
    assert ended["states"] == {
        "Start from the Portal": "done",
        "Version checker": "done",
        "Ask for a yes": "failed",
    }, "n8n's own record says what ran, so nothing is guessed on top of it"
    assert (await s.call("bob", "GET", "/api/v1/runs/run_n8n/n8n")).status_code == 403


async def test_the_planner_answers_who_may_open_n8n(s: Staffed):
    use_case_id, _ = await held(s)
    unused = cast(Any, None)
    front = PlannerFront(unused, s.lab.builder, unused, unused, unused, unused, s.staff)
    name = (await s.lab.builder.get_use_case(use_case_id)).name  # type: ignore[union-attr]

    async def asked(person: Principal, text: str) -> Any:
        return await front.answer(AnswerIn(text=text), person)

    bob = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
    no_access = await asked(bob, f"open {name} in n8n")
    assert (no_access.answer, no_access.said, no_access.can_open) == ("n8n", APPROVERS, False)
    dana = Principal(UserId(await s.operator("dana")), frozenset({Role.OPERATOR}), "Dana")
    assert (await asked(dana, f"open {name} in n8n")).said == NO_ACCESS
    carol = Principal(CAROL, frozenset({Role.OPERATOR}), "Carol", n8n_access=True)
    assert (await s.give("carol")).status_code == 200
    s.bootstrapped(ready=False)
    assert (await asked(carol, "show me N8N")).said == NOT_READY
    s.bootstrapped(ready=True)
    await s.settle()
    s.n8n.accept((await s.person("carol"))["n8n_user_id"])
    here = await asked(carol, f"Open {name} in n8n please")
    assert (here.said, here.can_open, here.use_case_id) == (HERE_IN_N8N, True, use_case_id)
    which = await asked(carol, "open n8n")
    assert (which.said, which.use_case_id) == (WHICH_IN_N8N, None)


async def test_everyone_sees_who_has_a_workflow_open_in_n8n_by_their_name(s: Staffed):
    dana = await s.operator("dana")
    await s.member(dana)
    use_case_id, _ = await held(s)
    assert (await s.open(dana, use_case_id)).status_code == 200
    for person in ("alice", "bob", "carol"):
        shown = (await s.call(person, "GET", f"/api/v1/use-cases/{use_case_id}")).json()
        listed = (await s.call(person, "GET", "/api/v1/use-cases")).json()["use_cases"]
        [row] = [u for u in listed if u["use_case_id"] == use_case_id]
        assert row["held_in_n8n"] == shown["held_in_n8n"], "the page and the list say one thing"
        assert (shown["held_in_n8n"]["id"], shown["held_in_n8n"]["name"]) == (dana, "Dana")
    assert (await s.take_back(dana, use_case_id)).status_code == 200
    view = (await s.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert view["held_in_n8n"] is None


async def held_by_nobody_listed(s: Staffed, use_case_id: str) -> str:
    """A hold by someone whose row is no longer on the People list."""
    gone = "per_01JB8GONE"
    async with s.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_cases SET held_by = %s, held_since = %s WHERE use_case_id = %s",
            (gone, uow.now, use_case_id),
        )
    return gone


async def test_a_holder_nobody_can_name_is_a_colleague_never_an_id(s: Staffed):
    await s.member()
    use_case_id, _ = await held(s)
    gone = await held_by_nobody_listed(s, use_case_id)
    shown = (await s.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert (shown["held_in_n8n"]["id"], shown["held_in_n8n"]["name"]) == (gone, "a colleague")
    in_n8n = (await s.call("carol", "GET", f"/api/v1/use-cases/{use_case_id}/n8n")).json()
    assert in_n8n["holder"]["name"] == "a colleague"
    saved = await s.call(
        "alice",
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        {"day": "monday", "at": "07:30", "via": "page", "expected_version": 1},
    )
    assert saved.status_code == 409
    assert saved.json()["detail"].startswith("A colleague has it open in n8n since ")
    assert saved.json()["detail"].endswith(
        "Ask a colleague, or anyone with n8n access, to take it back."
    )


async def test_home_names_whoever_published_in_n8n_from_the_people_list(s: Staffed):
    dana = await s.operator("dana")
    dana_in_n8n = await s.member(dana)
    use_case_id, workflow_id = await held(s)
    assert (await s.open(dana, use_case_id)).status_code == 200

    def renamed(workflow: dict[str, Any]) -> None:
        workflow["nodes"][-1]["name"] = "Raise the ticket"

    s.n8n.publish_as(workflow_id, dana_in_n8n, renamed)
    assert s.lab.builder.sweep is not None
    assert len(await s.lab.builder.sweep.sweep()) == 1
    h = s.lab.h
    requests = TeamRequests(h.db, NoTeams(), h.orchestrator, h.log, "http://localhost:8000")
    state = s.lab.app.state
    state.home = Home(
        s.lab.builder,
        h.orchestrator,
        state.people,
        requests,
        Rig(h.db).connections,
        state.watchlist,
    )
    home = (await s.call("alice", "GET", "/api/v1/home")).json()
    [card] = [c for c in home["changed_in_n8n"] if c["use_case_id"] == use_case_id]
    assert (card["by"], card["by_name"]) == (dana, "Dana")
