"""The start of a fix and its approval (ADR 0055, sections 6 and 7, PR 6), end to end in
platform-api with the agent runtime, n8n's record of the run and the builder's test run faked.

An Operator asks for a fix on a stopped run. platform-api writes the fix's start itself, with who
asked from the session, and mints the fix's token only once the log took the start. The fixed
version is stored under the fix id, and a proposal of it opens a set-up approval (ADR 0051, as
ADR 0055 amends it): the person who asked and everyone who changed the version are its parties,
and nobody approves their own work. After a yes, Turn back on runs the one real test run, which
writes nothing, and only then turns the workflow on. A no leaves the fix off. A fix never changes
a setting: when the cause needs one, the hand-back asks the person for it."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import httpx
import pytest

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder.drafted_workflows import DraftedWorkflows
from platform_api.builder.fix_parts import (
    FIX_TOKEN_HEADER,
    FixLayouts,
    FixParts,
    fix_token,
    fix_token_ok,
)
from platform_api.builder.fixes import (
    DECLINED,
    HANDED_BACK,
    NEVER_PROPOSED,
    STALE,
    Fixes,
    FixSettings,
    FixTrying,
)
from platform_api.builder.n8n_facts import BuilderWorkflowFacts, Specs
from platform_api.db import Database
from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    FixStartedData,
    PendingEvent,
    RunCreatedData,
    RunFailedData,
    RunRetriedData,
)
from platform_api.orchestration import (
    GITHUB_RELEASES,
    AgentRejected,
    AgentUnavailable,
    FixAccepted,
    FixStartRequest,
    ModelAccess,
    NodeState,
    RunInN8n,
    WorkflowPlan,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.shared import TEAM_TIME_ZONE, Principal, RunId, UserId
from tests.conftest import PostgresUrls
from tests.support import LOCAL_ENV
from tests.test_drafted_layout import release_check
from tests.test_drafted_workflows import Channels, Drafter, Facts, Lab, N8n, Staff
from tests.test_setup_approvals import Channel

pytestmark = pytest.mark.anyio

KEY = LOCAL_ENV["CALLBACK_SIGNING_KEY"]
RUN = RunId("run_01STOPPED")
READ = "Read new releases"
PROPOSE = "Propose a ticket"
MOVED_FIELD = "={{ 'New release ' + $json.release.tag }}"
CAUSE = {
    "failed_part": [PROPOSE],
    "system": None,
    "failure_kind": "changed_field",
    "detail": "tag",
}
ALL_PASSED = {
    "happy_path": {"kind": "happy_path", "verdict": "passed", "step": None, "why": None},
    "replay_the_stop": {"kind": "happy_path", "verdict": "passed", "step": None, "why": None},
}


def fixed(plan: WorkflowPlan) -> WorkflowPlan:
    """The stopped version with only the field the ticket's title reads moved."""
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "title": MOVED_FIELD}})
        if b.name == PROPOSE
        else b
        for b in plan.blocks
    ]
    return plan.model_copy(update={"blocks": blocks})


class Clock:
    """The database's clock, which a test moves on. It starts at the real time, as the fix's
    token is checked against the real time."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def later(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Runtime:
    """The agent runtime's POST /v1/fixes, which runs the coordinator."""

    started: list[FixStartRequest] = field(default_factory=list[FixStartRequest])
    answer: FixAccepted | AgentUnavailable | AgentRejected | None = None

    async def start_fix(
        self, request: FixStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected:
        self.started.append(request)
        return self.answer or FixAccepted(fix_id=request.request.fix_id, started=True)


@dataclass
class Records:
    """n8n's record of the stopped run: where it stopped."""

    stopped_at: str = PROPOSE

    async def read(self, run_id: RunId) -> RunInN8n | None:
        nodes: dict[str, NodeState] = {
            name: ("failed" if name == self.stopped_at else "done")
            for name in ("Every Monday", READ, PROPOSE)
        }
        return RunInN8n(run_id, "", "Failed", "exec-1", "wf1", "v1", nodes, True)


@dataclass
class Models:
    access_now: ModelAccess | None = field(
        default_factory=lambda: ModelAccess.model_validate(
            {
                "style": "anthropic",
                "base_url": "https://model.example",
                "model": "m",
                "api_key": "x" * 8,
            }
        )
    )

    async def access(self) -> ModelAccess | None:
        return self.access_now


@dataclass
class Tries:
    """The builder's test run of the fixed version and turning the workflow back on."""

    done: list[str] = field(default_factory=list[str])
    outcome: Literal["passed", "failed"] | None = None
    tried: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def try_fixed(
        self, use_case_id: str, document: dict[str, Any], by: Principal
    ) -> FixTrying | str:
        self.done.append("test run")
        self.tried.append(document)
        return FixTrying(run_id="run_01TEST", draft="v2")

    async def tried_outcome(self, run_id: str) -> Literal["passed", "failed"] | None:
        return self.outcome

    async def put_live(
        self,
        use_case_id: str,
        trying: FixTrying,
        document: dict[str, Any],
        by: UserId,
        authors: frozenset[UserId],
    ) -> str | None:
        self.done.append("turned on")
        return None


@dataclass
class FixLab:
    lab: Lab
    db: Database
    clock: Clock
    log: ActivityLog
    fixes: Fixes
    runtime: Runtime
    records: Records
    models: Models
    tries: Tries
    settings: FixSettings

    async def call(self, user: str, method: str, path: str, body: Any = None) -> httpx.Response:
        return await self.lab.call(user, method, path, body)

    async def internal(
        self, path: str, body: Any, token: str | None = None, fix_id: str | None = None
    ) -> httpx.Response:
        asked = self.runtime.started[-1]
        fix_id = fix_id or asked.request.fix_id
        headers = {FIX_TOKEN_HEADER: token or asked.token}
        return await self.lab.client.post(
            f"/internal/v1/runs/{RUN}/fixes/{fix_id}{path}", json=body, headers=headers
        )

    async def set_up_and_stop(self) -> str:
        """A drafted workflow Alice described and Carol sent, that Bob approved, set up and
        turned on, whose run stopped."""
        lab = self.lab
        view = await lab.start(user="alice")
        sent = (await lab.send(view["drafted_id"], view["revision"], user="carol")).json()
        approval_id = sent["approval"]["approval_id"]
        page = (await lab.call("bob", "GET", f"/api/v1/setup-approvals/{approval_id}")).json()
        decided = await lab.call(
            "bob",
            "POST",
            f"/api/v1/setup-approvals/{approval_id}/decisions",
            {"verdict": "approve", "digest": page["digest"]},
        )
        assert decided.status_code == 201, decided.text
        await lab.approvals.work_once()
        [use_case] = await lab.use_cases()
        async with self.db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.use_cases SET draft = false WHERE use_case_id = %s",
                (use_case["use_case_id"],),
            )
        await self.stop(use_case["use_case_id"])
        return str(use_case["use_case_id"])

    async def stop(self, use_case_id: str) -> None:
        async with self.db.transaction("monitoring") as uow:
            created = RunCreatedData(
                use_case_id=use_case_id, use_case_version=1, started_by=UserId("alice")
            )
            failed = RunFailedData(
                stage="working",
                reason="WorkflowNodeError",
                retryable=False,
                message="The ticket's title read a field that isn't there: tag",
            )
            await self.log.append(
                uow,
                RUN,
                [
                    PendingEvent(PLATFORM, "run_created", "Alice started a run.", created),
                    PendingEvent(PLATFORM, "run_failed", "The run stopped.", failed),
                ],
            )

    async def ask(self, user: str = "alice", status: int = 202) -> dict[str, Any]:
        answer = await self.call(user, "POST", f"/api/v1/runs/{RUN}/fixes", {})
        assert answer.status_code == status, answer.text
        return answer.json()

    def stopped(self) -> WorkflowPlan:
        """The stopped version, as platform-api sent it to the coordinator."""
        return self.runtime.started[-1].request.version

    async def store(self, plan: WorkflowPlan | None = None, **given: Any) -> httpx.Response:
        version = (plan or fixed(self.stopped())).model_dump(mode="json")
        return await self.internal("/revisions", {"version": version, "cause": CAUSE}, **given)

    async def proven(self, plan: WorkflowPlan | None = None) -> None:
        fix_id = self.runtime.started[-1].request.fix_id
        await self.fixes.simulated_on(fix_id, plan or fixed(self.stopped()), ALL_PASSED)

    async def propose(self, version: int, digest: str, **given: Any) -> httpx.Response:
        fix_id = given.pop("fix_id", None) or self.runtime.started[-1].request.fix_id
        data = {"fix_id": fix_id, "version": version, "digest": digest}
        return await self.internal(
            "/events", {"kind": "fix_proposed", "data": data}, fix_id=fix_id, **given
        )

    async def handed_in(self) -> dict[str, Any]:
        """Asked for, proven, stored and proposed: the fix waits for a yes."""
        view = await self.ask()
        await self.proven()
        stored = await self.store()
        assert stored.status_code == 200, stored.text
        proposed = await self.propose(**stored.json())
        assert proposed.json() == {"refused": None}, proposed.text
        return await self.view(view["fix_id"])

    async def view(self, fix_id: str, user: str = "alice") -> dict[str, Any]:
        answer = await self.call(user, "GET", f"/api/v1/fixes/{fix_id}")
        assert answer.status_code == 200, answer.text
        return answer.json()

    async def page(self, approval_id: str, user: str = "bob") -> dict[str, Any]:
        answer = await self.call(user, "GET", f"/api/v1/setup-approvals/{approval_id}")
        assert answer.status_code == 200, answer.text
        return answer.json()

    async def decide(
        self, approval_id: str, user: str, verdict: str = "approve", **given: Any
    ) -> httpx.Response:
        digest = given.pop("digest", None) or (await self.page(approval_id))["digest"]
        body = {"verdict": verdict, "digest": digest, **given}
        return await self.call(
            user, "POST", f"/api/v1/setup-approvals/{approval_id}/decisions", body
        )

    async def turn_back_on(self, fix_id: str, user: str = "alice") -> httpx.Response:
        return await self.call(user, "POST", f"/api/v1/fixes/{fix_id}/turn-back-on", {})

    async def fix_events(self) -> list[Any]:
        return [e for e in await self.log.read_after(RUN, 0) if e.kind.startswith("fix_")]


@pytest.fixture
async def fix_lab(postgres: PostgresUrls, db: Database) -> AsyncIterator[FixLab]:
    clock = Clock()
    timed = Database(postgres.contexts, clock=clock)
    await timed.open()
    try:
        people = People(timed)
        assert await people.seed_dev(DEV_PEOPLE)
        channel, drafter, n8n = Channel(), Drafter(), N8n()
        approvals = SetUpApprovals(timed, channel, people, "https://portal.example", TEAM_TIME_ZONE)
        drafted = DraftedWorkflows(
            timed,
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
        log = ActivityLog(timed)
        layouts = FixLayouts(Facts(), n8n, "https://portal.example", TEAM_TIME_ZONE.key)
        runtime, records, models, tries = Runtime(), Records(), Models(), Tries()
        settings = FixSettings(on=True, signing_key=KEY, platform_url="http://platform-api:8000")
        fixes = Fixes(
            timed,
            log,
            records,
            drafted,
            approvals,
            runtime,
            models,
            tries,
            settings,
        )
        drafted.serve_fixes(fixes)
        app = create_app(LOCAL_ENV)
        app.state.people = people
        app.state.drafted = drafted
        app.state.fixes = fixes
        app.state.activity_log = log
        app.state.fix_parts = FixParts(layouts, None, None, fixes, fixes)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            lab = Lab(timed, drafted, approvals, drafter, n8n, channel, client)
            yield FixLab(lab, timed, clock, log, fixes, runtime, records, models, tries, settings)
    finally:
        await timed.close()


# The start


async def test_platform_api_writes_the_start_with_who_asked_from_the_session(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    answer = await fix_lab.call(
        "alice", "POST", f"/api/v1/runs/{RUN}/fixes", {"asked_by": "mallory"}
    )
    assert answer.status_code == 202, answer.text
    fix_id = answer.json()["fix_id"]

    [start] = await fix_lab.fix_events()
    assert start.kind == "fix_started"
    assert (start.data.fix_id, start.data.asked_by, start.data.asked_by_name) == (
        fix_id,
        "alice",
        "Alice",
    )
    [asked] = fix_lab.runtime.started
    assert (asked.request.fix_id, asked.request.asked_by, asked.run_id) == (fix_id, "alice", RUN)
    assert asked.request.ends_by == start.data.ends_by
    assert asked.request.stopped_at == [PROPOSE]
    assert [b.name for b in asked.request.version.blocks] == [
        b.name for b in release_check().blocks
    ]
    assert asked.token == fix_token(KEY, RUN, fix_id, start.data.ends_by)
    assert fix_token_ok(KEY, RUN, fix_id, asked.token, datetime.now(UTC))
    assert asked.platform_url == "http://platform-api:8000"
    assert answer.json()["state"] == "drafting"


async def test_no_token_is_minted_when_the_log_refuses_the_start(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    elsewhere = FixStartedData(
        fix_id="fix_01ELSE",
        asked_by=UserId("carol"),
        asked_by_name="Carol",
        ends_by=fix_lab.clock.now + timedelta(minutes=10),
    )
    assert await fix_lab.log.note_fix(RUN, elsewhere) is None
    refused = await fix_lab.ask(status=409)
    assert refused["detail"] == "A fix for this workflow is already under way."
    assert fix_lab.runtime.started == []


async def test_one_fix_at_a_time_for_a_workflow_and_none_once_the_run_goes_on(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    first = await fix_lab.ask()
    second = await fix_lab.ask(user="carol", status=409)
    assert second["detail"] == "A fix for this workflow is already under way."
    assert [a.request.fix_id for a in fix_lab.runtime.started] == [first["fix_id"]]

    async with fix_lab.db.transaction("monitoring") as uow:
        retried = RunRetriedData(leg="work", attempt=2)
        await fix_lab.log.append(
            uow, RUN, [PendingEvent(PLATFORM, "run_retried", "Retried.", retried)]
        )
    fix_lab.clock.later(minutes=21)
    refused = await fix_lab.ask(status=409)
    assert refused["detail"] == "This run isn't stopped, so there's nothing to fix."
    assert len(fix_lab.runtime.started) == 1
    starts = [e for e in await fix_lab.fix_events() if e.kind == "fix_started"]
    assert len(starts) == 1


async def test_only_an_operator_asks_for_a_fix_and_only_while_fix_it_for_me_is_on(
    fix_lab: FixLab,
):
    await fix_lab.set_up_and_stop()
    refused = await fix_lab.ask(user="bob", status=403)
    assert refused["detail"] == "Only an Operator can ask for a fix. Ask an Operator on the team."
    fix_lab.fixes.settings = FixSettings(on=False, signing_key=KEY, platform_url="http://x")
    off = await fix_lab.ask(status=409)
    assert off["detail"] == "Fix it for me is off here."
    fix_lab.fixes.settings = fix_lab.settings
    fix_lab.models.access_now = None
    no_model = await fix_lab.ask(status=409)
    assert no_model["detail"] == "Fix it for me needs an AI model, and none is connected yet."
    assert fix_lab.runtime.started == []
    assert await fix_lab.fix_events() == []


async def test_a_runtime_that_doesn_t_take_the_fix_hands_it_back_at_once(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    fix_lab.runtime.answer = AgentUnavailable("down")
    view = await fix_lab.ask()
    assert view["state"] == "handed_back"
    assert [e.kind for e in await fix_lab.fix_events()] == ["fix_started", "fix_handed_back"]


# The store of the fixed version


async def test_a_fix_is_stored_once_under_its_fix_id(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.ask()
    await fix_lab.proven()
    first = await fix_lab.store()
    again = await fix_lab.store()
    assert first.status_code == again.status_code == 200, first.text
    assert first.json() == again.json()
    assert first.json()["version"] == 2
    assert (await fix_lab.view(view["fix_id"]))["state"] == "drafting"


async def test_a_fix_is_stored_only_once_its_simulations_here_all_passed(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    await fix_lab.ask()
    unproven = await fix_lab.store()
    assert unproven.status_code == 409
    fix_id = fix_lab.runtime.started[-1].request.fix_id
    failed = {**ALL_PASSED, "happy_path": {**ALL_PASSED["happy_path"], "verdict": "failed"}}
    await fix_lab.fixes.simulated_on(fix_id, fixed(fix_lab.stopped()), failed)
    assert (await fix_lab.store()).status_code == 409


async def test_a_fix_never_changes_a_setting(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    await fix_lab.ask()
    plan = fixed(fix_lab.stopped())
    settings = [
        s.model_copy(update={"value": "langchain-ai/langgraph-py"}) if s.id == "repository" else s
        for s in plan.settings
    ]
    widened = plan.model_copy(update={"settings": settings})
    await fix_lab.proven(widened)
    refused = await fix_lab.store(widened)
    assert (refused.status_code, refused.json()["detail"]) == (422, "A fix can't change a setting.")


async def test_a_store_that_comes_back_after_the_deadline_stores_nothing(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.ask()
    await fix_lab.proven()
    fix_lab.clock.later(minutes=20, seconds=1)
    late = await fix_lab.store()
    assert late.status_code == 409
    assert (await fix_lab.view(view["fix_id"]))["state"] == "handed_back"


async def test_a_stored_fix_never_proposed_never_waits_for_a_yes_and_is_dropped_on_the_next_start(
    fix_lab: FixLab,
):
    await fix_lab.set_up_and_stop()
    first = await fix_lab.ask()
    await fix_lab.proven()
    stored = await fix_lab.store()
    assert stored.status_code == 200
    fix_lab.clock.later(minutes=21)

    assert await fix_lab.lab.approvals.latest(first["fix_id"]) is None
    late = await fix_lab.propose(**stored.json(), fix_id=first["fix_id"])
    assert late.json() == {"refused": "ended"}
    assert await fix_lab.lab.approvals.latest(first["fix_id"]) is None

    second = await fix_lab.ask()
    assert second["fix_id"] != first["fix_id"]
    dropped = await fix_lab.view(first["fix_id"])
    assert (dropped["state"], dropped["said"]) == ("dropped", NEVER_PROPOSED)


# The proposal and its set-up approval


async def test_a_proposal_opens_a_set_up_approval_for_the_stored_version(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    assert view["state"] == "waiting"
    state = await fix_lab.lab.approvals.latest(view["fix_id"])
    assert state is not None
    assert (state.request.revision, state.request.sent_by) == (2, "alice")
    assert state.request.parties == {"alice", "carol"}

    page = await fix_lab.page(view["approval_id"])
    assert page["you_can_decide"] is True
    assert page["digest"] == state.request.digest
    evidence = page["fix"]
    assert evidence["cause"]
    assert evidence["changes"] == [
        {
            "block": PROPOSE,
            "parameter": "title",
            "before": "={{ 'New release ' + $json.tag }}",
            "after": MOVED_FIELD,
        }
    ]
    assert {s["name"]: s["verdict"] for s in evidence["scenarios"]} == {
        "happy_path": "passed",
        "replay_the_stop": "passed",
    }
    assert {c["check"]: c["passed"] for c in evidence["checks"]} == {
        "inside_the_failed_part": True,
        "every_scenario_passed": True,
        "safety_check": True,
        "settings_unchanged": True,
    }
    assert page["report"]["reworded"] is None


async def test_a_proposal_that_isn_t_the_stored_revision_is_refused(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.ask()
    await fix_lab.proven()
    stored = (await fix_lab.store()).json()
    wrong = await fix_lab.propose(stored["version"], "sha256:" + "0" * 64)
    assert wrong.status_code == 422
    assert [e.kind for e in await fix_lab.fix_events()] == ["fix_started"]
    assert await fix_lab.lab.approvals.latest(view["fix_id"]) is None


async def test_the_person_who_asked_for_the_fix_can_never_approve_it(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    page = await fix_lab.page(view["approval_id"], user="alice")
    assert page["you_can_decide"] is False
    own = await fix_lab.decide(view["approval_id"], "alice")
    assert own.status_code == 403
    assert own.json()["detail"].startswith("You can't approve it.")


async def test_an_approval_by_a_stranger_is_refused(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    not_an_approver = await fix_lab.decide(view["approval_id"], "carol")
    assert not_an_approver.status_code == 403
    stranger = await fix_lab.decide(view["approval_id"], "mallory")
    assert stranger.status_code in {401, 403}
    assert (await fix_lab.view(view["fix_id"]))["state"] == "waiting"


# Turn back on


async def test_a_yes_runs_the_test_run_before_the_workflow_turns_back_on(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    early = await fix_lab.turn_back_on(view["fix_id"])
    assert early.status_code == 409
    assert fix_lab.tries.done == []

    yes = await fix_lab.decide(view["approval_id"], "bob")
    assert yes.status_code == 201, yes.text
    await fix_lab.lab.approvals.work_once()
    assert (await fix_lab.view(view["fix_id"]))["state"] == "approved"
    assert fix_lab.tries.done == []

    pressed = await fix_lab.turn_back_on(view["fix_id"])
    assert pressed.status_code == 202, pressed.text
    assert pressed.json()["state"] == "testing"
    assert fix_lab.tries.done == ["test run"]
    page = await fix_lab.page(view["approval_id"])
    assert [workflow_digest_of(d) for d in fix_lab.tries.tried] == [page["digest"]]

    await fix_lab.fixes.work_once()
    assert fix_lab.tries.done == ["test run"], "nothing turns on before the test run passed"
    fix_lab.tries.outcome = "passed"
    await fix_lab.fixes.work_once()
    await fix_lab.fixes.work_once()
    assert fix_lab.tries.done == ["test run", "turned on"]
    assert (await fix_lab.view(view["fix_id"]))["state"] == "on"


async def test_a_test_run_that_doesn_t_pass_leaves_the_workflow_as_it_was(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    await fix_lab.decide(view["approval_id"], "bob")
    await fix_lab.lab.approvals.work_once()
    await fix_lab.turn_back_on(view["fix_id"])
    fix_lab.tries.outcome = "failed"
    await fix_lab.fixes.work_once()
    assert fix_lab.tries.done == ["test run"]
    assert (await fix_lab.view(view["fix_id"]))["state"] == "test_failed"


async def test_a_no_leaves_the_fix_off_and_says_so(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    no = await fix_lab.decide(view["approval_id"], "bob", "decline", reason="Not needed")
    assert no.status_code == 201, no.text
    await fix_lab.lab.approvals.work_once()
    after = await fix_lab.view(view["fix_id"])
    assert (after["state"], after["said"]) == ("declined", DECLINED)
    refused = await fix_lab.turn_back_on(view["fix_id"])
    assert (refused.status_code, refused.json()["detail"]) == (409, DECLINED)
    assert fix_lab.tries.done == []


async def test_a_replayed_approval_is_refused(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    first = await fix_lab.handed_in()
    first_page = await fix_lab.page(first["approval_id"])
    no = await fix_lab.decide(first["approval_id"], "bob", "decline", reason="Not needed")
    assert no.status_code == 201
    replayed_no = await fix_lab.decide(first["approval_id"], "bob", "decline", reason="Not needed")
    assert replayed_no.status_code == 200
    first_token = fix_lab.runtime.started[-1].token

    second = await fix_lab.handed_in()
    assert second["approval_id"] != first["approval_id"]
    old_yes = await fix_lab.decide(second["approval_id"], "bob", digest="sha256:" + "1" * 64)
    assert old_yes.status_code == 403
    late_yes = await fix_lab.decide(first["approval_id"], "bob", digest=first_page["digest"])
    assert late_yes.status_code == 403
    stolen = await fix_lab.store(token=first_token)
    assert stolen.status_code == 401

    yes = await fix_lab.decide(second["approval_id"], "bob")
    again = await fix_lab.decide(second["approval_id"], "bob")
    assert (yes.status_code, again.status_code) == (201, 200)
    await fix_lab.lab.approvals.work_once()
    assert (await fix_lab.turn_back_on(second["fix_id"])).status_code == 202
    assert (await fix_lab.turn_back_on(second["fix_id"])).status_code == 202
    assert fix_lab.tries.done == ["test run"]


async def test_a_new_version_of_the_workflow_drops_a_fix_that_still_waits(fix_lab: FixLab):
    use_case_id = await fix_lab.set_up_and_stop()
    view = await fix_lab.handed_in()
    async with fix_lab.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_cases SET current_version = 2 WHERE use_case_id = %s",
            (use_case_id,),
        )
    page = await fix_lab.page(view["approval_id"])
    assert (page["you_can_decide"], page["why_not"]) == (False, STALE)
    refused = await fix_lab.decide(view["approval_id"], "bob")
    assert (refused.status_code, refused.json()["detail"]) == (403, STALE)
    after = await fix_lab.view(view["fix_id"])
    assert (after["state"], after["said"]) == ("dropped", STALE)


# The hand-back


async def test_a_hand_back_asks_for_the_setting_a_fix_may_not_change(fix_lab: FixLab):
    fix_lab.records.stopped_at = READ
    await fix_lab.set_up_and_stop()
    view = await fix_lab.ask()
    back = await fix_lab.internal(
        "/events",
        {"kind": "fix_handed_back", "data": {"fix_id": view["fix_id"], "why": "widened"}},
    )
    assert back.json() == {"refused": None}
    after = await fix_lab.view(view["fix_id"])
    assert (after["state"], after["said"]) == ("handed_back", HANDED_BACK)
    question = after["question"]
    assert (question["setting"], question["words"]) == (
        "repository",
        "Which GitHub repository should it read?",
    )

    answered = await fix_lab.call(
        "carol",
        "POST",
        f"/api/v1/fixes/{view['fix_id']}/answers",
        {"setting": "repository", "typed": "langchain-ai/langgraph-py"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["state"] == "waiting"
    state = await fix_lab.lab.approvals.latest(view["fix_id"])
    assert state is not None
    assert {"alice", "carol"} <= state.request.parties
    page = await fix_lab.page(answered.json()["approval_id"])
    assert page["fix"]["changes"] == [
        {
            "block": READ,
            "parameter": "place",
            "before": "langchain-ai/langgraph",
            "after": "langchain-ai/langgraph-py",
        }
    ]

    facts = BuilderWorkflowFacts(fix_lab.db, cast(Specs, None), None, ())
    assert "langchain-ai/langgraph-py" not in {o.id for o in await facts.places(GITHUB_RELEASES)}
    assert (await fix_lab.decide(answered.json()["approval_id"], "bob")).status_code == 201
    await fix_lab.lab.approvals.work_once()
    readable = {o.id for o in await facts.places(GITHUB_RELEASES)}
    assert "langchain-ai/langgraph-py" in readable, "its test run may read it after the yes"


async def test_only_the_fix_s_own_start_is_written_by_the_platform(fix_lab: FixLab):
    await fix_lab.set_up_and_stop()
    view = await fix_lab.ask()
    forged = FixStartedData(
        fix_id=view["fix_id"],
        asked_by=UserId("mallory"),
        asked_by_name="Mallory",
        ends_by=datetime.now(UTC) + timedelta(minutes=5),
    )
    answer = await fix_lab.internal(
        "/events", {"kind": "fix_started", "data": forged.model_dump(mode="json")}
    )
    assert answer.status_code == 422
    assert [e.kind for e in await fix_lab.fix_events()] == ["fix_started"]


def workflow_digest_of(document: dict[str, Any]) -> str:
    from platform_api.orchestration import workflow_digest

    return workflow_digest(document)
