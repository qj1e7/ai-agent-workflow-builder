"""What the In n8n tabs draw (ENGINE-PLAN E7, E8): a workflow's blocks and edges as the version
in use holds them, who published it and who holds it now, and for a run, each block's state."""

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, Field

from platform_api.builder.models import N8nBadge, N8nBlockKind, N8nBlockView, N8nHolderView
from platform_api.builder.n8n_draft import blocks_of, view_kind
from platform_api.builder.n8n_holds import Held, Holding, StaffPort
from platform_api.db import Database
from platform_api.orchestration import (
    CanOpen,
    NodeState,
    RunInN8n,
    Unreadable,
    face,
    read_flow,
)
from platform_api.shared import Principal, RunId, UserId
from platform_api.wire import WireModel


class N8nNodeView(WireModel):
    name: str
    type: str
    kind: N8nBlockKind = Field(
        description="What the block does, as on the set-up card. other is a sticky note or one "
        "of n8n's own blocks that shapes the data, reads a system or posts a notice, and off a "
        "block the class file turns off, or does not know, for what it is or what it was asked "
        "to do; type and tag say which."
    )
    badge: N8nBadge = Field(
        default="ours",
        description="ours for a block of our node pack, n8n for one of n8n's own (ADR 0045).",
    )
    tag: str | None = Field(
        default=None,
        description="What one of n8n's own blocks does, by its class: Reads Jira, Posts in "
        "Slack, Shapes the data. Null for our blocks, n8n's flow blocks and sticky notes.",
    )
    position: list[float] = Field(description="Where n8n's editor draws it, as x and y.")
    disabled: bool


class N8nEdgeView(WireModel):
    source: str
    exit: int = Field(description="Which of the source block's exits, from 0.")
    target: str


class UseCaseN8nView(WireModel):
    use_case_id: str
    workflow_id: str
    version: int = Field(description="The version in use.")
    n8n_version_id: str | None
    published_by: UserId | None = Field(
        description="Who published the version in use. Null for one nobody could be matched to."
    )
    published_by_name: str | None
    published_in: Literal["portal", "n8n"] | None
    published_at: AwareDatetime = Field(
        description="When the version in use was made, as the versions list says it."
    )
    nodes: list[N8nNodeView]
    edges: list[N8nEdgeView]
    holder: N8nHolderView | None = Field(description="Who has it open in n8n now, if anyone.")
    can_open: bool = Field(description="Whether you can open n8n's editor now.")
    why_not: str | None = Field(description="Why not, in words to show. Null when you can.")
    editor_url: str | None = Field(
        description="This workflow in n8n's editor, while you can open it and it sits in your "
        "own n8n space."
    )


class RunN8nView(WireModel):
    run_id: RunId
    use_case_id: str
    workflow_id: str | None
    execution_id: str | None = Field(description="The run's last n8n execution.")
    n8n_version_id: str | None = Field(description="The n8n version that execution ran.")
    nodes: list[N8nNodeView]
    edges: list[N8nEdgeView]
    blocks: list[N8nBlockView] = Field(
        description="The same blocks in the order a run meets them, as the set-up card and a "
        "workflow's blocks list them, which the canvas draws."
    )
    states: dict[str, NodeState] = Field(
        description="Each block's state by its name. A block that is not here has not run, or "
        "is not known to have run. Until n8n's own record is read, a block that never calls the "
        "platform, such as an IF, is done when it is the one way into a block that ran "
        "(ENGINE-PLAN section 1, row 9)."
    )
    from_n8n: bool = Field(
        description="n8n's own record of the ended run was read, so n8n's blocks are here too."
    )


class RunsReader(Protocol):
    async def read(self, run_id: RunId) -> RunInN8n | None: ...


def graph(document: Mapping[str, Any] | None) -> tuple[list[N8nNodeView], list[N8nEdgeView]]:
    """The blocks and edges of an n8n workflow, or none for one the platform cannot read."""
    if document is None:
        return [], []
    try:
        flow = read_flow(document)
    except Unreadable:
        return [], []
    nodes: list[N8nNodeView] = []
    for node in document["nodes"]:
        block = flow.blocks[node["name"]]
        seen = face(block.type, block.version, block.parameters)
        position = node.get("position") or [0, 0]
        nodes.append(
            N8nNodeView(
                name=node["name"],
                type=str(node.get("type", "")),
                kind=view_kind(seen),
                badge="ours" if seen.ours else "n8n",
                tag=seen.tag,
                position=[float(position[0]), float(position[1])],
                disabled=bool(node.get("disabled", False)),
            )
        )
    edges = [N8nEdgeView(source=e.source, exit=e.exit, target=e.target) for e in flow.edges]
    return nodes, edges


QUIET: frozenset[N8nBlockKind] = frozenset(
    {"schedule", "start", "manual", "error", "branch", "merge", "other"}
)
"""Blocks that never call the platform: the starts, and n8n's own blocks before a run's end."""


def with_quiet_blocks(
    states: Mapping[str, NodeState], nodes: list[N8nNodeView], edges: list[N8nEdgeView]
) -> dict[str, NodeState]:
    """Before n8n's own record is read, a quiet block is done when it is the one way into a
    block that ran, so an IF is not drawn as not run while the run waits past it. Where two
    blocks lead in, either may have run, so neither is guessed."""
    kinds = {node.name: node.kind for node in nodes}
    into: dict[str, set[str]] = {}
    for edge in edges:
        into.setdefault(edge.target, set()).add(edge.source)
    found = dict(states)
    grown = True
    while grown:
        grown = False
        for target, sources in into.items():
            if target not in found or len(sources) != 1:
                continue
            [source] = sources
            if source not in found and kinds.get(source) in QUIET:
                found[source] = "done"
                grown = True
    return found


_IN_USE = """
    SELECT u.n8n_workflow_id, u.current_version, v.document, v.n8n_version_id, v.published_by,
           v.published_in, v.created_at
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE u.use_case_id = %s AND u.deleted_at IS NULL
"""
_RAN = """
    SELECT document FROM builder.use_case_versions
    WHERE use_case_id = %s AND n8n_version_id = %s AND document IS NOT NULL
    ORDER BY version DESC LIMIT 1
"""


class InN8nViews:
    def __init__(
        self,
        db: Database,
        holding: Holding,
        staff: StaffPort,
        runs: RunsReader,
        editor_url: str | None,
    ) -> None:
        self._db = db
        self._holding = holding
        self._staff = staff
        self._runs = runs
        self._editor_url = editor_url

    async def use_case(self, use_case_id: str, viewer: Principal) -> UseCaseN8nView | None:
        async with self._db.connection("builder") as conn:
            row = await (await conn.execute(_IN_USE, (use_case_id,))).fetchone()
        if row is None or row["n8n_workflow_id"] is None:
            return None
        nodes, edges = graph(row["document"])
        held = await self._holding.holder(use_case_id)
        access = await self._staff.access(viewer.user_id)
        can_open = isinstance(access, CanOpen)
        publisher = None if row["published_by"] is None else UserId(row["published_by"])
        workflow_id = str(row["n8n_workflow_id"])
        mine = held is not None and held.by == viewer.user_id
        return UseCaseN8nView(
            use_case_id=use_case_id,
            workflow_id=workflow_id,
            version=row["current_version"],
            n8n_version_id=row["n8n_version_id"],
            published_by=publisher,
            published_by_name=None
            if publisher is None
            else await self._staff.display_of(publisher),
            published_in=row["published_in"],
            published_at=row["created_at"],
            nodes=nodes,
            edges=edges,
            holder=None if held is None else await self._holder(held),
            can_open=can_open,
            why_not=None if isinstance(access, CanOpen) else access.words,
            editor_url=self.editor_url(workflow_id) if can_open and mine else None,
        )

    async def run(self, run_id: RunId) -> RunN8nView | None:
        ran = await self._runs.read(run_id)
        if ran is None:
            return None
        async with self._db.connection("builder") as conn:
            row = None
            if ran.version_id is not None:
                found = await conn.execute(_RAN, (ran.use_case_id, ran.version_id))
                row = await found.fetchone()
            if row is None:
                row = await (await conn.execute(_IN_USE, (ran.use_case_id,))).fetchone()
        document = None if row is None else row["document"]
        nodes, edges = graph(document)
        return RunN8nView(
            run_id=run_id,
            use_case_id=ran.use_case_id,
            workflow_id=ran.workflow_id,
            execution_id=ran.execution_id,
            n8n_version_id=ran.version_id,
            nodes=nodes,
            edges=edges,
            blocks=[] if document is None else blocks_of(document),
            states=dict(ran.nodes) if ran.read_n8n else with_quiet_blocks(ran.nodes, nodes, edges),
            from_n8n=ran.read_n8n,
        )

    def editor_url(self, workflow_id: str) -> str | None:
        return None if self._editor_url is None else f"{self._editor_url}/workflow/{workflow_id}"

    async def _holder(self, held: Held) -> N8nHolderView:
        return N8nHolderView(
            id=held.by, name=await self._staff.display_of(held.by), since=held.since
        )
