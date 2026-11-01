import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.dispatch import (
    RETRY_POLICY,
    ApprovalNotice,
    ApprovalOutcome,
    AskedStep,
    DispatchFailure,
    MessageRef,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.runs import Leg, Pending
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.store import Store
from platform_api.orchestration.teams import TeamsWorkflowsWebhook, approval_card
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.shared import ApprovalId, Digest, N8nExecutionId, RunId
from tests.conftest import PostgresUrls, truncate_all
from tests.support import BOB, SPEC, SUMMARY, TICKET_TITLE
from tests.test_orchestrator import (
    ASK_APPROVAL,
    PUBLIC_BASE_URL,
    RUN_AGENTS,
    Harness,
    RecordingEngine,
    mint,
    open_harness,
    start,
    work_leg_to_approval,
)
from tests.test_ready import env_for

pytestmark = pytest.mark.anyio


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as harness:
        yield harness


class RecordingChannel:
    name = "CODESparks Ops"
    adapter = "recording"

    def __init__(self, pause: float = 0.0) -> None:
        self.pause = pause
        self.announced: list[ApprovalNotice] = []
        self.updated: list[tuple[MessageRef, ApprovalOutcome]] = []
        self.down_for = 0
        self.breaks_with: Exception | None = None

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        if self.pause:
            await asyncio.sleep(self.pause)
        if self.breaks_with is not None:
            raise self.breaks_with
        if self.down_for > 0:
            self.down_for -= 1
            raise DispatchFailure("Teams is down")
        self.announced.append(notice)
        return MessageRef(self.name, f"m-{notice.approval_id}", self.adapter)

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        self.updated.append((ref, outcome))


def through(h: Harness, channel: RecordingChannel) -> None:
    h.orchestrator = orchestrator_for(h, channel)


def orchestrator_for(h: Harness, channel: RecordingChannel) -> Orchestrator:
    return Orchestrator(
        h.db,
        h.log,
        h.engine,
        channel,
        h.agent,
        WriteGateway(h.db, [h.jira], poll=0.05),
        mint,
        public_base_url=PUBLIC_BASE_URL,
    )


async def digest_of(h: Harness, approval_id: ApprovalId) -> Digest:
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    return detail.request.digest


async def test_the_practice_copy_keeps_the_card_a_real_channel_gets(h: Harness):
    await People(h.db).seed_dev(DEV_PEOPLE)
    run_id, _, approval_id = await work_leg_to_approval(h)
    [message] = await h.teams.messages()
    expected = ApprovalNotice(
        run_id=run_id,
        approval_id=approval_id,
        use_case_name=SPEC.use_case_name,
        actions=(f'create a Jira ticket in MOCK titled "{TICKET_TITLE}"',),
        link=f"/approvals/{approval_id}",
        open_url=f"{PUBLIC_BASE_URL}/approvals/{approval_id}",
        summary=SUMMARY,
        lines=(f"Create Jira ticket in MOCK: {TICKET_TITLE}",),
        digest=await digest_of(h, approval_id),
        steps=(AskedStep("Team approver"),),
        not_deciding=("Alice",),
    )
    assert message.card == approval_card(expected)


@pytest.mark.parametrize(
    ("verdict", "words"),
    [(Verdict.APPROVE, "Approved by Bob"), (Verdict.DECLINE, "Declined by Bob")],
)
async def test_a_decision_shows_on_the_practice_card_as_a_bot_would_edit_it(
    h: Harness, verdict: Verdict, words: str
):
    _, _, approval_id = await work_leg_to_approval(h)
    await h.orchestrator.decide(approval_id, BOB, 0, verdict, await digest_of(h, approval_id))
    await h.orchestrator.tick()
    [message] = await h.teams.messages()
    assert message.card is not None
    assert message.card.as_json()["body"][0]["inlines"][0]["text"] == words


async def test_the_outcome_goes_to_the_message_the_announcement_posted(h: Harness):
    channel = RecordingChannel()
    through(h, channel)
    _, _, approval_id = await work_leg_to_approval(h)
    await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(h, approval_id)
    )
    await h.orchestrator.tick()
    assert channel.updated == [
        (
            MessageRef("CODESparks Ops", f"m-{approval_id}", "recording"),
            ApprovalOutcome(
                "approved",
                ("Bob",),
                SPEC.use_case_name,
                f"{PUBLIC_BASE_URL}/approvals/{approval_id}",
            ),
        )
    ]


async def test_an_outcome_waits_until_its_request_is_posted(h: Harness):
    channel = RecordingChannel()
    channel.down_for = 1
    through(h, channel)
    _, _, approval_id = await work_leg_to_approval(h)
    assert channel.announced == []
    await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(h, approval_id)
    )
    await h.orchestrator.tick()
    assert channel.updated == []
    h.advance(timedelta(seconds=10))
    await h.orchestrator.tick()
    assert [n.approval_id for n in channel.announced] == [approval_id]
    assert [outcome.verdict for _, outcome in channel.updated] == ["approved"]


async def test_the_outcome_still_reaches_teams_when_the_run_fails_after_the_yes(h: Harness):
    channel = RecordingChannel()
    through(h, channel)
    _, _, approval_id = await work_leg_to_approval(h)
    await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(h, approval_id)
    )
    await h.orchestrator.on_workflow_failure(N8nExecutionId("41"), "run", "Write", "boom")
    await h.orchestrator.tick()
    assert [leg for _, leg, _ in h.engine.legs] == [Leg.WORK]
    assert [outcome.verdict for _, outcome in channel.updated] == ["approved"]


async def test_an_adapter_that_raises_anything_cannot_stall_the_tick(h: Harness):
    channel = RecordingChannel()
    channel.breaks_with = RuntimeError("no route to https://hook.example/run?sig=s3cr3t")
    through(h, channel)
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    other = await start(h, key="key-2")
    await h.orchestrator.tick()
    assert ("run", Leg.WORK, other) in h.engine.legs
    async with h.db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT attempt, last_error FROM orchestration.outbox WHERE kind = 'announce'"
            )
        ).fetchone()
    assert row is not None
    assert (row["attempt"], row["last_error"]) == (1, "the Teams adapter failed (RuntimeError)")


async def test_a_message_posted_before_cards_reads_without_one(h: Harness):
    async with h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "INSERT INTO orchestration.teams_stub_messages "
            "(id, ts, channel, text, link, run_id, approval_id) "
            "VALUES ('tm_old', %s, 'CODESparks Ops', 'An old message.', '/approvals/apr_old', "
            "'run_old', 'apr_old')",
            (uow.now,),
        )
    [message] = await h.teams.messages()
    assert (message.card, message.text, message.run_id) == (
        None,
        "An old message.",
        RunId("run_old"),
    )


async def test_an_adapter_error_that_names_the_address_never_reaches_a_log_line(
    h: Harness, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG)
    channel = RecordingChannel()
    channel.breaks_with = RuntimeError("no route to https://hook.example/run?sig=s3cr3t")
    through(h, channel)
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    await h.orchestrator.tick()
    assert "s3cr3t" not in caplog.text and "hook.example" not in caplog.text
    failed = [r for r in caplog.records if "the Teams adapter failed" in r.getMessage()]
    assert failed and "RuntimeError" in caplog.text


async def test_two_ticks_at_once_post_each_request_once(h: Harness):
    # During a revision switch two replicas tick the same outbox.
    channel = RecordingChannel(pause=0.3)
    through(h, channel)
    other = orchestrator_for(h, channel)
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    await asyncio.gather(h.orchestrator.tick(), other.tick())
    assert len(channel.announced) == 1


async def test_a_row_a_stopped_replica_had_taken_is_sent_once_its_lease_runs_out(h: Harness):
    channel = RecordingChannel()
    through(h, channel)
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    async with h.db.transaction("orchestration") as uow:
        taken = await Store().take_due_outbox(uow, h.clock["now"])
    assert [row.kind for row in taken] == ["announce"]
    await h.orchestrator.tick()
    assert channel.announced == []
    h.advance(timedelta(minutes=2))
    await h.orchestrator.tick()
    assert len(channel.announced) == 1


async def test_an_outcome_for_a_message_another_adapter_posted_is_skipped(
    h: Harness, caplog: pytest.LogCaptureFixture
):
    # The practice copy posted the request, then the platform moved to real Teams.
    caplog.set_level(logging.INFO)
    _, _, approval_id = await work_leg_to_approval(h)
    channel = RecordingChannel()
    through(h, channel)
    await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(h, approval_id)
    )
    await h.orchestrator.tick()
    assert channel.updated == []
    async with h.db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT status, attempt FROM orchestration.outbox WHERE kind = 'show_outcome'"
            )
        ).fetchone()
    assert row is not None and (row["status"], row["attempt"]) == ("sent", 0)
    assert any("posted by practice" in r.getMessage() for r in caplog.records)


async def test_someone_not_on_the_people_list_shows_as_someone_on_this_run(h: Harness):
    # Under real sign-in an id is an Entra object id, which nobody can read.
    await work_leg_to_approval(h)
    [message] = await h.teams.messages()
    assert message.card is not None
    text = " ".join(
        run["text"] for block in message.card.as_json()["body"] for run in block.get("inlines", [])
    )
    assert "Someone on this run can’t decide, because this run is their own work." in text
    assert "alice" not in text


def test_shutting_down_closes_the_teams_webhook_client(postgres: PostgresUrls):
    truncate_all(postgres.owner)
    app = create_app(
        {**env_for(postgres), "TEAMS_WEBHOOK_URL": "https://hook.example.test/r?sig=x"}
    )
    with TestClient(app):
        webhook = app.state.teams_webhook
        assert isinstance(webhook, TeamsWorkflowsWebhook) and not webhook.closed
    assert webhook.closed


async def asking_runs(h: Harness, count: int) -> list[RunId]:
    """Runs whose approval requests are queued and not yet posted."""
    runs = [await start(h, key=f"ask-{n}") for n in range(count)]
    await h.orchestrator.tick()
    for run_id in runs:
        state = await h.state(run_id)
        assert isinstance(state, Pending) and state.claimant is not None
        await h.orchestrator.on_step(run_id, RUN_AGENTS, state.claimant)
        await h.orchestrator.on_step(run_id, ASK_APPROVAL, state.claimant)
    return runs


class SlowTeams(RecordingChannel):
    """Each post takes 40 seconds. During the second, another replica ticks."""

    def __init__(self, h: Harness) -> None:
        super().__init__()
        self.h = h
        self.posts = 0
        self.meanwhile: Callable[[], Awaitable[None]] | None = None

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        self.posts += 1
        self.h.advance(timedelta(seconds=40))
        if self.posts == 2 and self.meanwhile is not None:
            meanwhile, self.meanwhile = self.meanwhile, None
            await meanwhile()
        return await super().announce(notice)


async def test_a_slow_teams_never_lets_a_second_replica_post_a_request_twice(h: Harness):
    # Three requests taken in one tick outlast the first lease: the third is due again by the time
    # the first replica reaches it, and a second replica takes it meanwhile.
    runs = await asking_runs(h, 3)
    channel = SlowTeams(h)
    first, second = orchestrator_for(h, channel), orchestrator_for(h, channel)
    channel.meanwhile = second.tick
    await first.tick()
    posted = [n.approval_id for n in channel.announced]
    assert len(posted) == len(set(posted)) == len(runs)


async def test_a_tick_takes_at_most_a_batch_of_rows(h: Harness):
    for n in range(RETRY_POLICY.batch + 2):
        await start(h, key=f"many-{n}")
    await h.orchestrator.tick()
    assert len(h.engine.legs) == RETRY_POLICY.batch
    await h.orchestrator.tick()
    assert len(h.engine.legs) == RETRY_POLICY.batch + 2


class FirstLegBreaks:
    def __init__(self, inner: RecordingEngine) -> None:
        self.inner = inner
        self.broke = False

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        if not self.broke:
            self.broke = True
            raise RuntimeError("a bug in the engine client")
        return await self.inner.start_leg(workflow, leg, run_id)


async def test_a_row_that_raises_does_not_stop_the_rows_after_it(
    h: Harness, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.ERROR)
    h.orchestrator = Orchestrator(
        h.db,
        h.log,
        FirstLegBreaks(h.engine),
        h.teams,
        h.agent,
        WriteGateway(h.db, [h.jira], poll=0.05),
        mint,
        public_base_url=PUBLIC_BASE_URL,
    )
    first = await start(h, key="breaks")
    second = await start(h, key="after")
    await h.orchestrator.tick()
    assert [run_id for _, _, run_id in h.engine.legs] == [second]
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)
    assert isinstance(await h.state(first), Pending)


class SharedLog(RecordingChannel):
    """One replica's channel. Both replicas' channels post into one list."""

    def __init__(self, h: Harness, posted: list[ApprovalNotice], pause: float) -> None:
        super().__init__(pause=pause)
        self.h = h
        self.announced = posted
        self.posts = 0
        self.meanwhile: Callable[[], None] | None = None

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        self.posts += 1
        self.h.advance(timedelta(seconds=40))
        if self.posts == 2 and self.meanwhile is not None:
            meanwhile, self.meanwhile = self.meanwhile, None
            meanwhile()
        return await super().announce(notice)


async def test_a_row_another_replica_is_still_sending_is_left_to_it(h: Harness):
    # The second replica takes the third request while the first is on its second send, and is
    # still sending it when the first reaches it. Only the lease says whose the row is now.
    runs = await asking_runs(h, 3)
    posted: list[ApprovalNotice] = []
    first_channel = SharedLog(h, posted, pause=0.2)
    second_channel = SharedLog(h, posted, pause=1.0)
    first = orchestrator_for(h, first_channel)
    second = orchestrator_for(h, second_channel)
    started: list[asyncio.Task[None]] = []
    first_channel.meanwhile = lambda: started.append(asyncio.create_task(second.tick()))
    await first.tick()
    await asyncio.gather(*started)
    ids = [n.approval_id for n in posted]
    assert len(ids) == len(set(ids)) == len(runs)


async def test_a_row_that_raises_outside_the_adapter_is_retried_then_given_up(h: Harness):
    # A payload missing a key raises in the platform's own code, not in the adapter. It must
    # still count its tries, wait between them and give up, as any other failed send does.
    run_id, _, approval_id = await work_leg_to_approval(h)
    async with h.db.transaction("orchestration") as uow:
        await Store().enqueue(
            uow, run_id, "announce", {"run_id": run_id, "approval_id": approval_id}, uow.now
        )
    for _ in range(20):
        await h.orchestrator.tick()
        h.advance(timedelta(seconds=10))
    async with h.db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT status, attempt, last_error FROM orchestration.outbox "
                "WHERE kind = 'announce' AND NOT payload ? 'use_case_name'"
            )
        ).fetchone()
    assert row is not None
    assert (row["status"], row["attempt"]) == ("given_up", RETRY_POLICY.tries - 1)
    assert row["last_error"] == "the outbox could not send it (KeyError)"
    assert (await h.kinds(run_id))[-1] == "approval_announce_failed"
