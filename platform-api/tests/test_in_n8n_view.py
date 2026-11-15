from collections.abc import AsyncIterator, Mapping

import pytest

from platform_api.builder.models import N8nBlockKind
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.n8n_view import N8nEdgeView, N8nNodeView, graph, with_quiet_blocks
from platform_api.orchestration.n8n_run_view import RunsInN8n
from platform_api.orchestration.runs import Succeeded
from platform_api.shared import N8nExecutionId
from tests.conftest import PostgresUrls
from tests.support import BOB
from tests.test_n8n_watchlist import check
from tests.test_n8n_write import Writes, open_writes


def node(name: str, kind: N8nBlockKind) -> N8nNodeView:
    return N8nNodeView(name=name, type="t", kind=kind, position=[0, 0], disabled=False)


def edge(source: str, target: str, exit: int = 0) -> N8nEdgeView:
    return N8nEdgeView(source=source, exit=exit, target=target)


NODES = [
    node("Daily 8:00", "schedule"),
    node("Read", "read"),
    node("Newer?", "branch"),
    node("Keep fields", "other"),
    node("Join", "merge"),
    node("Ask for a yes", "ask"),
    node("Nothing to change", "end"),
]
EDGES = [
    edge("Daily 8:00", "Read"),
    edge("Read", "Newer?"),
    edge("Newer?", "Keep fields"),
    edge("Newer?", "Nothing to change", 1),
    edge("Keep fields", "Join"),
    edge("Join", "Ask for a yes"),
]


def test_quiet_blocks_before_a_block_that_ran_are_done_however_many_in_a_row():
    found = with_quiet_blocks({"Read": "done", "Ask for a yes": "waiting"}, NODES, EDGES)
    assert found == {
        "Daily 8:00": "done",
        "Read": "done",
        "Newer?": "done",
        "Keep fields": "done",
        "Join": "done",
        "Ask for a yes": "waiting",
    }, "each quiet block here is the only way into a block that ran, the schedule included"


def test_a_start_is_done_only_when_it_is_the_one_way_in():
    two = [*NODES, node("Start from the Portal", "start")]
    found = with_quiet_blocks(
        {"Read": "running"}, two, [*EDGES, edge("Start from the Portal", "Read")]
    )
    assert found == {"Read": "running"}, "either start may have begun it, so neither is guessed"


def test_of_two_branches_into_a_merge_neither_is_guessed():
    nodes = [
        node("Newer?", "branch"),
        node("Keep", "other"),
        node("Set", "other"),
        node("Merge", "merge"),
        node("Ask for a yes", "ask"),
    ]
    edges = [
        edge("Newer?", "Keep"),
        edge("Newer?", "Set", 1),
        edge("Keep", "Merge"),
        edge("Set", "Merge", 1),
        edge("Merge", "Ask for a yes"),
    ]
    found = with_quiet_blocks({"Ask for a yes": "waiting"}, nodes, edges)
    assert found == {"Merge": "done", "Ask for a yes": "waiting"}, "Keep or Set: unknown"


def test_n8n_s_own_record_is_kept_as_it_is():
    found = with_quiet_blocks({"Newer?": "failed", "Ask for a yes": "done"}, NODES, EDGES)
    assert found["Newer?"] == "failed"


class Ran:
    """n8n's own record of an execution, as the executions API reads it."""

    def __init__(self, record: Mapping[str, str]) -> None:
        self.record = record

    async def ran(self, execution_id: N8nExecutionId) -> Mapping[str, str] | None:
        return self.record


@pytest.fixture
async def wl(postgres: PostgresUrls) -> AsyncIterator[Writes]:
    async with open_writes(postgres) as writes:
        yield writes


@pytest.mark.anyio
async def test_a_run_through_the_real_calls_waits_at_the_yes_then_reads_n8n_s_record(wl: Writes):
    await check(wl, "101")
    run = await wl.run()
    record = {"Mon 9:00": "success", "Ask for a yes": "success", "Create tickets": "success"}
    views = RunsInN8n(wl.h.db, Ran(record))
    waiting = await views.read(run.run_id)
    assert waiting is not None
    assert waiting.nodes["Ask for a yes"] == "waiting", "the run's stored state is what it waits in"
    assert not waiting.read_n8n

    await wl.decide(BOB)
    await wl.tick()
    await wl.write("101", "Create tickets")
    assert isinstance((await wl.run()).state, Succeeded)
    ended = await views.read(run.run_id)
    assert ended is not None and ended.read_n8n, "an ended run reads n8n's own record"
    assert ended.nodes["Mon 9:00"] == "done"
    assert ended.nodes["Create tickets"] == "done"


def test_a_block_that_is_off_or_unknown_is_told_apart_from_n8n_s_safe_ones():
    def at(name: str, kind: str) -> dict[str, object]:
        return {"name": name, "type": kind, "typeVersion": 1, "position": [0, 0], "parameters": {}}

    document = {
        "nodes": [
            at("Daily 8:00", "n8n-nodes-base.scheduleTrigger"),
            at("Keep fields", "n8n-nodes-base.set"),
            at("Send it", "n8n-nodes-base.httpRequest"),
            at("Mystery", "community.unknown"),
        ],
        "connections": {
            "Daily 8:00": {"main": [[{"node": "Keep fields", "type": "main", "index": 0}]]},
            "Keep fields": {"main": [[{"node": "Send it", "type": "main", "index": 0}]]},
            "Send it": {"main": [[{"node": "Mystery", "type": "main", "index": 0}]]},
        },
    }
    kinds = {block.name: block.kind for block in blocks_of(document)}
    assert kinds == {
        "Daily 8:00": "schedule",
        "Keep fields": "other",
        "Send it": "off",
        "Mystery": "off",
    }
    nodes, _ = graph(document)
    assert {node.name: node.kind for node in nodes} == kinds
