"""Fix it for me's routes (ADR 0055, PR 6): an Operator asks for a fix on a stopped run, anyone on
the team reads it, an Operator turns it back on after an Approver's yes, and answers the question
a handed-back fix asks. The Portal's button comes with PR 7."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.drafted_workflows import NotFound, Refused
from platform_api.builder.fixes import FixAnswerIn, Fixes, FixView
from platform_api.builder.http import operators_only
from platform_api.shared import Principal, RunId
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

ASK_FOR_FIXES = "Only an Operator can ask for a fix. Ask an Operator on the team."
NO_SUCH_FIX = "No such fix"
NO_SUCH_RUN = "No such run"
NOT_HERE = "Fix it for me isn't set up here."

FixAsker = Annotated[Principal, Depends(operators_only(ASK_FOR_FIXES))]


def current_fixes(request: Request) -> Fixes:
    fixes: Fixes | None = getattr(request.app.state, "fixes", None)
    if fixes is None:
        raise HTTPException(503, NOT_HERE)
    return fixes


CurrentFixes = Annotated[Fixes, Depends(current_fixes)]


def _answered(answer: FixView | Refused | NotFound, missing: str = NO_SUCH_FIX) -> FixView:
    match answer:
        case Refused(words):
            raise HTTPException(409, words)
        case NotFound():
            raise HTTPException(404, missing)
        case _:
            return answer


@router.post(
    "/runs/{run_id}/fixes",
    status_code=202,
    description="Starts Fix it for me on a stopped run (ADR 0055). platform-api writes the fix's "
    "start with who asked, from the session, mints its token only once the log took the start, "
    "and asks the agent runtime to run the coordinator. It answers at once, while the fix "
    "drafts. Only for a drafted workflow, set up as it was approved and still that version, "
    "one fix at a time, and only while FIX_MODEL is on.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH_RUN),
        409: error_response("Why no fix can start on this run now"),
        503: error_response(NOT_HERE),
    },
)
async def ask_for_a_fix(run_id: RunId, principal: FixAsker, fixes: CurrentFixes) -> FixView:
    return _answered(await fixes.start(run_id, principal), NO_SUCH_RUN)


@router.get(
    "/fixes/{fix_id}",
    description="A fix as it stands, in one state with code's words for it. A handed-back fix "
    "asks for the one setting a fix never changes itself. Anyone on the team who is signed in "
    "may read it.",
    responses={**SIGNED_IN, 404: error_response(NO_SUCH_FIX), 503: error_response(NOT_HERE)},
)
async def read_a_fix(fix_id: str, principal: CurrentPrincipal, fixes: CurrentFixes) -> FixView:
    return _answered(await fixes.view(fix_id))


@router.post(
    "/fixes/{fix_id}/turn-back-on",
    status_code=202,
    description="Only after an Approver's yes to the fix's version: tries it with the one real "
    "test run, which stops at the yes and writes nothing, and turns the workflow back on with it "
    "only once that passed. Asking again answers the fix as it stands. A fix an Approver said no "
    "to stays off.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH_FIX),
        409: error_response("It needs an Approver's yes first."),
        503: error_response(NOT_HERE),
    },
)
async def turn_a_fix_back_on(fix_id: str, principal: FixAsker, fixes: CurrentFixes) -> FixView:
    return _answered(await fixes.turn_back_on(fix_id, principal))


@router.post(
    "/fixes/{fix_id}/answers",
    description="The answer to the question a handed-back fix asks: the one setting a fix never "
    "changes itself. Code puts it in the stopped version, with no model, and the version it makes "
    "waits for an Approver's yes, as any fix does. The person who answers is a party to it.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH_FIX),
        409: error_response("There's no question to answer for this fix."),
        503: error_response(NOT_HERE),
    },
)
async def answer_a_fix(
    fix_id: str, body: FixAnswerIn, principal: FixAsker, fixes: CurrentFixes
) -> FixView:
    return _answered(await fixes.answer(fix_id, principal, body))
