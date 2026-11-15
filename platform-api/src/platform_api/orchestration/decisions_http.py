"""A person's own decisions on requests, for the Planner's answer to "What did I decide before?"
(ADR 0043). Anyone signed in reads their own, and nobody reads anyone else's."""

from datetime import datetime
from typing import Final, Literal

from fastapi import APIRouter
from pydantic import Field

from platform_api.auth import SIGNED_IN, CurrentPrincipal
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.http import CurrentOrchestrator
from platform_api.orchestration.service import PastDecision
from platform_api.shared import RunId, UseCaseId, UserId
from platform_api.wire import RunState, WireModel

router = APIRouter(prefix="/api/v1", tags=["orchestration"])

DECISIONS_SHOWN: Final = 50


class PastDecisionView(WireModel):
    run_id: RunId
    use_case_id: UseCaseId
    use_case_name: str = Field(description="The workflow's name when the run started.")
    verdict: Literal["approve", "decline"]
    reason: str | None = Field(description="Why they declined, when they gave a reason.")
    at: datetime = Field(description="When they decided.")
    run_state: RunState = Field(description="How the run they decided stands now.")
    written: int = Field(description="The writes the run made.")
    tickets: bool = Field(
        description="True when every write the run made, or proposed, is a ticket."
    )
    connector: str | None = Field(description="Where the run writes, as jira.")
    approved_before: list[UserId] = Field(
        description="On a declined run, who said yes before the decline, in step order. Empty "
        "for any other run."
    )
    declined_by: UserId | None = Field(description="Who declined the run, when it was declined.")


class DecisionsView(WireModel):
    decisions: list[PastDecisionView] = Field(
        description=f"Newest first, at most {DECISIONS_SHOWN}."
    )
    total: int = Field(description="How many decisions match, shown or not.")


def _view(past: PastDecision) -> PastDecisionView:
    decision, record, gist = past.decision, past.run.record, past.gist
    return PastDecisionView(
        run_id=record.run_id,
        use_case_id=record.spec.use_case_id,
        use_case_name=record.spec.use_case_name,
        verdict=decision.verdict.value,
        reason=decision.reason,
        at=decision.at,
        run_state=gist.state,
        written=gist.written,
        tickets=gist.tickets,
        connector=past.connector,
        approved_before=list(gist.approved_by) if gist.state == "rejected" else [],
        declined_by=gist.declined_by,
    )


@router.get("/decisions", responses=SIGNED_IN)
async def decisions(
    principal: CurrentPrincipal,
    orchestrator: CurrentOrchestrator,
    verdict: Literal["approve", "decline"] | None = None,
) -> DecisionsView:
    """The signed-in person's own decisions on requests, newest first, each with the run it
    decided as it stands now. `verdict` keeps only approvals or only declines."""
    page = await orchestrator.decisions_of(
        principal, None if verdict is None else Verdict(verdict), DECISIONS_SHOWN
    )
    return DecisionsView(decisions=[_view(p) for p in page.decisions], total=page.total)
