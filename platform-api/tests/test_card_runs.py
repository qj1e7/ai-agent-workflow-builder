"""A run of agent cards through the orchestrator: the request, the review, and the binding."""

from collections.abc import AsyncIterator

import pytest

from platform_api.orchestration import AnyApprover, ApprovalPolicy
from platform_api.orchestration.agents import (
    CardBlock,
    CardInput,
    CardsInputs,
    CardSpec,
    CarryForward,
    ProposedIntentIn,
    TaskOutput,
)
from platform_api.orchestration.cards import card_bindings, cards_policy
from platform_api.orchestration.runs import AwaitingApproval, Failed, FailureReason, StepName
from platform_api.orchestration.spec import CardRun, CardsTask, RunSpec
from platform_api.shared import N8nExecutionId, UseCaseId, UserId
from tests.conftest import PostgresUrls
from tests.support import ALICE
from tests.test_orchestrator import Harness, open_harness

pytestmark = pytest.mark.anyio

WORK = N8nExecutionId("41")


def card(card_id: str, name: str) -> CardSpec:
    return CardSpec(
        id=card_id,
        version=1,
        name=name,
        purpose="Checks.",
        inputs=[CardInput(name="Project", kind="jira_project")],
        blocks=[
            CardBlock(say="Read.", tool="github.read_releases"),
            CardBlock(say="Raise.", tool="jira.create_ticket"),
        ],
    )


def spec(*projects: str, approvers: int = 1) -> RunSpec:
    cards = [card(f"crd_{n}", f"Agent {n}") for n in range(len(projects))]
    runs = tuple(
        CardRun(c, {"Project": p}, card_bindings(c, {"Project": p}))
        for c, p in zip(cards, projects, strict=True)
    )
    return RunSpec(
        use_case_id=UseCaseId("uc_cards"),
        use_case_version=1,
        use_case_name="Cards",
        owner=UserId("alice"),
        workflow="release_check",
        instruction="Check things.",
        task=CardsTask(runs),
        bindings={},
        approval_policy=cards_policy([r.card for r in runs], approvers),
    )


def ticket(subject: str | None, title: str = "New release", **fields: object) -> ProposedIntentIn:
    return ProposedIntentIn(
        kind="jira.create_ticket",
        fields={"title": title, "body": "Details.", **fields},
        reason="A release.",
        subject=subject,
    )


def output(*proposed: ProposedIntentIn) -> TaskOutput:
    return TaskOutput(
        summary="Two releases.", new_tags=[], proposed=list(proposed), carry_forward=CarryForward()
    )


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as harness:
        yield harness


async def run_work(h: Harness, run_spec: RunSpec):
    started = await h.orchestrator.start_run(run_spec, ALICE, "k")
    await h.orchestrator.tick()
    reply = await h.orchestrator.on_step(started.run_id, StepName.RUN_AGENTS, WORK)
    return started.run_id, reply


async def test_the_runtime_is_asked_for_the_cards_and_values_of_the_run(h: Harness):
    h.agent.output = output()
    await run_work(h, spec("AAA", "BBB"))
    [request] = h.agent.requests
    assert isinstance(request.inputs, CardsInputs)
    assert [(a.card.id, a.values) for a in request.inputs.agents] == [
        ("crd_0", {"Project": "AAA"}),
        ("crd_1", {"Project": "BBB"}),
    ]
    assert request.carry_forward == CarryForward()
    assert request.model is None


async def test_each_ticket_is_bound_to_its_own_cards_project_in_the_order_proposed(h: Harness):
    h.agent.output = output(ticket("crd_1", "For B"), ticket("crd_0", "For A"))
    run_id, reply = await run_work(h, spec("AAA", "BBB"))
    assert (reply.proceed, reply.outcome) == (True, "proposed")
    detail = await h.orchestrator.get_run(run_id)
    assert detail is not None and detail.proposal is not None
    assert [(a.target["project"], a.fields["title"]) for a in detail.proposal.actions] == [
        ("BBB", "For B"),
        ("AAA", "For A"),
    ]
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    state = (await h.orchestrator.get_run(run_id)).record.state  # pyright: ignore[reportOptionalMemberAccess]
    assert isinstance(state, AwaitingApproval)


async def test_a_planted_project_in_the_fields_fails_the_run_and_nothing_is_proposed(h: Harness):
    h.agent.output = output(ticket("crd_0", project="SECRET"))
    run_id, reply = await run_work(h, spec("AAA"))
    assert (reply.proceed, reply.outcome) == (False, "failed")
    detail = await h.orchestrator.get_run(run_id)
    assert detail is not None and detail.proposal is None
    state = detail.record.state
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.AGENT_ERROR and not state.failure.retryable


@pytest.mark.parametrize(
    "proposed",
    [
        [ticket("crd_other")],
        [ticket(None)],
        [ProposedIntentIn(kind="jira.search", fields={}, reason="x", subject="crd_0")],
        [
            ProposedIntentIn(
                kind="create_ticket", fields={"title": "t", "body": ""}, reason="x", subject="crd_0"
            )
        ],
        [ticket("crd_0")] * 11,
    ],
)
async def test_each_refused_proposal_fails_the_run_without_a_retry(
    h: Harness, proposed: list[ProposedIntentIn]
):
    h.agent.output = output(*proposed)
    run_id, reply = await run_work(h, spec("AAA"))
    assert reply.outcome == "failed"
    state = (await h.orchestrator.get_run(run_id)).record.state  # pyright: ignore[reportOptionalMemberAccess]
    assert isinstance(state, Failed) and not state.failure.retryable


async def test_no_proposals_is_a_run_with_nothing_to_write(h: Harness):
    h.agent.output = output()
    _, reply = await run_work(h, spec("AAA"))
    assert reply.outcome == "nothing_to_write"


async def test_two_approvers_open_two_steps_and_the_second_cannot_be_the_first(h: Harness):
    h.agent.output = output(ticket("crd_0"))
    run_id, _ = await run_work(h, spec("AAA", approvers=2))
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    detail = await h.orchestrator.get_run(run_id)
    assert detail is not None
    assert [s.label for s in detail.record.spec.approval_policy.steps] == [
        "Team approver",
        "Second approver",
    ]
    assert all(
        isinstance(s.eligible, AnyApprover) for s in detail.record.spec.approval_policy.steps
    )
    assert isinstance(detail.record.spec.approval_policy, ApprovalPolicy)


async def test_the_spec_round_trips_through_the_store(h: Harness):
    h.agent.output = output()
    run_id, _ = await run_work(h, spec("AAA", "BBB"))
    detail = await h.orchestrator.get_run(run_id)
    assert detail is not None
    assert detail.record.spec == spec("AAA", "BBB")
