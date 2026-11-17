"""Drafted workflows, end to end in platform-api with the drafter, n8n and Teams faked (ADR 0051,
build step 6): the words go to the drafter unchanged, code lays the plan out and checks it, a
revision is sent only when nothing is needed and nothing is flagged, any Approver who is not a
party approves that exact digest, and only that digest is set up as a Draft."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import pytest

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder.drafted_settings import ANY_APPROVER, APPROVERS
from platform_api.builder.drafted_workflows import (
    CHANGED,
    KEY_PASTED,
    DraftedWorkflows,
)
from platform_api.db import Database
from platform_api.orchestration import (
    CanOpen,
    DrafterFacts,
    KnownOptions,
    ListedWorkflow,
    ModelProblem,
    N8nWorkflow,
    NoModel,
    NoN8nAccess,
    RuntimeDown,
    SavedDraft,
    StaffAccess,
    WorkflowDrafted,
    WorkflowDraftResult,
    WorkflowNotDrafted,
    WorkflowPlan,
    workflow_digest,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.orchestration.slack_channels import ChannelList
from platform_api.shared import TEAM_TIME_ZONE, UserId
from tests.conftest import PostgresUrls
from tests.support import LOCAL_ENV
from tests.test_drafted_layout import release_check
from tests.test_setup_approvals import Channel

pytestmark = pytest.mark.anyio

ERROR_WORKFLOW = "wfErrorReporter01"
WORDS = (
    "Draft an n8n workflow that every Monday at 9:00 checks langchain-ai/langgraph for a new "
    "release and raises a ticket in MOCK"
)


@dataclass
class Drafter:
    answers: list[WorkflowDraftResult | NoModel | RuntimeDown] = field(
        default_factory=lambda: [drafted(release_check())]
    )
    asked: list[tuple[str, DrafterFacts, WorkflowPlan | None]] = field(
        default_factory=list[tuple[str, DrafterFacts, WorkflowPlan | None]]
    )

    async def draft(
        self, words: str, facts: DrafterFacts, current: WorkflowPlan | None
    ) -> WorkflowDraftResult | NoModel | RuntimeDown:
        self.asked.append((words, facts, current))
        return self.answers.pop(0) if self.answers else drafted(release_check())


def drafted(plan: WorkflowPlan) -> WorkflowDrafted:
    return WorkflowDrafted(plan=plan, catalogue="n8nio/n8n:2.42.6@sha256:x", sent_back=[], turns=3)


@dataclass
class N8n:
    saved: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    """Every workflow n8n created, in order."""
    sent: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    """Every document the platform sent n8n to create, as it was sent."""
    held: dict[str, N8nWorkflow] = field(default_factory=dict[str, N8nWorkflow])
    """What n8n still holds, by id."""
    projects: dict[str, str] = field(default_factory=dict[str, str])
    """Where each workflow n8n holds sits. The platform's own project is "platform"."""
    removed: list[str] = field(default_factory=list[str])
    changes_it: bool = False
    down: bool = False

    async def error_workflow_id(self) -> str | None:
        return ERROR_WORKFLOW

    async def save_draft(
        self,
        document: Mapping[str, Any],
        created: Callable[[str], Awaitable[None]] | None = None,
    ) -> SavedDraft:
        if self.down:
            raise httpx.ConnectError("n8n is down")
        kept = deepcopy(dict(document))
        pins = kept.pop("pinData", None)
        if self.changes_it:
            kept["settings"]["callerPolicy"] = "any"
        self.sent.append(deepcopy(dict(document)))
        for number, node in enumerate(kept["nodes"]):
            # As real n8n, which keeps the ids the API sends and makes one only when none came.
            node.setdefault("id", f"n8n-{number}")
        self.saved.append(kept)
        workflow_id = f"wf{len(self.saved)}"
        self.held[workflow_id] = N8nWorkflow(workflow_id, "v1", None, kept, pins)
        self.projects[workflow_id] = "platform"
        if created is not None:
            await created(workflow_id)
        return SavedDraft(workflow_id, "v1", kept, pins)

    async def platform_project(self) -> str | None:
        return "platform"

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]:
        if self.down:
            raise httpx.ConnectError("n8n is down")
        return [
            ListedWorkflow(w, None) for w in self.held.values() if self.projects[w.id] == project_id
        ]

    async def look(self, workflow_id: str) -> N8nWorkflow | None:
        return self.held.get(workflow_id)

    async def remove(self, workflow_id: str) -> None:
        self.removed.append(workflow_id)
        self.held.pop(workflow_id, None)
        self.projects.pop(workflow_id, None)

    async def remove_for_good(self, workflow_id: str) -> None:
        await self.remove(workflow_id)

    async def member_project(self, n8n_user_id: str) -> str | None:
        return f"space-{n8n_user_id}"

    async def move(self, workflow_id: str, project_id: str) -> None:
        if self.down:
            raise httpx.ConnectError("n8n is down")
        self.projects[workflow_id] = project_id


@dataclass
class Staff:
    """Alice and Carol have n8n access, as Operators with an account there."""

    with_access: frozenset[str] = frozenset({"alice", "carol"})

    async def access(self, person: UserId) -> StaffAccess:
        if person in self.with_access:
            return CanOpen(person, f"n8n-{person}")
        return NoN8nAccess()


@dataclass
class Channels:
    seen: list[str] = field(default_factory=lambda: ["#support", "#eng-housekeeping"])
    stale_since: datetime | None = None
    """When Slack last listed them, once it stopped answering."""

    async def listed(self) -> ChannelList:
        return ChannelList(list(self.seen), self.stale_since, self.stale_since is not None)


class Facts:
    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions:
        repos = frozenset({"fastapi/fastapi", *adding.get("github_releases", ())})
        return KnownOptions(
            frozenset(),
            {"github_releases": repos},
            {"jira.create_ticket": frozenset({"MOCK"})},
            {},
            {},
        )


@dataclass
class Lab:
    db: Database
    drafted: DraftedWorkflows
    approvals: SetUpApprovals
    drafter: Drafter
    n8n: N8n
    channel: Channel
    client: httpx.AsyncClient

    async def call(self, user: str, method: str, path: str, body: Any = None) -> httpx.Response:
        return await self.client.request(method, path, headers={"X-Dev-User": user}, json=body)

    async def start(
        self, user: str = "alice", words: str = WORDS, answered: bool = True
    ) -> dict[str, Any]:
        """The drafted workflow, with who says yes on each run answered by its starter."""
        r = await self.call(user, "POST", "/api/v1/drafted-workflows", {"words": words})
        assert r.status_code == 202, r.text
        await self.drafted.settle()
        view = await self.read(r.json()["drafted_id"])
        if answered and view["question"] == APPROVERS:
            view = await self.answer(view, APPROVERS, user, choice=ANY_APPROVER)
        return view

    async def answer(
        self,
        view: dict[str, Any],
        setting: str,
        user: str = "alice",
        choice: str | None = None,
        typed: str | None = None,
        status: int = 200,
    ) -> dict[str, Any]:
        body = {"revision": view["revision"], "setting": setting, "choice": choice, "typed": typed}
        r = await self.call(
            user, "POST", f"/api/v1/drafted-workflows/{view['drafted_id']}/answers", body
        )
        assert r.status_code == status, r.text
        return r.json()

    async def read(self, drafted_id: str) -> dict[str, Any]:
        r = await self.call("bob", "GET", f"/api/v1/drafted-workflows/{drafted_id}")
        assert r.status_code == 200, r.text
        return r.json()

    async def send(self, drafted_id: str, revision: int, user: str = "carol") -> httpx.Response:
        return await self.call(
            user, "POST", f"/api/v1/drafted-workflows/{drafted_id}/send", {"revision": revision}
        )

    async def use_cases(self) -> list[dict[str, Any]]:
        async with self.db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT u.use_case_id, u.draft, u.engine, u.n8n_workflow_id, u.owner,"
                    " v.document, v.also, v.grade FROM builder.use_cases u"
                    " JOIN builder.use_case_versions v USING (use_case_id)"
                )
            ).fetchall()
        return [dict(row) for row in rows]


@pytest.fixture
async def lab(postgres: PostgresUrls, db: Database) -> AsyncIterator[Lab]:
    people = People(db)
    assert await people.seed_dev(DEV_PEOPLE)
    channel, drafter, n8n = Channel(), Drafter(), N8n()
    approvals = SetUpApprovals(db, channel, people, "https://portal.example", TEAM_TIME_ZONE)
    drafted = DraftedWorkflows(
        db,
        drafter,
        approvals,
        Facts(),
        n8n,
        "https://portal.example",
        TEAM_TIME_ZONE.key,
        Channels(),
        Staff(),
        "https://n8n.example",
    )
    approvals.serve(drafted)
    app = create_app(LOCAL_ENV)
    app.state.people = people
    app.state.drafted = drafted
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Lab(db, drafted, approvals, drafter, n8n, channel, client)


async def test_the_drafter_gets_the_words_unchanged_and_the_team_s_facts_but_no_approver(
    lab: Lab,
):
    await lab.start()

    [(words, facts, current)] = lab.drafter.asked
    assert words == WORDS
    assert current is None
    assert facts.jira_projects == ["MOCK"]
    assert facts.repositories == ["fastapi/fastapi"]
    assert "bob" not in facts.model_dump_json() and "Bob" not in facts.model_dump_json()


async def test_a_drafted_release_check_with_nothing_needed_and_no_flags_can_be_sent(lab: Lab):
    view = await lab.start()

    assert (view["state"], view["revision"], view["name"]) == ("draft", 2, "Release check")
    assert (view["made_by"], view["card_revision"]) == ("answer", 1)
    assert (view["needed"], view["flags"], view["can_send"]) == (0, 0, True)
    assert view["why_not_send"] is None
    assert [b["name"] for b in view["blocks"]][:2] == ["Every Monday", "Start from the Portal"]
    report = view["report"]
    assert report["approves"] == [
        {
            "block": "Make the ticket",
            "decides": "each_run",
            "approvers": 1,
            "words": report["approves"][0]["words"],
        }
    ]
    assert report["flags"] == []


async def test_a_setting_still_needed_holds_the_send_with_how_many_are_left(lab: Lab):
    lab.drafter.answers = [drafted(release_check(run_time=None))]
    view = await lab.start()

    assert (view["needed"], view["can_send"], view["question"]) == (2, False, "run_time")
    assert view["why_not_send"] == "Answer 2 questions first"
    r = await lab.send(view["drafted_id"], view["revision"])
    assert (r.status_code, r.json()["detail"]) == (409, "Answer 2 questions first")
    assert lab.channel.posted == []


async def test_a_flagged_draft_can_t_be_sent_in_this_step(lab: Lab):
    plan = release_check().model_dump()
    plan["blocks"][1]["parameters"]["source"] = "jira_tickets"
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start()

    assert view["flags"] >= 1 and view["can_send"] is False
    assert "comes in a later step" in view["why_not_send"]
    assert (await lab.send(view["drafted_id"], view["revision"])).status_code == 409


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (
            WorkflowNotDrafted(
                why="gave_up",
                message="I couldn't draft that.",
                catalogue="x",
                sent_back=[],
                turns=4,
            ),
            "I couldn't draft that.",
        ),
        (NoModel(), "I couldn't draft that. No AI model is connected yet."),
        (RuntimeDown("503"), "I couldn't draft that."),
        (ModelProblem(reason="too_slow", message="slow"), "I couldn't draft that."),
    ],
)
async def test_a_draft_that_didn_t_work_says_so_and_offers_nothing_to_send(
    lab: Lab, answer: WorkflowDraftResult | NoModel | RuntimeDown, said: str
):
    lab.drafter.answers = [answer]
    view = await lab.start()

    assert (view["state"], view["said"], view["can_send"]) == ("not_drafted", said, False)


async def test_words_shaped_like_a_key_are_refused_before_anything_is_kept_or_sent(lab: Lab):
    r = await lab.call(
        "alice",
        "POST",
        "/api/v1/drafted-workflows",
        {"words": "Draft a workflow with ghp_abcdefghijklmnopqrstuvwxyz0123 for GitHub"},
    )

    assert (r.status_code, r.json()["detail"]) == (409, KEY_PASTED)
    assert lab.drafter.asked == []
    async with lab.db.connection("builder") as conn:
        row = await (
            await conn.execute("SELECT count(*) AS n FROM builder.drafted_revisions")
        ).fetchone()
    assert row is not None and row["n"] == 0


async def test_only_an_operator_may_draft_change_or_send(lab: Lab):
    view = await lab.start()
    drafted_id = view["drafted_id"]

    assert (
        await lab.call("bob", "POST", "/api/v1/drafted-workflows", {"words": WORDS})
    ).status_code == 403
    change = {"words": "post at 9 instead", "revision": 1}
    path = f"/api/v1/drafted-workflows/{drafted_id}/changes"
    assert (await lab.call("bob", "POST", path, change)).status_code == 403
    assert (await lab.send(drafted_id, view["revision"], user="bob")).status_code == 403


async def test_the_same_idempotency_key_answers_the_draft_it_started(lab: Lab):
    key = {"Idempotency-Key": str(uuid.uuid4()), "X-Dev-User": "alice"}
    body = {"words": WORDS}
    first = await lab.client.post("/api/v1/drafted-workflows", json=body, headers=key)
    again = await lab.client.post("/api/v1/drafted-workflows", json=body, headers=key)
    await lab.drafted.settle()

    assert first.json()["drafted_id"] == again.json()["drafted_id"]
    assert len(lab.drafter.asked) == 1


async def test_settle_returns_when_a_draft_ended_before_its_clean_up_ran(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
):
    # A draft task that has ended but whose done callback, which takes it off the running set,
    # hasn't run yet. gather() on futures that are all done completes without giving the loop a
    # turn, so a settle that waits while the set is non-empty spun here for good (CI, 17 Nov).
    ended = asyncio.get_running_loop().create_future()
    ended.set_result(None)
    lab.drafted._running.add(ended)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    real_gather = asyncio.gather
    gathers = 0

    def counted_gather(*futures: Any, return_exceptions: bool = False) -> Any:
        nonlocal gathers
        gathers += 1
        assert gathers < 100, "settle keeps gathering drafts that have already ended"
        return real_gather(*futures, return_exceptions=return_exceptions)

    monkeypatch.setattr(asyncio, "gather", counted_gather)

    await lab.drafted.settle()


async def test_a_change_sends_the_plan_as_it_stands_and_replaces_a_waiting_approval(lab: Lab):
    view = await lab.start()
    drafted_id = view["drafted_id"]
    assert (await lab.send(drafted_id, view["revision"])).status_code == 200

    r = await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/changes",
        {"words": "post at 10:00 instead", "revision": 2},
    )
    assert r.status_code == 202, r.text
    assert r.json()["state"] == "drafting"
    await lab.drafted.settle()
    after = await lab.read(drafted_id)

    words, _, current = lab.drafter.asked[-1]
    assert words == "post at 10:00 instead"
    assert current is not None and current.name == "Release check"
    assert (after["revision"], after["state"], after["replaced_waiting"]) == (3, "draft", True)
    assert (after["approval"], after["card_revision"], after["question"]) == (None, 3, None)
    stale = await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/changes",
        {"words": "drop it", "revision": 2},
    )
    assert (stale.status_code, stale.json()["detail"]) == (409, "A newer revision is below.")


async def test_a_sent_revision_waits_for_an_approver_who_is_not_a_party(lab: Lab):
    view = await lab.start(user="alice")
    drafted_id = view["drafted_id"]

    sent = await lab.send(drafted_id, view["revision"], user="carol")
    await lab.approvals.work_once()

    assert sent.json()["state"] == "waiting"
    approval = sent.json()["approval"]
    assert approval["link"] == f"/setup-approvals/{approval['approval_id']}"
    [notice] = lab.channel.posted
    assert sorted(notice.not_deciding) == ["Alice", "Carol"]
    page = await lab.call("alice", "GET", f"/api/v1/setup-approvals/{approval['approval_id']}")
    assert page.json()["you_can_decide"] is False
    assert page.json()["why_not"].startswith("You can't approve it.")
    refused = await lab.call(
        "alice",
        "POST",
        f"/api/v1/setup-approvals/{approval['approval_id']}/decisions",
        {"verdict": "approve", "digest": page.json()["digest"]},
    )
    assert refused.status_code == 403


async def test_bob_s_yes_sets_the_approved_digest_up_as_a_draft(lab: Lab):
    view = await lab.start()
    drafted_id = view["drafted_id"]
    sent = (await lab.send(drafted_id, view["revision"])).json()
    approval_id = sent["approval"]["approval_id"]
    page = (await lab.call("bob", "GET", f"/api/v1/setup-approvals/{approval_id}")).json()
    assert page["you_can_decide"] is True

    r = await lab.call(
        "bob",
        "POST",
        f"/api/v1/setup-approvals/{approval_id}/decisions",
        {"verdict": "approve", "digest": page["digest"]},
    )
    assert r.status_code == 201, r.text
    await lab.approvals.work_once()

    [saved] = lab.n8n.saved
    assert workflow_digest(saved) == page["digest"]
    [use_case] = await lab.use_cases()
    assert (use_case["draft"], use_case["engine"], use_case["n8n_workflow_id"]) == (
        True,
        "own",
        "wf1",
    )
    assert {a["by"] for a in use_case["also"]} == {"alice", "carol"}
    after = await lab.read(drafted_id)
    assert after["state"] == "approved"
    assert after["set_up"] == {
        "state": "set_up",
        "use_case_id": use_case["use_case_id"],
        "words": None,
    }
    assert [o.verdict for o in lab.channel.updated] == ["approved"]


async def test_a_workflow_n8n_holds_otherwise_than_approved_is_not_set_up(lab: Lab):
    lab.n8n.changes_it = True
    view = await lab.start()
    sent = (await lab.send(view["drafted_id"], view["revision"])).json()
    approval_id = sent["approval"]["approval_id"]
    page = (await lab.call("bob", "GET", f"/api/v1/setup-approvals/{approval_id}")).json()

    await lab.call(
        "bob",
        "POST",
        f"/api/v1/setup-approvals/{approval_id}/decisions",
        {"verdict": "approve", "digest": page["digest"]},
    )
    await lab.approvals.work_once()

    assert lab.n8n.removed == ["wf1"]
    assert await lab.use_cases() == []
    after = await lab.read(view["drafted_id"])
    assert after["set_up"] == {"state": "refused", "use_case_id": None, "words": CHANGED}


async def test_a_decline_needs_a_reason_from_the_short_list(lab: Lab):
    view = await lab.start()
    sent = (await lab.send(view["drafted_id"], view["revision"])).json()
    approval_id = sent["approval"]["approval_id"]
    page = (await lab.call("bob", "GET", f"/api/v1/setup-approvals/{approval_id}")).json()
    path = f"/api/v1/setup-approvals/{approval_id}/decisions"

    bare = await lab.call("bob", "POST", path, {"verdict": "decline", "digest": page["digest"]})
    made_up = await lab.call(
        "bob", "POST", path, {"verdict": "decline", "digest": page["digest"], "reason": "Meh"}
    )
    declined = await lab.call(
        "bob",
        "POST",
        path,
        {"verdict": "decline", "digest": page["digest"], "reason": "Not needed"},
    )

    assert (bare.status_code, made_up.status_code, declined.status_code) == (422, 422, 201)
    after = await lab.read(view["drafted_id"])
    assert after["state"] == "declined"
    assert (after["approval"]["decided_by"], after["approval"]["reason"]) == ("Bob", "Not needed")
    assert lab.n8n.saved == []


async def test_a_set_up_n8n_didn_t_take_can_be_tried_again(lab: Lab, db: Database):
    lab.n8n.down = True
    view = await lab.start()
    sent = (await lab.send(view["drafted_id"], view["revision"])).json()
    approval_id = sent["approval"]["approval_id"]
    page = (await lab.call("bob", "GET", f"/api/v1/setup-approvals/{approval_id}")).json()
    await lab.call(
        "bob",
        "POST",
        f"/api/v1/setup-approvals/{approval_id}/decisions",
        {"verdict": "approve", "digest": page["digest"]},
    )
    from datetime import timedelta

    for later in range(8):
        await lab.approvals.work_once(db.clock() + timedelta(minutes=10 * later))
    failed = await lab.read(view["drafted_id"])
    assert failed["set_up"]["state"] == "failed"

    lab.n8n.down = False
    again = await lab.call(
        "carol", "POST", f"/api/v1/drafted-workflows/{view['drafted_id']}/set-up"
    )
    assert again.status_code == 200, again.text
    await lab.approvals.work_once(db.clock() + timedelta(hours=2))

    after = await lab.read(view["drafted_id"])
    assert after["set_up"]["state"] == "set_up"
