"""Refining a drafted workflow's Check (ADR 0054, section 7, PR 8).

When the Check's simulation of a drafted revision fails a case, or no case reached a block, an
Operator may ask to refine it. The coordinator of Fix it for me (ADR 0055) runs the same loop on
the draft: the Scenario writer writes scenarios, or more aimed at the blocks no case reached, the
simulation runs them, and the Fix drafter changes only the blocks where a case failed. Code's
done check decides when it is good enough, the no-progress and widening stops apply, and the
limits are a fix's: 3 rounds, 12 hand-offs, $2 and 20 minutes.

It is offered only where Simulation mode's model is on (SIMULATION_MODEL) and a model is
connected, which the drafter runs on. Without them the card shows the simulation as before.

platform-api keeps the refinement and mints its token for the same deadline, then asks the agent
runtime to run the coordinator. The coordinator reaches platform-api's own routes for this one
refinement (`refine_http.py`): the Scenario writer, the simulation and the checker are a fix's
own parts (`fix_parts.py`), and its events go to this drafted workflow's record, never to a run's
log, as a Check has no run.

The result is a new revision of the drafted workflow, made with no model by code from the refined
plan, which goes through the normal Check: the safety checker's grade, its own simulation, and a
set-up approval before it is set up. It is kept only while the refinement runs, with no setting
changed, the change inside the blocks where a case failed on the draft as checked, a simulation
platform-api ran that every case passed, and the safety checker's grade of safe. A draft no case
failed on may come back unchanged once every case passed, and then nothing new is kept. Nothing
turns on, nothing is written, and no approval is skipped."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, LiteralString, Protocol, cast

from platform_api.builder.drafted_views import (
    DraftedWorkflowView,
    RefinementRoundView,
    RefinementState,
    RefinementView,
)
from platform_api.builder.drafted_workflows import (
    NEWER_BELOW,
    DraftedWorkflows,
    NotFound,
    Refused,
)
from platform_api.builder.fix_parts import MOST_CALLS, FixRevisionOut, ModelCall, refine_token
from platform_api.builder.fixes import (
    NotStored,
    changed_blocks,
    named_digest,
    plan_key,
    same_shape,
    settings_kept,
)
from platform_api.builder.simulation_views import SimulationView
from platform_api.builder.simulations import Simulations
from platform_api.db import Connection, Database, hold_workflow, json
from platform_api.monitoring import (
    FixData,
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
    FixRoundData,
)
from platform_api.orchestration import (
    AgentRejected,
    AgentUnavailable,
    CauseFound,
    CheckedCase,
    FixAccepted,
    ModelAccess,
    RefineAsked,
    RefineStartRequest,
    WorkflowPlan,
)
from platform_api.shared import Principal, Role, UserId, new_id

log = logging.getLogger(__name__)

REFINE_TIME_LIMIT: Final = timedelta(minutes=20)
"""ADR 0055, section 5: a fix's 20 minutes, from the press of the button."""
MOST_NAMED: Final = 10
"""As many failed cases and blocks no case reached as a refinement takes."""

OFF: Final = "Refining isn't turned on here."
NO_MODEL: Final = "No AI model is connected yet, so it can't be refined."
NOTHING_TO_REFINE: Final = (
    "Every case passed and reached every block, so there's nothing to refine."
)
REFINING: Final = "It's being refined now."
TRIED: Final = "This draft was refined once already."
ENDED: Final = "The refinement ended."
SETTING: Final = "A refinement can't change a setting."
OUTSIDE: Final = "A refinement changes only the blocks where a case failed."
UNPROVEN: Final = "Nothing here proved it on practice systems."
NOT_STORED: Final = "The proposal names a version this refinement didn't keep."

OFFERED_FAILED: Final = (
    "A case failed on practice systems. I can change the draft where it failed and try it again."
)
OFFERED_GAP: Final = (
    "No case reached every block. I can try more cases, and change the draft if one fails."
)
REFINING_SAID: Final = "Refining it on practice systems."
UNCHANGED_SAID: Final = (
    "Tried more cases on practice systems. Every case passed, so nothing changed."
)
GAVE_UP_SAID: Final = "I couldn't refine it. {why}"
WHY_SAID: Final[Mapping[str, str]] = {
    "no_progress": "A change didn't make more cases pass.",
    "widened": "A change went past the blocks where cases failed.",
    "round_limit": "It took more than 3 rounds.",
    "handoff_limit": "It took too many steps.",
    "cost_limit": "It reached its cost limit.",
    "time_limit": "It ran out of time.",
    "no_answer": "The drafter didn't answer.",
}
OTHERWISE: Final = "Nothing it tried passed every case."
CALL_COLUMNS: Final[Mapping[ModelCall, LiteralString]] = {
    "writer": "writer_calls",
    "explainer": "explainer_calls",
}


def refined_said(rounds: int) -> str:
    return (
        f"Refined on practice systems in {rounds} {'round' if rounds == 1 else 'rounds'}. "
        "It's checked again like any draft."
    )


@dataclass(frozen=True)
class RefineSettings:
    on: bool
    """SIMULATION_MODEL: off, no refinement is offered, so its coordinator makes no paid call."""
    signing_key: str = field(repr=False)
    platform_url: str
    """platform-api's own address, where the coordinator's calls go."""


class RefineRuntime(Protocol):
    async def start_refinement(
        self, request: RefineStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected: ...


class RefineModels(Protocol):
    async def access(self) -> ModelAccess | None: ...


@dataclass(frozen=True)
class RefineRow:
    fix_id: str
    drafted_id: str
    revision: int
    digest: str
    asked_by: UserId
    started_at: datetime
    ends_by: datetime
    refined_revision: int | None
    refined_digest: str | None
    refined_key: str | None
    unchanged: bool
    proposed_at: datetime | None
    handed_back_at: datetime | None
    handed_back_why: str | None
    simulated: Mapping[str, Mapping[str, Any]]

    def state(self, now: datetime) -> Literal["refining", "refined", "unchanged", "gave_up"]:
        if self.refined_revision is not None:
            return "refined"
        if self.unchanged:
            return "unchanged"
        if self.handed_back_at is not None or now >= self.ends_by:
            return "gave_up"
        return "refining"

    @property
    def ended(self) -> bool:
        return self.proposed_at is not None or self.handed_back_at is not None


def proven(results: Mapping[str, Mapping[str, Any]] | None) -> bool:
    """Every case that applies passed, and at least one applies. A refinement has no replay of a
    stop, as there is no stopped run."""
    applied = [r for r in (results or {}).values() if r.get("verdict") != "not_tried"]
    return bool(applied) and all(r.get("verdict") == "passed" for r in applied)


def failed_at(results: Mapping[str, Mapping[str, Any]] | None) -> set[str]:
    """The blocks where a case failed, as platform-api's own simulation graded it."""
    return {
        str(r["step"])
        for r in (results or {}).values()
        if r.get("verdict") == "failed" and r.get("step")
    }


class Refinements:
    def __init__(
        self,
        db: Database,
        drafted: DraftedWorkflows,
        simulations: Simulations,
        runtime: RefineRuntime,
        models: RefineModels,
        settings: RefineSettings,
    ) -> None:
        self._db = db
        self._drafted = drafted
        self._simulations = simulations
        self._runtime = runtime
        self._models = models
        self.settings = settings

    @property
    def available(self) -> bool:
        """Simulation mode's model is on, and there is a simulation n8n here."""
        return self.settings.on and self._simulations.available

    # The start

    async def start(
        self, drafted_id: str, person: Principal, revision: int
    ) -> DraftedWorkflowView | Refused | NotFound:
        """Starts refining the newest revision's Check for an Operator, whom the route checked."""
        if not self.available:
            return Refused(OFF)
        view = await self._drafted.view(drafted_id, person)
        if view is None:
            return NotFound()
        if revision != view.revision:
            return Refused(NEWER_BELOW)
        offer = view.refinement
        if offer is None:
            return Refused(NOTHING_TO_REFINE)
        if offer.state == "refining":
            return Refused(REFINING)
        if offer.state != "offered" or not offer.can_start:
            return Refused(TRIED)
        model = await self._models.access()
        if model is None:
            return Refused(NO_MODEL)
        drafted = await self._drafted.revision_plan(drafted_id, revision)
        if drafted is None:
            return NotFound()
        plan, digest = drafted
        gaps = await self._simulations.gaps(digest)
        blocks = {b.name for b in plan.blocks}
        failed = [_checked(case, blocks) for case in gaps.failed][:MOST_NAMED]
        not_reached = [name for name in gaps.not_reached if name in blocks][:MOST_NAMED]
        if not failed and not not_reached:
            return Refused(NOTHING_TO_REFINE)
        facts = await self._drafted.drafter_facts()
        row = await self._begin(drafted_id, revision, digest, person.user_id)
        if isinstance(row, Refused):
            return row
        token = refine_token(self.settings.signing_key, drafted_id, row.fix_id, row.ends_by)
        asked = RefineStartRequest(
            drafted_id=drafted_id,
            request=RefineAsked(
                fix_id=row.fix_id,
                asked_by=person.user_id,
                ends_by=row.ends_by,
                version=plan,
                failed=failed,
                not_reached=not_reached,
            ),
            facts=facts,
            model=model,
            platform_url=self.settings.platform_url,
            token=token,
        )
        answer = await self._runtime.start_refinement(asked)
        if not isinstance(answer, FixAccepted):
            log.warning("refinement %s: the runtime didn't take it: %s", row.fix_id, answer.detail)
            await self.note(
                drafted_id, row.fix_id, FixHandedBackData(fix_id=row.fix_id, why="gave_up")
            )
        log.info("%s asked to refine %s at revision %d", person.user_id, drafted_id, revision)
        view = await self._drafted.view(drafted_id, person)
        assert view is not None
        return view

    async def _begin(
        self, drafted_id: str, revision: int, digest: str, asked_by: UserId
    ) -> RefineRow | Refused:
        """Keeps the refinement, one for each drafted workflow at a time and one for each
        revision, under the drafted workflow's refinement lock."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"refine:{drafted_id}", alone=True)
            for row in await _rows_of(uow.conn, drafted_id):
                if row.state(uow.now) == "refining":
                    return Refused(REFINING)
                if row.revision == revision:
                    return Refused(TRIED)
            fix_id = new_id("fix")
            await uow.conn.execute(
                "INSERT INTO builder.drafted_refinements (fix_id, drafted_id, revision, digest,"
                " asked_by, started_at, ends_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    fix_id,
                    drafted_id,
                    revision,
                    digest,
                    asked_by,
                    uow.now,
                    uow.now + REFINE_TIME_LIMIT,
                ),
            )
            row = await _row(uow.conn, fix_id)
        assert row is not None
        return row

    # What the card shows

    async def view(
        self,
        drafted_id: str,
        newest: int,
        digest: str | None,
        editing: bool,
        simulation: SimulationView | None,
        viewer: Principal | None,
    ) -> RefinementView | None:
        """The refinement of the newest revision, or of the one it came from, as it stands. Or
        the offer to an Operator, once the newest revision's simulation failed a case or reached
        no case at a block, where refining is on and a model is connected."""
        async with self._db.connection("builder") as conn:
            rows = await _rows_of(conn, drafted_id)
            row = rows[0] if rows else None
            if row is not None and newest in (row.revision, row.refined_revision):
                return await self._view_of(conn, row)
        operator = viewer is not None and Role.OPERATOR in viewer.roles
        if not (operator and self.available and editing and digest is not None):
            return None
        if simulation is None or simulation.state != "done":
            return None
        gaps = await self._simulations.gaps(digest)
        if not gaps or await self._models.access() is None:
            return None
        return RefinementView(
            state="offered",
            said=OFFERED_FAILED if gaps.failed else OFFERED_GAP,
            rounds=[],
            revision=None,
            ends_by=None,
            can_start=True,
        )

    async def _view_of(self, conn: Connection, row: RefineRow) -> RefinementView:
        state: RefinementState = row.state(self._db.clock())
        rounds = await _rounds(conn, row.fix_id)
        match state:
            case "refined":
                said = refined_said(len(rounds))
            case "unchanged":
                said = UNCHANGED_SAID
            case "gave_up":
                why = row.handed_back_why or "time_limit"
                said = GAVE_UP_SAID.format(why=WHY_SAID.get(why, OTHERWISE))
            case _:
                said = REFINING_SAID
        return RefinementView(
            state=state,
            said=said,
            rounds=rounds,
            revision=row.refined_revision,
            ends_by=row.ends_by if state == "refining" else None,
            can_start=False,
        )

    # What the coordinator's routes reach

    async def note(self, drafted_id: str, fix_id: str, data: FixData) -> str | None:
        """One event of the refinement, kept by the drafted workflow under the rules a fix's
        events keep on a run: only while it runs, only the hand-back for time after its
        deadline, a repeat writes nothing, and a different repeat is a conflict. A proposal must
        name what this refinement kept."""
        kind, number = _key(data)
        async with self._db.transaction("builder") as uow:
            row = await _row(uow.conn, fix_id, lock=True)
            if row is None or row.drafted_id != drafted_id:
                return "not_started"
            same = await (
                await uow.conn.execute(
                    "SELECT data FROM builder.drafted_refinement_events"
                    " WHERE fix_id = %s AND kind = %s AND number = %s",
                    (fix_id, kind, number),
                )
            ).fetchone()
            written = data.model_dump(mode="json")
            if same is not None:
                return None if same["data"] == written else "conflict"
            for_time = isinstance(data, FixHandedBackData) and data.why == "time_limit"
            if row.ended or (uow.now >= row.ends_by and not for_time):
                return "ended"
            if isinstance(data, FixProposedData) and not _names_what_was_kept(row, data):
                raise NotStored(NOT_STORED)
            await uow.conn.execute(
                "INSERT INTO builder.drafted_refinement_events (fix_id, kind, number, data, at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (fix_id, kind, number, json(written), uow.now),
            )
            if isinstance(data, FixProposedData):
                await uow.conn.execute(
                    "UPDATE builder.drafted_refinements SET proposed_at = %s WHERE fix_id = %s",
                    (uow.now, fix_id),
                )
            elif isinstance(data, FixHandedBackData):
                await uow.conn.execute(
                    "UPDATE builder.drafted_refinements SET handed_back_at = %s,"
                    " handed_back_why = %s WHERE fix_id = %s",
                    (uow.now, data.why, fix_id),
                )
        return None

    async def store(
        self, drafted_id: str, fix_id: str, plan: WorkflowPlan, cause: CauseFound | None
    ) -> FixRevisionOut:
        """The refined draft as the drafted workflow's next revision, once, or the draft as
        checked when it comes back unchanged. NotStored says why not."""
        row = await self._row(fix_id)
        if row is None or row.drafted_id != drafted_id:
            raise NotStored(ENDED, 409)
        key = plan_key(plan)
        if row.refined_key == key and row.refined_revision and row.refined_digest:
            return FixRevisionOut(
                version=row.refined_revision, digest=named_digest(row.refined_digest)
            )
        if row.ended or row.state(self._db.clock()) != "refining":
            raise NotStored(ENDED, 409)
        checked = await self._drafted.revision_plan(drafted_id, row.revision)
        if checked is None:
            raise NotStored(ENDED, 409)
        original, _ = checked
        if not proven(row.simulated.get(key)):
            raise NotStored(UNPROVEN, 409)
        if plan == original:
            await self._unchanged(fix_id)
            return FixRevisionOut(version=row.revision, digest=named_digest(row.digest))
        if not settings_kept(original, plan):
            raise NotStored(SETTING)
        part = set(cause.failed_part) if cause is not None else set[str]()
        if (
            not part
            or not part <= failed_at(row.simulated.get(plan_key(original)))
            or not same_shape(original, plan)
            or not changed_blocks(original, plan) <= part
        ):
            raise NotStored(OUTSIDE)
        kept = await self._drafted.keep_refined(drafted_id, row.revision, plan, row.asked_by)
        if isinstance(kept, Refused):
            raise NotStored(kept.words, 409)
        number, digest = kept
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_refinements SET refined_revision = %s,"
                " refined_digest = %s, refined_key = %s WHERE fix_id = %s",
                (number, digest, key, fix_id),
            )
        log.info("refinement %s: kept revision %d of %s", fix_id, number, drafted_id)
        return FixRevisionOut(version=number, digest=named_digest(digest))

    async def take_call(self, fix_id: str, kind: ModelCall) -> bool:
        column = CALL_COLUMNS[kind]
        async with self._db.transaction("builder") as uow:
            taken = await (
                await uow.conn.execute(
                    f"UPDATE builder.drafted_refinements SET {column} = {column} + 1"
                    f" WHERE fix_id = %s AND {column} < %s RETURNING fix_id",
                    (fix_id, MOST_CALLS[kind]),
                )
            ).fetchone()
        return taken is not None

    async def simulated_on(
        self, fix_id: str, plan: WorkflowPlan, results: Mapping[str, Any]
    ) -> None:
        """Keeps a simulation platform-api ran, each case's latest grade on the plan."""
        key = plan_key(plan)
        async with self._db.transaction("builder") as uow:
            row = await _row(uow.conn, fix_id, lock=True)
            if row is None:
                return
            kept = {**row.simulated.get(key, {}), **results}
            await uow.conn.execute(
                "UPDATE builder.drafted_refinements SET simulated = simulated || %s"
                " WHERE fix_id = %s",
                (json({key: kept}), fix_id),
            )

    async def _row(self, fix_id: str) -> RefineRow | None:
        async with self._db.connection("builder") as conn:
            return await _row(conn, fix_id)

    async def _unchanged(self, fix_id: str) -> None:
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_refinements SET unchanged = true WHERE fix_id = %s",
                (fix_id,),
            )


def _checked(case: Mapping[str, Any], blocks: set[str]) -> CheckedCase:
    """A case the Check failed, with where it stopped only when that is a block of the draft."""
    step, why = case.get("step"), case.get("why")
    return CheckedCase(
        kind=case["kind"],
        step=step if step in blocks else None,
        why=str(why)[:40] if why else None,
    )


def _names_what_was_kept(row: RefineRow, data: FixProposedData) -> bool:
    if row.refined_revision is not None and row.refined_digest is not None:
        return (data.version, data.digest) == (
            row.refined_revision,
            named_digest(row.refined_digest),
        )
    return row.unchanged and (data.version, data.digest) == (row.revision, named_digest(row.digest))


def _key(data: FixData) -> tuple[str, int]:
    match data:
        case FixHandoffData(handoff=handoff):
            return "fix_handoff", handoff
        case FixRoundData(round=number):
            return "fix_round", number
        case FixProposedData():
            return "fix_proposed", 0
        case FixHandedBackData():
            return "fix_handed_back", 0
        case _:
            return "fix_started", 0


async def _rounds(conn: Connection, fix_id: str) -> list[RefinementRoundView]:
    rows = await (
        await conn.execute(
            "SELECT data FROM builder.drafted_refinement_events"
            " WHERE fix_id = %s AND kind = 'fix_round' ORDER BY number",
            (fix_id,),
        )
    ).fetchall()
    return [
        RefinementRoundView(
            round=r["data"]["round"], passed=r["data"]["passed"], scenarios=r["data"]["scenarios"]
        )
        for r in rows
    ]


SELECT: Final[LiteralString] = (
    "SELECT fix_id, drafted_id, revision, digest, asked_by, started_at, ends_by,"
    " refined_revision, refined_digest, refined_key, unchanged, proposed_at, handed_back_at,"
    " handed_back_why, simulated FROM builder.drafted_refinements"
)


async def _row(conn: Connection, fix_id: str, lock: bool = False) -> RefineRow | None:
    query = f"{SELECT} WHERE fix_id = %s" + (" FOR UPDATE" if lock else "")
    row = await (await conn.execute(query, (fix_id,))).fetchone()
    return None if row is None else _from(row)


async def _rows_of(conn: Connection, drafted_id: str) -> list[RefineRow]:
    """A drafted workflow's refinements, the newest first."""
    rows = await (
        await conn.execute(
            f"{SELECT} WHERE drafted_id = %s ORDER BY started_at DESC", (drafted_id,)
        )
    ).fetchall()
    return [_from(row) for row in rows]


def _from(r: Mapping[str, Any]) -> RefineRow:
    return RefineRow(
        fix_id=r["fix_id"],
        drafted_id=r["drafted_id"],
        revision=r["revision"],
        digest=r["digest"],
        asked_by=UserId(r["asked_by"]),
        started_at=r["started_at"],
        ends_by=r["ends_by"],
        refined_revision=r["refined_revision"],
        refined_digest=r["refined_digest"],
        refined_key=r["refined_key"],
        unchanged=r["unchanged"],
        proposed_at=r["proposed_at"],
        handed_back_at=r["handed_back_at"],
        handed_back_why=r["handed_back_why"],
        simulated=cast(Mapping[str, Mapping[str, Any]], r["simulated"] or {}),
    )
