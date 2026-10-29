from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.orchestration.confirmations import (
    HISTORY_SHOWN,
    Confirmation,
    DecideRefusal,
    DecideRefused,
    Decision,
    Kind,
)
from platform_api.orchestration.http import Operator
from platform_api.orchestration.model_settings import (
    AddressDecided,
    NotAnApprover,
    NothingPending,
    OwnAddress,
    PendingChanged,
    SettingsOff,
)
from platform_api.orchestration.people import (
    MAX_DISPLAY_CHARS,
    MAX_EMAIL_CHARS,
    PeopleRefusal,
    Person,
    Refused,
)
from platform_api.orchestration.people_store import (
    ConfirmationRow,
    Decided,
    HistoryLine,
    ModelAddress,
    NotFound,
    People,
    PersonRow,
)
from platform_api.orchestration.settings_http import CurrentModelSettings
from platform_api.shared import Principal, UserId
from platform_api.wire import WireModel, error_response

router = APIRouter()

type PeopleRefusalName = Literal[
    "bad_email",
    "already_on_the_list",
    "no_role",
    "own_operator_role",
    "last_operator",
    "two_approvers",
    "already_an_approver",
    "already_asked",
    "confirmation_waiting",
    "yourself",
]
type DecideRefusalName = Literal[
    "not_an_approver",
    "you_asked",
    "about_you",
    "already_decided",
    "digest_changed",
    "person_removed",
    "asker_gone",
]
type ConfirmationKind = Literal["approver", "model_address"]
type ConfirmationDecision = Literal["confirmed", "not_now"]
type SettingsArea = Literal["people", "model"]


class PendingApproverOut(WireModel):
    confirmation_id: str
    asked_by: UserId
    asked_at: datetime


class PersonOut(WireModel):
    id: UserId
    display: str
    email: str
    operator: bool
    approver: bool
    pending_approver: PendingApproverOut | None = Field(
        description="Set while another Approver has still to confirm this person as an Approver."
    )
    signed_in: bool = Field(description="Whether this person has signed in at least once.")
    added_by: UserId
    added_at: datetime


class PeopleOut(WireModel):
    people: list[PersonOut]


class AddPersonIn(WireModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL_CHARS)
    display: str = Field(min_length=1, max_length=MAX_DISPLAY_CHARS)
    operator: bool = False
    approver: bool = Field(
        default=False, description="Asks for the role. Another Approver confirms it."
    )


class OperatorIn(WireModel):
    operator: bool


class PeopleRefusalOut(WireModel):
    refusal: PeopleRefusalName
    message: str


class AboutPersonOut(WireModel):
    id: UserId
    display: str
    email: str


class ConfirmationOut(WireModel):
    confirmation_id: str
    kind: ConfirmationKind
    summary: str
    about: AboutPersonOut | None = Field(description="The person a new Approver role is about.")
    digest: str = Field(description="Quote it in the decision, so it applies to this entry only.")
    asked_by: UserId
    asked_by_name: str
    asked_at: datetime
    you_can_decide: bool
    why_not: DecideRefusalName | None


class ConfirmationsOut(WireModel):
    confirmations: list[ConfirmationOut]


class ConfirmationDecisionIn(WireModel):
    verdict: Literal["confirm", "not_now"]
    digest: str


class ConfirmationDecidedOut(WireModel):
    confirmation_id: str
    kind: ConfirmationKind
    decision: ConfirmationDecision
    decided_by: UserId
    decided_at: datetime


class DecideRefusalOut(WireModel):
    refusal: DecideRefusalName
    message: str


class SettingsChangeOut(WireModel):
    at: datetime
    area: SettingsArea
    by: UserId = Field(description="Whose change it is: the person who made it, or who asked.")
    by_name: str | None
    confirmed_by: UserId | None = Field(description="The Approver who decided it, if any.")
    confirmed_by_name: str | None
    confirmation_id: str | None
    summary: str


class SettingsHistoryOut(WireModel):
    changes: list[SettingsChangeOut]


def current_people(request: Request) -> People:
    people: People = request.app.state.people
    return people


CurrentPeople = Annotated[People, Depends(current_people)]

NO_SUCH_PERSON = error_response("No such person on the list")
RULE_REFUSED = {
    "model": PeopleRefusalOut,
    "description": "A rule about people and roles refused it",
}
DECIDE_REFUSED = {"model": DecideRefusalOut, "description": "This person cannot decide this"}


def person_out(row: PersonRow) -> PersonOut:
    p = row.person
    return PersonOut(
        id=p.id,
        display=p.display,
        email=p.email,
        operator=p.is_operator,
        approver=p.is_approver,
        pending_approver=(
            PendingApproverOut(
                confirmation_id=row.pending.id,
                asked_by=row.pending.asked_by,
                asked_at=row.pending.asked_at,
            )
            if row.pending is not None
            else None
        ),
        signed_in=p.bound_at is not None,
        added_by=p.added_by,
        added_at=p.added_at,
    )


def confirmation_summary(confirmation: Confirmation, about: Person | None) -> str:
    match confirmation.kind:
        case Kind.APPROVER:
            name = about.display if about is not None else str(confirmation.change.get("display"))
            return f"Make {name} an Approver"
        case Kind.MODEL_ADDRESS:
            change = confirmation.change
            return f"Use {change.get('model')} at {change.get('host')}"


def confirmation_out(row: ConfirmationRow) -> ConfirmationOut:
    c = row.confirmation
    return ConfirmationOut(
        confirmation_id=c.id,
        kind=c.kind.value,  # type: ignore[arg-type]
        summary=confirmation_summary(c, row.about),
        about=(
            AboutPersonOut(id=row.about.id, display=row.about.display, email=row.about.email)
            if row.about is not None
            else None
        ),
        digest=c.digest,
        asked_by=c.asked_by,
        asked_by_name=row.asked_by_name,
        asked_at=c.asked_at,
        you_can_decide=row.why_not is None,
        why_not=row.why_not.value if row.why_not is not None else None,  # type: ignore[arg-type]
    )


def history_out(lines: list[HistoryLine]) -> SettingsHistoryOut:
    return SettingsHistoryOut(
        changes=[
            SettingsChangeOut(
                at=line.change.at,
                area=line.change.area,
                by=line.change.changed_by,
                by_name=line.changed_by_name,
                confirmed_by=line.change.confirmed_by,
                confirmed_by_name=line.confirmed_by_name,
                confirmation_id=line.change.confirmation_id,
                summary=line.change.summary,
            )
            for line in lines
        ]
    )


def _refused(refused: Refused) -> JSONResponse | HTTPException:
    if refused.reason is PeopleRefusal.NOT_AN_OPERATOR:
        return HTTPException(status_code=403, detail=refused.message)
    body = PeopleRefusalOut(refusal=refused.reason.value, message=refused.message)  # type: ignore[arg-type]
    return JSONResponse(status_code=409, content=body.model_dump(mode="json"))


def _answer(outcome: Person | PersonRow | Refused | NotFound) -> PersonOut | JSONResponse:
    match outcome:
        case Person():
            return person_out(PersonRow(outcome, None))
        case PersonRow():
            return person_out(outcome)
        case NotFound():
            raise HTTPException(status_code=404, detail="No such person on the list")
        case Refused():
            answer = _refused(outcome)
            if isinstance(answer, HTTPException):
                raise answer
            return answer


@router.get("/api/v1/people", tags=["people"], responses=SIGNED_IN)
async def list_people(principal: CurrentPrincipal, people: CurrentPeople) -> PeopleOut:
    return PeopleOut(people=[person_out(row) for row in await people.list_people()])


@router.post(
    "/api/v1/people",
    status_code=201,
    tags=["people"],
    response_model=PersonOut,
    responses={**OPERATORS_ONLY, 409: RULE_REFUSED},
)
async def add_person(
    body: AddPersonIn, principal: Operator, people: CurrentPeople
) -> PersonOut | JSONResponse:
    return _answer(
        await people.add(principal, body.email, body.display, body.operator, body.approver)
    )


@router.put(
    "/api/v1/people/{person_id}/operator",
    tags=["people"],
    response_model=PersonOut,
    responses={**OPERATORS_ONLY, 404: NO_SUCH_PERSON, 409: RULE_REFUSED},
)
async def set_operator(
    person_id: UserId, body: OperatorIn, principal: Operator, people: CurrentPeople
) -> PersonOut | JSONResponse:
    return _answer(await people.set_operator(principal, person_id, body.operator))


@router.post(
    "/api/v1/people/{person_id}/approver",
    status_code=202,
    tags=["people"],
    response_model=PersonOut,
    description="Asks to make this person an Approver. Another Approver confirms it.",
    responses={**OPERATORS_ONLY, 404: NO_SUCH_PERSON, 409: RULE_REFUSED},
)
async def ask_approver(
    person_id: UserId, principal: Operator, people: CurrentPeople
) -> PersonOut | JSONResponse:
    return _answer(await people.ask_approver(principal, person_id))


@router.delete(
    "/api/v1/people/{person_id}/approver",
    tags=["people"],
    response_model=PersonOut,
    responses={**OPERATORS_ONLY, 404: NO_SUCH_PERSON, 409: RULE_REFUSED},
)
async def remove_approver(
    person_id: UserId, principal: Operator, people: CurrentPeople
) -> PersonOut | JSONResponse:
    return _answer(await people.remove_approver(principal, person_id))


@router.delete(
    "/api/v1/people/{person_id}",
    status_code=204,
    tags=["people"],
    response_class=Response,
    responses={**OPERATORS_ONLY, 404: NO_SUCH_PERSON, 409: RULE_REFUSED},
)
async def remove_person(person_id: UserId, principal: Operator, people: CurrentPeople) -> Response:
    outcome = await people.remove(principal, person_id)
    if isinstance(outcome, Person):
        return Response(status_code=204)
    answer = _answer(outcome)
    assert isinstance(answer, JSONResponse)
    return answer


@router.get(
    "/api/v1/confirmations",
    tags=["people"],
    description="The setup changes waiting for a second person, and whether you may decide each.",
    responses=SIGNED_IN,
)
async def list_confirmations(
    principal: CurrentPrincipal, people: CurrentPeople
) -> ConfirmationsOut:
    return ConfirmationsOut(
        confirmations=[confirmation_out(row) for row in await people.confirmations(principal)]
    )


def _decide_refused(refused: DecideRefused) -> JSONResponse:
    conflict = refused.reason in (DecideRefusal.ALREADY_DECIDED, DecideRefusal.DIGEST_CHANGED)
    status = 409 if conflict else 403
    body = DecideRefusalOut(refusal=refused.reason.value, message=refused.message)  # type: ignore[arg-type]
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


@router.post(
    "/api/v1/confirmations/{confirmation_id}/decisions",
    status_code=201,
    tags=["people"],
    response_model=ConfirmationDecidedOut,
    responses={
        **SIGNED_IN,
        403: DECIDE_REFUSED,
        404: error_response("No such confirmation"),
        409: DECIDE_REFUSED,
        503: error_response("Settings are off until SETTINGS_ENCRYPTION_KEY is set"),
    },
)
async def decide_confirmation(
    confirmation_id: str,
    body: ConfirmationDecisionIn,
    principal: CurrentPrincipal,
    people: CurrentPeople,
    model_settings: CurrentModelSettings,
) -> ConfirmationDecidedOut | JSONResponse:
    decision = Decision.CONFIRMED if body.verdict == "confirm" else Decision.NOT_NOW
    outcome = await people.decide(principal, confirmation_id, decision, body.digest)
    match outcome:
        case Decided(confirmation):
            return decided_out(confirmation)
        case DecideRefused():
            return _decide_refused(outcome)
        case NotFound():
            raise HTTPException(status_code=404, detail="No such confirmation")
        case ModelAddress(confirmation):
            return await _decide_address(
                confirmation, principal, decision, body.digest, people, model_settings
            )


async def _decide_address(
    confirmation: Confirmation,
    principal: Principal,
    decision: Decision,
    digest: str,
    people: People,
    model_settings: CurrentModelSettings,
) -> ConfirmationDecidedOut | JSONResponse:
    result = await model_settings.decide(principal, decision is Decision.CONFIRMED, digest)
    match result:
        case AddressDecided():
            decided = await people.confirmation(confirmation.id)
            assert decided is not None
            return decided_out(decided)
        case NotAnApprover():
            return _decide_refused(DecideRefused(DecideRefusal.NOT_AN_APPROVER))
        case OwnAddress():
            return _decide_refused(DecideRefused(DecideRefusal.YOU_ASKED))
        case PendingChanged():
            return _decide_refused(DecideRefused(DecideRefusal.DIGEST_CHANGED))
        case NothingPending():
            return _decide_refused(DecideRefused(DecideRefusal.ALREADY_DECIDED))
        case SettingsOff(message):
            raise HTTPException(status_code=503, detail=message)


def decided_out(confirmation: Confirmation) -> ConfirmationDecidedOut:
    assert confirmation.decided_by is not None
    assert confirmation.decision is not None
    assert confirmation.decided_at is not None
    return ConfirmationDecidedOut(
        confirmation_id=confirmation.id,
        kind=confirmation.kind.value,  # type: ignore[arg-type]
        decision=confirmation.decision.value,  # type: ignore[arg-type]
        decided_by=confirmation.decided_by,
        decided_at=confirmation.decided_at,
    )


@router.get(
    "/api/v1/settings/history",
    tags=["settings"],
    description="Every change to people, roles and the AI model: who asked, and who confirmed.",
    responses=SIGNED_IN,
)
async def settings_history(
    principal: CurrentPrincipal, people: CurrentPeople
) -> SettingsHistoryOut:
    return history_out(await people.history(HISTORY_SHOWN))
