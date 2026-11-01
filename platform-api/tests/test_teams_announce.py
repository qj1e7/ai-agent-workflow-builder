from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.dispatch import (
    ApprovalNotice,
    ApprovalOutcome,
    AskedStep,
    DispatchFailure,
    MessageRef,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.runs import Leg
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.teams import approval_card
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.shared import ApprovalId, Digest, N8nExecutionId, RunId
from tests.conftest import PostgresUrls
from tests.support import BOB, SPEC, SUMMARY, TICKET_TITLE
from tests.test_orchestrator import (
    ASK_APPROVAL,
    PUBLIC_BASE_URL,
    RUN_AGENTS,
    Harness,
    mint,
    open_harness,
    start,
    work_leg_to_approval,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as harness:
        yield harness


class RecordingChannel:
    name = "CODESparks Ops"

    def __init__(self) -> None:
        self.announced: list[ApprovalNotice] = []
        self.updated: list[tuple[MessageRef, ApprovalOutcome]] = []
        self.down_for = 0
        self.breaks_with: Exception | None = None

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        if self.breaks_with is not None:
            raise self.breaks_with
        if self.down_for > 0:
            self.down_for -= 1
            raise DispatchFailure("Teams is down")
        self.announced.append(notice)
        return MessageRef(self.name, f"m-{notice.approval_id}")

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        self.updated.append((ref, outcome))


def through(h: Harness, channel: RecordingChannel) -> None:
    h.orchestrator = Orchestrator(
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
            MessageRef("CODESparks Ops", f"m-{approval_id}"),
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
