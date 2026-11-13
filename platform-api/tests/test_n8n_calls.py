from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

import pytest

from platform_api.orchestration.agents import (
    CardBlock,
    CardInput,
    CardSpec,
    CarryForward,
    ProposedIntentIn,
    TaskOutput,
)
from platform_api.orchestration.cards import card_bindings
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.n8n_call_book import CallBook
from platform_api.orchestration.n8n_call_service import NodeCalls
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    NOBODY_HOLDS,
    NOT_OURS,
    START_EXPIRED,
    START_LIFETIME,
    START_OTHER_WORKFLOW,
    START_UNKNOWN,
    START_USED,
    UNKNOWN_PUBLISHER,
    UNKNOWN_START,
    VERSION_FAILED,
    AgentCall,
    Answer,
    ExecutionFacts,
    IssuedStart,
    NodeCall,
    NodeCatalog,
    NodeOption,
    OwnWorkflow,
    ProposeCall,
    Publisher,
    RanVersion,
    ReadCall,
    ReadFailed,
    ReadItems,
    Refused,
    TryLater,
    Work,
    WriteEntry,
    check_start,
    start_signature,
)
from platform_api.orchestration.runs import (
    DEADLINES,
    AwaitingApproval,
    Failed,
    FailureReason,
    Pending,
    Skipped,
    Working,
    working_on,
)
from platform_api.orchestration.spec import CardRun
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import ApprovalId, N8nExecutionId, ProposalId, RunId, UserId
from tests.conftest import PostgresUrls
from tests.support import NOW, SPEC
from tests.test_orchestrator import Harness, mint, open_harness

pytestmark = pytest.mark.anyio

WORKFLOW = "wf_7"
OTHER_WORKFLOW = "wf_8"
ALICE, BOB, DAVE = UserId("alice"), UserId("bob"), UserId("dave")
REPO = "langchain-ai/langgraph"
RELEASE = {"kind": "release", "id": "1.2.16", "tag": "1.2.16"}
CARD = CardSpec(
    id="crd_compare",
    version=1,
    name="Compare",
    purpose="Compares releases.",
    inputs=[CardInput(name="Project", kind="jira_project")],
    blocks=[
        CardBlock(say="Read.", tool="github.read_releases"),
        CardBlock(say="Raise.", tool="jira.create_ticket"),
    ],
)
CARD_RUN = CardRun(CARD, {"Project": "MOCK"}, card_bindings(CARD, {"Project": "MOCK"}))
JIRA = WriteEntry(
    "jira.create_ticket",
    "Create a Jira ticket",
    "jira",
    "create_ticket",
    "project",
    (NodeOption("MOCK", "MOCK"),),
)
SAFE_BY_ALICE = RanVersion("safe", Publisher(ALICE))


@dataclass
class FakeN8n:
    executions: dict[str, ExecutionFacts] = field(default_factory=dict[str, ExecutionFacts])

    async def execution(self, execution_id: N8nExecutionId) -> ExecutionFacts | None:
        return self.executions.get(execution_id)


@dataclass
class FakeWorkflows:
    holder: UserId | None = None
    versions: dict[str, RanVersion] = field(default_factory=lambda: {"v1": SAFE_BY_ALICE})

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | None:
        if n8n_workflow_id not in (WORKFLOW, OTHER_WORKFLOW):
            return None
        return OwnWorkflow(SPEC, self.holder)

    async def version(self, n8n_workflow_id: str, version_id: str) -> RanVersion | None:
        return self.versions.get(version_id)

    async def agents(self) -> Sequence[NodeOption]:
        return [NodeOption(CARD.id, CARD.name)]

    async def agent_inputs(self, agent_id: str) -> Sequence[CardInput]:
        return CARD.inputs if agent_id == CARD.id else []

    async def agent_run(self, agent_id: str, values: Mapping[str, str]) -> CardRun | None:
        return CARD_RUN if agent_id == CARD.id else None


@dataclass
class FakeSources:
    items: list[dict[str, Any]] = field(default_factory=lambda: [RELEASE])
    down: bool = False
    reads: list[tuple[str, str, str | None]] = field(
        default_factory=list[tuple[str, str, str | None]]
    )

    async def places(self, source: str) -> Sequence[NodeOption]:
        return [NodeOption(REPO, "LangGraph")] if source == "github_releases" else []

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed:
        self.reads.append((source, place, query))
        return ReadFailed("GitHub did not answer") if self.down else self.items


@dataclass
class Calls:
    h: Harness
    n8n: FakeN8n
    workflows: FakeWorkflows
    sources: FakeSources
    calls: NodeCalls

    def started(
        self,
        execution: str,
        mode: str = "trigger",
        *,
        retry_of: str | None = None,
        nonce: str | None = None,
        version: str | None = "v1",
        workflow: str = WORKFLOW,
    ) -> None:
        self.n8n.executions[execution] = ExecutionFacts(
            workflow,
            mode,
            None if retry_of is None else N8nExecutionId(retry_of),
            nonce,
            version,
        )

    async def call(
        self, execution: str, work: Work | None = None, node: str = "Read release"
    ) -> object:
        work = work or ReadCall("github_releases", REPO, None)
        return await self.calls.call(NodeCall(N8nExecutionId(execution), node, work))

    async def runs(self) -> list[RunRecord]:
        async with self.h.db.transaction("orchestration") as uow:
            return await Store().list_runs(uow)

    async def only_run(self) -> RunRecord:
        [run] = await self.runs()
        return run

    async def kinds(self, run_id: RunId) -> list[str]:
        return await self.h.kinds(run_id)

    async def pending_run(self, run_id: str = "run_portal") -> RunId:
        run = RunId(run_id)
        record = RunRecord(run, SPEC, BOB, NOW, NOW, 1, Pending(run, 1, None, NOW), (), None)
        async with self.h.db.transaction("orchestration") as uow:
            await Store().insert_run(uow, record, f"portal:{run_id}")
        return run

    async def node_calls(self) -> list[dict[str, Any]]:
        async with self.h.db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT execution_id, node_name, run_id, outcome, attempts, status, actions "
                    "FROM orchestration.node_calls ORDER BY execution_id, node_name"
                )
            ).fetchall()
        return [dict(row) for row in rows]


@pytest.fixture
async def t(postgres: PostgresUrls) -> AsyncIterator[Calls]:
    async with open_harness(postgres) as h:
        n8n, workflows, sources = FakeN8n(), FakeWorkflows(), FakeSources()
        calls = NodeCalls(
            h.db,
            h.log,
            h.agent,
            mint,
            NodeCatalog(workflows, sources, [JIRA]),
            workflows,
            n8n,
            sources,
            {"jira": PRACTICE_SITE},
            start_secret="test-start-secret",
        )
        yield Calls(h, n8n, workflows, sources, calls)


async def test_a_scheduled_first_call_makes_a_run_of_the_publisher_and_reads(t: Calls):
    t.started("101")
    assert await t.call("101") == Answer((RELEASE,))
    run = await t.only_run()
    assert (run.started_by, run.spec.trigger) == (ALICE, "schedule")
    assert run.state == working_on(run.run_id, N8nExecutionId("101"), 1, NOW)
    assert await t.kinds(run.run_id) == ["run_created", "execution_linked"]
    assert t.sources.reads == [("github_releases", REPO, None)]


async def test_a_webhook_execution_without_a_start_is_refused_and_credited_to_nobody(t: Calls):
    """Run now and our Start from the Portal arrive as webhook, and each carries a start our API
    issued. Only the Schedule Trigger's run is credited to the publisher."""
    t.started("101", "webhook")
    assert await t.call("101") == UNKNOWN_START
    assert await t.runs() == []
    assert t.sources.reads == []


@pytest.mark.parametrize(
    ("work", "refused"),
    [
        pytest.param(
            ReadCall("github_releases", "evil/repo", None),
            'Our platform does not know the place "evil/repo".',
            id="read-place",
        ),
        pytest.param(
            ReadCall("confluence_page", "123", None),
            'Our platform does not know the place "123".',
            id="read-source",
        ),
        pytest.param(
            AgentCall("crd_unknown", {}),
            'Our platform does not know the agent "crd_unknown".',
            id="agent",
        ),
        pytest.param(
            ProposeCall("http.request", "MOCK", "t", "b", None),
            'Our platform does not know the change "http.request".',
            id="propose-action",
        ),
        pytest.param(
            ProposeCall("jira.create_ticket", "PROD", "t", "b", None),
            'Our platform does not know the place "PROD".',
            id="propose-place",
        ),
        pytest.param(
            AgentCall(CARD.id, {"Project": "PROD"}),
            'Our platform does not know the place "PROD".',
            id="agent-write-target",
        ),
        pytest.param(
            AgentCall(CARD.id, {"Project": "MOCK", "Repo": "evil/repo"}),
            'Our platform does not know the input "Repo".',
            id="agent-input",
        ),
    ],
)
async def test_an_unknown_option_id_is_refused_and_nothing_is_read_run_or_proposed(
    t: Calls, work: Work, refused: str
):
    t.started("101")
    assert await t.call("101", work) == Refused(422, refused)
    assert t.sources.reads == []
    assert t.h.agent.requests == []
    [row] = await t.node_calls()
    run = await t.only_run()
    assert (row["run_id"], row["outcome"], row["actions"]) == (run.run_id, "refused", [])


async def test_nothing_is_kept_for_an_execution_n8n_does_not_know(t: Calls):
    """The catalog is asked only once n8n vouches for the execution, so a caller with the node
    key alone leaves no row behind, whatever it names."""
    unknown_place = ReadCall("github_releases", "evil/repo", None)
    assert isinstance(await t.call("999", unknown_place), TryLater)
    assert await t.node_calls() == []
    assert await t.runs() == []


async def test_a_repeat_of_a_block_with_other_content_is_refused_and_changes_nothing(t: Calls):
    t.started("101")
    first = await t.call("101")
    other_place = ReadCall("github_releases", "langchain-ai/langchain", None)
    changed = Refused(409, "This block already called with other content in this execution.")
    assert await t.call("101", other_place) == changed
    assert await t.call("101", AgentCall(CARD.id, {})) == changed, "another kind, same name"
    [row] = await t.node_calls()
    assert (row["outcome"], row["attempts"]) == ("answered", 1)
    assert await t.call("101") == replace(first, replayed=True)  # type: ignore[arg-type]
    assert len(t.sources.reads) == 1


async def test_a_refusal_n8n_repeats_gets_the_same_answer_and_is_kept_once(t: Calls):
    t.started("101")
    unknown_place = ReadCall("github_releases", "evil/repo", None)
    first = await t.call("101", unknown_place)
    assert await t.call("101", unknown_place) == first
    assert await t.call("101", unknown_place) == first
    [row] = await t.node_calls()
    assert (row["outcome"], row["status"], row["attempts"]) == ("refused", 422, 3)


async def test_a_run_while_an_earlier_one_waits_for_a_yes_is_skipped(t: Calls):
    waiting = RunId("run_waiting")
    state = AwaitingApproval(waiting, ProposalId("prp_w"), ApprovalId("apr_w"))
    async with t.h.db.transaction("orchestration") as uow:
        await Store().insert_run(
            uow, RunRecord(waiting, SPEC, ALICE, NOW, NOW, 1, state, (), None), "earlier"
        )
    t.started("101")
    assert await t.call("101") == Answer(())
    [skipped] = [run for run in await t.runs() if run.run_id != waiting]
    assert skipped.state == Skipped(skipped.run_id, waiting)
    assert await t.kinds(skipped.run_id) == ["run_created", "execution_linked", "run_skipped"]
    assert t.sources.reads == []
    assert await t.call("101", node="Compare", work=AgentCall(CARD.id, {})) == Answer(())
    assert t.h.agent.requests == [], "a skipped run runs no agent either"


async def test_a_version_published_by_someone_we_dont_know_stops_before_anything_runs(t: Calls):
    t.workflows.versions["v2"] = RanVersion("safe", Publisher(None))
    t.started("101", version="v2")
    assert await t.call("101") == UNKNOWN_PUBLISHER
    assert await t.runs() == []
    assert t.sources.reads == []


@pytest.mark.parametrize(
    "version",
    [
        pytest.param(RanVersion("needs_a_fix", Publisher(ALICE)), id="failed-the-check"),
        pytest.param(None, id="not-checked-yet"),
    ],
)
async def test_a_version_that_did_not_pass_the_check_stops_before_reading(
    t: Calls, version: RanVersion | None
):
    if version is not None:
        t.workflows.versions["v2"] = version
    t.started("101", version="v2")
    assert await t.call("101") == VERSION_FAILED
    assert await t.runs() == []
    assert t.sources.reads == []


async def test_writes_refused_still_runs_so_the_gateway_can_refuse_the_write(t: Calls):
    t.workflows.versions["v2"] = RanVersion("writes_refused", Publisher(ALICE))
    t.started("101", version="v2")
    assert await t.call("101") == Answer((RELEASE,))


async def test_a_workflow_that_is_not_ours_is_refused(t: Calls):
    t.started("101", workflow="wf_someone_elses")
    assert await t.call("101") == NOT_OURS
    assert await t.runs() == []


async def test_a_run_by_hand_is_the_holders_and_refused_when_nobody_holds_it(t: Calls):
    t.started("101", "manual")
    assert await t.call("101") == NOBODY_HOLDS
    assert await t.runs() == []
    t.workflows.holder = DAVE
    t.started("102", "manual")
    assert await t.call("102") == Answer((RELEASE,))
    run = await t.only_run()
    assert (run.started_by, run.spec.trigger) == (DAVE, "person")
    assert DAVE in run.parties


async def test_a_start_links_the_pending_run_it_was_issued_for_and_is_used_once(t: Calls):
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    t.started("101", "webhook", nonce=str(start.body["nonce"]))
    assert await t.call("101") == Answer((RELEASE,))
    run = await t.only_run()
    assert (run.run_id, run.started_by) == (run_id, BOB)
    assert isinstance(run.state, Working) and run.state.execution == "101"


async def test_a_replayed_start_is_refused_and_starts_nothing(t: Calls):
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    nonce = str(start.body["nonce"])
    t.started("101", "webhook", nonce=nonce)
    t.started("102", "webhook", nonce=nonce)
    await t.call("101")
    assert await t.call("102") == START_USED
    [run] = await t.runs()
    assert isinstance(run.state, Working) and run.state.execution == "101"
    assert len(t.sources.reads) == 1


def test_a_start_used_once_is_refused_by_our_own_record():
    used = IssuedStart("start_1", RunId("run_1"), "run_now", WORKFLOW, NOW, N8nExecutionId("101"))
    assert check_start(used, WORKFLOW, NOW) == START_USED
    assert check_start(replace(used, used_by=None), WORKFLOW, NOW) == replace(used, used_by=None)


async def test_only_one_execution_can_use_a_start(t: Calls):
    run_id = await t.pending_run()
    async with t.h.db.transaction("orchestration") as uow:
        start = await CallBook().issue_start(uow, run_id, "run_now", WORKFLOW)
        assert await CallBook().use_start(uow, start.nonce, N8nExecutionId("101"))
        assert not await CallBook().use_start(uow, start.nonce, N8nExecutionId("102"))


async def test_a_forged_start_is_refused_and_never_taken_for_a_trigger(t: Calls):
    t.started("101", "webhook", nonce="start_made_up")
    assert await t.call("101") == START_UNKNOWN
    assert await t.runs() == []


async def test_a_start_made_for_another_workflow_is_refused_and_stays_unused(t: Calls):
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    nonce = str(start.body["nonce"])
    t.started("101", "webhook", nonce=nonce, workflow=OTHER_WORKFLOW)
    assert await t.call("101") == START_OTHER_WORKFLOW
    assert isinstance((await t.only_run()).state, Pending)
    t.started("102", "webhook", nonce=nonce)
    assert await t.call("102") == Answer((RELEASE,)), "its own workflow can still use it"


async def test_an_expired_start_is_refused(t: Calls):
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    t.h.advance(START_LIFETIME + timedelta(seconds=1))
    t.started("101", "webhook", nonce=str(start.body["nonce"]))
    assert await t.call("101") == START_EXPIRED


async def test_a_start_for_a_version_that_failed_the_check_stops_its_pending_run(t: Calls):
    t.workflows.versions["v2"] = RanVersion("needs_a_fix", Publisher(ALICE))
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    t.started("101", "webhook", nonce=str(start.body["nonce"]), version="v2")
    assert await t.call("101") == VERSION_FAILED
    run = await t.only_run()
    assert isinstance(run.state, Failed)
    assert run.state.failure.reason is FailureReason.SAFETY_DENIED
    assert not run.state.failure.retryable
    assert t.sources.reads == []


async def test_a_retry_joins_its_original_run_and_gets_the_blocks_earlier_answers(t: Calls):
    t.workflows.holder = DAVE
    t.started("101")
    await t.call("101")
    t.h.advance(DEADLINES[Working] + timedelta(seconds=1))
    await t.h.orchestrator.tick()
    run = await t.only_run()
    assert isinstance(run.state, Failed) and run.state.failure.retryable
    t.started("102", "retry", retry_of="101")
    assert await t.call("102") == Answer((RELEASE,), replayed=True)
    joined = await t.only_run()
    assert joined.run_id == run.run_id
    assert isinstance(joined.state, Working) and joined.state.execution == "102"
    assert DAVE in joined.parties, "the holder joins the run they retried in n8n"
    assert len(t.sources.reads) == 1, "the retry never reads twice"
    assert await t.call("101", node="Compare", work=AgentCall(CARD.id, {})) == ANOTHER_EXECUTION


async def stopped_on_timeout(t: Calls) -> None:
    t.started("101")
    await t.call("101")
    t.h.advance(DEADLINES[Working] + timedelta(seconds=1))
    await t.h.orchestrator.tick()


async def test_a_retry_carries_no_version_of_its_own_and_runs_on_its_originals(t: Calls):
    await stopped_on_timeout(t)
    t.started("102", "retry", retry_of="101", version=None)
    assert await t.call("102") == Answer((RELEASE,), replayed=True)


async def test_a_retry_of_a_version_since_graded_failed_is_refused(t: Calls):
    await stopped_on_timeout(t)
    t.workflows.versions["v1"] = RanVersion("needs_a_fix", Publisher(ALICE))
    t.started("102", "retry", retry_of="101", version=None)
    assert await t.call("102", node="Compare", work=AgentCall(CARD.id, {})) == VERSION_FAILED
    assert isinstance((await t.only_run()).state, Failed)


async def test_a_retry_of_a_stop_that_cannot_be_retried_is_refused(t: Calls):
    t.workflows.versions["v2"] = RanVersion("needs_a_fix", Publisher(ALICE))
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "run_now", WORKFLOW, "hook-1")
    t.started("101", "webhook", nonce=str(start.body["nonce"]), version="v2")
    await t.call("101")
    t.workflows.versions["v2"] = SAFE_BY_ALICE
    t.started("102", "retry", retry_of="101", version="v2")
    refused = await t.call("102")
    assert isinstance(refused, Refused) and refused.status == 409
    assert isinstance((await t.only_run()).state, Failed)


async def test_a_repeated_call_gets_its_first_answer_and_reads_once(t: Calls):
    t.started("101")
    first = await t.call("101")
    assert await t.call("101") == replace(first, replayed=True)  # type: ignore[arg-type]
    assert len(t.sources.reads) == 1
    [row] = await t.node_calls()
    assert (row["outcome"], row["attempts"]) == ("answered", 2)


async def test_each_call_moves_the_working_deadline_on(t: Calls):
    t.started("101")
    await t.call("101")
    t.h.advance(timedelta(minutes=5))
    await t.call(
        "101", node="Propose", work=ProposeCall("jira.create_ticket", "MOCK", "t", "b", None)
    )
    t.h.advance(timedelta(minutes=5))
    await t.h.orchestrator.tick()
    run = await t.only_run()
    assert isinstance(run.state, Working), "ten minutes in, but five since the last call"
    assert run.state.deadline_at == NOW + timedelta(minutes=5) + DEADLINES[Working]


async def test_a_read_that_fails_is_tried_again_and_reads_once_it_answers(t: Calls):
    t.started("101")
    t.sources.down = True
    assert await t.call("101") == TryLater("GitHub did not answer")
    t.sources.down = False
    assert await t.call("101") == Answer((RELEASE,))


async def test_a_read_passes_on_at_most_the_cap_and_says_it_stopped_there(t: Calls):
    t.sources.items = [{"id": str(n)} for n in range(150)]
    t.started("101")
    answer = await t.call("101")
    assert isinstance(answer, Answer)
    assert (len(answer.items), answer.cut_off) == (100, True)


async def test_an_agent_block_runs_its_card_and_keeps_the_changes_it_proposes(t: Calls):
    t.h.agent.output = TaskOutput(
        summary="LangGraph 1.2.16 is out.",
        new_tags=[],
        proposed=[
            ProposedIntentIn(
                kind="jira.create_ticket",
                fields={"title": "Upgrade LangGraph", "body": "1.2.16 is out."},
                reason="newer",
                subject=CARD.id,
            )
        ],
        carry_forward=CarryForward(),
    )
    t.started("101")
    answer = await t.call("101", AgentCall(CARD.id, {"Project": "MOCK"}), node="Compare")
    assert answer == Answer(({"summary": "LangGraph 1.2.16 is out.", "findings": []},))
    [request] = t.h.agent.requests
    assert [a.card.id for a in request.inputs.agents] == [CARD.id]  # type: ignore[union-attr]
    [row] = await t.node_calls()
    assert row["actions"] == [
        {
            "connector": "jira",
            "operation": "create_ticket",
            "target": {"project": "MOCK", "site": PRACTICE_SITE.identity},
            "fields": {"title": "Upgrade LangGraph", "body": "1.2.16 is out."},
            "subject": None,
        }
    ]


async def test_an_agent_that_fails_stops_the_run_and_its_repeat_gets_the_same_words(t: Calls):
    t.h.agent.mode = "failed"
    t.started("101")
    stopped = await t.call("101", AgentCall(CARD.id, {}), node="Compare")
    assert isinstance(stopped, Refused) and stopped.status == 409
    run = await t.only_run()
    assert isinstance(run.state, Failed) and run.state.failure.reason is FailureReason.AGENT_ERROR
    assert await t.call("101", AgentCall(CARD.id, {}), node="Compare") == stopped
    assert len(t.h.agent.requests) == 1


async def test_a_propose_block_adds_one_change_at_an_allowed_place(t: Calls):
    t.started("101")
    work = ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "Body.", "langgraph")
    assert await t.call("101", work, node="Propose a change") == Answer(())
    [row] = await t.node_calls()
    assert row["actions"] == [
        {
            "connector": "jira",
            "operation": "create_ticket",
            "target": {"project": "MOCK", "site": PRACTICE_SITE.identity},
            "fields": {"title": "Upgrade LangGraph", "body": "Body."},
            "subject": "langgraph",
        }
    ]


async def test_n8n_with_no_record_of_the_execution_yet_is_asked_again(t: Calls):
    assert isinstance(await t.call("101"), TryLater)
    assert await t.node_calls() == []


async def test_a_signed_start_lives_240_seconds_and_is_signed_as_the_block_checks():
    """The vector comes from Node's crypto, as the Start from the Portal block computes it."""
    assert start_signature(
        "test-start-secret", "wf_7", "hook-1", "start_abc", "run_now", 1793680800
    ) == ("3b3c11d837ae6b9f48c4a5b0d49b09bb8b88657677d22a947fa21c9420ed366c")
    assert timedelta(seconds=240) == START_LIFETIME


async def test_an_issued_start_expires_240_seconds_on_and_carries_its_signature(t: Calls):
    run_id = await t.pending_run()
    start = await t.calls.issue_start(run_id, "test", WORKFLOW, "hook-1")
    expires = int((NOW + START_LIFETIME).timestamp())
    assert start.body == {"nonce": start.body["nonce"], "kind": "test", "expires": expires}
    assert start.signature == start_signature(
        "test-start-secret", WORKFLOW, "hook-1", str(start.body["nonce"]), "test", expires
    )


async def test_the_options_list_only_what_the_portal_allows(t: Calls):
    assert await t.calls.options("agents", {}) == [NodeOption(CARD.id, "Compare")]
    assert await t.calls.options("agent_inputs", {"agent": CARD.id}) == [
        NodeOption("Project", "Project")
    ]
    assert await t.calls.options("places", {"source": "github_releases"}) == [
        NodeOption(REPO, "LangGraph")
    ]
    assert await t.calls.options("places", {"action": "jira.create_ticket"}) == [
        NodeOption("MOCK", "MOCK")
    ]
    assert await t.calls.options("write_actions", {}) == [
        NodeOption("jira.create_ticket", "Create a Jira ticket")
    ]
    assert await t.calls.options("places", {"action": "http.request"}) == []
