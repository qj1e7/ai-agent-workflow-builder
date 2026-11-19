"""Set-up approvals (ADR 0051, flow steps 7 to 9): the run gate's rules, a Teams card, and the
builder's set-up once approved, each job keyed by our own request id."""

from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from platform_api.db import Database
from platform_api.orchestration.approvals import Approved, Closed, Declined, Open, Refusal, Verdict
from platform_api.orchestration.dispatch import (
    PRACTICE,
    ApprovalOutcome,
    DispatchFailure,
    MessageRef,
    RetryPolicy,
    SetUpNotice,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.setup_approvals import (
    ApprovedSetUp,
    Decided,
    DecisionRefused,
    SetUpApprovals,
    SetUpAsk,
    SetUpFinished,
    TryAgain,
)
from platform_api.shared import TEAM_TIME_ZONE, Digest, Principal, SeedPerson
from tests.support import ALICE, BOB, CAROL

pytestmark = pytest.mark.anyio

DIGEST = Digest("d" * 64)
ASK = SetUpAsk(
    drafted_id="dw_1",
    revision=1,
    digest=DIGEST,
    name="Release check",
    in_short="Every Monday at 9:00, it reads GitHub.",
    parties=frozenset({ALICE.user_id}),
    sent_by=ALICE.user_id,
)


@dataclass
class Channel:
    posted: list[SetUpNotice] = field(default_factory=list[SetUpNotice])
    updated: list[ApprovalOutcome] = field(default_factory=list[ApprovalOutcome])
    fails: bool = False

    @property
    def name(self) -> str:
        return "CODESparks Ops"

    async def announce_set_up(self, notice: SetUpNotice) -> MessageRef:
        if self.fails:
            raise DispatchFailure("Teams answered 502")
        self.posted.append(notice)
        return MessageRef("CODESparks Ops", f"msg-{notice.approval_id}", PRACTICE)

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        self.updated.append(outcome)


@dataclass
class SetUps:
    answers: list[SetUpFinished | TryAgain] = field(default_factory=list[SetUpFinished | TryAgain])
    asked: list[ApprovedSetUp] = field(default_factory=list[ApprovedSetUp])
    given_up: list[str] = field(default_factory=list[str])

    async def set_up(self, approved: ApprovedSetUp) -> SetUpFinished | TryAgain:
        self.asked.append(approved)
        return self.answers.pop(0) if self.answers else SetUpFinished()

    async def gave_up(self, approved: ApprovedSetUp, detail: str) -> None:
        self.given_up.append(detail)


@dataclass
class Lab:
    approvals: SetUpApprovals
    channel: Channel
    setups: SetUps


@pytest.fixture
async def lab(db: Database) -> Lab:
    seed = [
        SeedPerson(p.user_id, f"{p.user_id}@example.test", p.display, p.roles)
        for p in (ALICE, BOB, CAROL)
    ]
    people = People(db)
    assert await people.seed_dev(seed)
    channel, setups = Channel(), SetUps()
    approvals = SetUpApprovals(
        db,
        channel,
        people,
        "https://portal.example",
        TEAM_TIME_ZONE,
        RetryPolicy(delays=(timedelta(seconds=1),)),
    )
    approvals.serve(setups)
    return Lab(approvals, channel, setups)


async def test_a_sent_revision_is_posted_in_teams_with_who_can_t_decide(lab: Lab):
    request = await lab.approvals.send(ASK)
    await lab.approvals.work_once()

    [notice] = lab.channel.posted
    assert notice.approval_id == request.id
    assert notice.open_url == f"https://portal.example/setup-approvals/{request.id}"
    assert (notice.sent_by, notice.not_deciding) == ("Alice", ("Alice",))
    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.post == "sent"
    assert isinstance(state.status, Open)


async def test_only_an_approver_who_may_decide_it_sees_it_waiting_for_them(lab: Lab):
    """Needs you and the Teams button count the set-up approvals each person may decide."""
    request = await lab.approvals.send(ASK)

    assert [s.request.id for s in await lab.approvals.waiting_for(BOB)] == [request.id]
    assert await lab.approvals.waiting_for(ALICE) == [], "a party never may"
    assert await lab.approvals.waiting_for(CAROL) == [], "nor someone who is no Approver"
    await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, DIGEST, None)
    assert await lab.approvals.waiting_for(BOB) == []


async def test_sending_the_same_revision_again_answers_the_same_request(lab: Lab):
    first = await lab.approvals.send(ASK)

    assert (await lab.approvals.send(ASK)).id == first.id


@pytest.mark.parametrize(
    ("who", "refusal"),
    [(ALICE, Refusal.OWN_WORK), (CAROL, Refusal.NOT_AN_APPROVER)],
)
async def test_a_party_or_someone_who_is_not_an_approver_can_t_decide(
    lab: Lab, who: Principal, refusal: Refusal
):
    request = await lab.approvals.send(ASK)

    decided = await lab.approvals.decide(request.id, who, Verdict.APPROVE, DIGEST, None)

    assert decided == DecisionRefused(refusal)


async def test_a_yes_on_another_digest_is_refused(lab: Lab):
    request = await lab.approvals.send(ASK)

    decided = await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, Digest("x"), None)

    assert decided == DecisionRefused(Refusal.STALE_DIGEST)


async def test_one_approver_s_yes_sets_the_approved_digest_up_and_shows_it_in_teams(lab: Lab):
    request = await lab.approvals.send(ASK)

    decided = await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, DIGEST, None)
    await lab.approvals.work_once()

    assert isinstance(decided, Decided) and decided.status == Approved((BOB.user_id,))
    [asked] = lab.setups.asked
    assert (asked.approval_id, asked.digest, asked.approvers) == (
        request.id,
        DIGEST,
        (BOB.user_id,),
    )
    [outcome] = lab.channel.updated
    assert (outcome.verdict, outcome.by) == ("approved", ("Bob",))
    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.set_up == "done"


async def test_a_decline_keeps_its_reason_and_sets_nothing_up(lab: Lab):
    request = await lab.approvals.send(ASK)

    await lab.approvals.decide(request.id, BOB, Verdict.DECLINE, DIGEST, "Not needed")
    await lab.approvals.work_once()

    assert lab.setups.asked == []
    [outcome] = lab.channel.updated
    assert (outcome.verdict, outcome.reason, outcome.nothing) == (
        "declined",
        "Not needed",
        "Nothing was set up.",
    )
    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.status == Declined(BOB.user_id, 0)


async def test_a_new_revision_replaces_a_request_that_still_waits(lab: Lab):
    request = await lab.approvals.send(ASK)
    await lab.approvals.work_once()

    await lab.approvals.replace_waiting("dw_1")
    decided = await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, DIGEST, None)
    await lab.approvals.work_once()

    assert decided == DecisionRefused(Refusal.NOT_OPEN)
    assert [o.verdict for o in lab.channel.updated] == ["replaced"]
    assert lab.setups.asked == []


async def test_sending_another_revision_replaces_the_one_that_waits(lab: Lab):
    first = await lab.approvals.send(ASK)
    second = await lab.approvals.send(
        SetUpAsk(**{**ASK.__dict__, "revision": 2, "digest": Digest("e" * 64)})
    )

    state = await lab.approvals.get(first.id)
    assert second.id != first.id
    assert state is not None and isinstance(state.status, Closed)


async def test_a_request_nobody_answers_in_two_working_days_expires(lab: Lab, db: Database):
    request = await lab.approvals.send(ASK)
    assert request.expires_at is not None

    await lab.approvals.work_once(request.expires_at + timedelta(seconds=1))

    state = await lab.approvals.get(request.id)
    assert state is not None and isinstance(state.status, Closed)
    decided = await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, DIGEST, None)
    assert decided == DecisionRefused(Refusal.NOT_OPEN)


async def test_a_set_up_n8n_did_not_take_is_tried_again_then_given_up_and_can_be_asked_again(
    lab: Lab, db: Database
):
    lab.setups.answers = [TryAgain("n8n answered 503"), TryAgain("n8n answered 503")]
    request = await lab.approvals.send(ASK)
    await lab.approvals.decide(request.id, BOB, Verdict.APPROVE, DIGEST, None)

    await lab.approvals.work_once()
    await lab.approvals.work_once(db.clock() + timedelta(seconds=5))

    assert lab.setups.given_up == ["n8n answered 503"]
    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.set_up == "failed"
    assert await lab.approvals.set_up_again(request.id)
    await lab.approvals.work_once(db.clock() + timedelta(seconds=10))
    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.set_up == "done"


async def test_a_post_teams_did_not_take_shows_as_failed(lab: Lab, db: Database):
    lab.channel.fails = True
    await lab.approvals.send(ASK)

    await lab.approvals.work_once()
    await lab.approvals.work_once(db.clock() + timedelta(seconds=5))

    state = await lab.approvals.latest("dw_1")
    assert state is not None and state.post == "failed"
