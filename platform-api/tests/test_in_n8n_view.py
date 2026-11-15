from platform_api.builder.models import N8nBlockKind
from platform_api.builder.n8n_view import N8nEdgeView, N8nNodeView, with_quiet_blocks


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
        "Read": "done",
        "Newer?": "done",
        "Keep fields": "done",
        "Join": "done",
        "Ask for a yes": "waiting",
    }


def test_a_start_and_a_branch_not_taken_stay_unrun():
    found = with_quiet_blocks({"Read": "running"}, NODES, EDGES)
    assert found == {"Read": "running"}, "a schedule never calls, and nothing ran after the IF"


def test_n8n_s_own_record_is_kept_as_it_is():
    found = with_quiet_blocks({"Newer?": "failed", "Ask for a yes": "done"}, NODES, EDGES)
    assert found["Newer?"] == "failed"
