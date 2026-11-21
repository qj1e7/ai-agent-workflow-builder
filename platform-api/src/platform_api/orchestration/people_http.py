from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.orchestration.confirmations import (
    HISTORY_SHOWN,
    Confirmation,
    ConfirmationDecision,
    ConfirmationKind,
    DecideRefusal,
    DecideRefused,
    confirmation_summary,
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
from platform_api.orchestration.n8n_staff import StaffAccounts
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
from platform_api.wire import ErrorBody, WireIn, WireModel, error_response

router = APIRouter()

type SettingsArea = Literal["people", "model"]
type N8nAccountState = Literal["none", "invited", "ready"]


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
    n8n_access: bool = Field(
        description="Whether this person may open workflows in n8n's editor. Only an Operator "
        "who is no Approver holds it, and gaining the Approver role ends it."
    )
    n8n_account: N8nAccountState = Field(
        description="The n8n account the platform made for this person. invited: they have not "
        "set their n8n password yet. none: there is none, as while n8n access is off, or before "
        "the platform has made it."
    )
    added_by: UserId
    added_at: datetime


class PeopleOut(WireModel):
    people: list[PersonOut]


class AddPersonIn(WireIn):
    email: str = Field(min_length=3, max_length=MAX_EMAIL_CHARS)
    display: str = Field(min_length=1, max_length=MAX_DISPLAY_CHARS)
    operator: bool = False
    approver: bool = Field(
        default=False, description="Asks for the role. Another Approver confirms it."
    )


class OperatorIn(WireIn):
    operator: bool


class N8nAccessIn(WireIn):
    n8n_access: bool


class PeopleRefusalOut(WireModel):
    refusal: PeopleRefusal
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
    why_not: DecideRefusal | None


class ConfirmationsOut(WireModel):
    confirmations: list[ConfirmationOut]


class ConfirmationDecisionIn(WireIn):
    verdict: Literal["confirm", "not_now"]
    digest: str


class ConfirmationDecidedOut(WireModel):
    confirmation_id: str
    kind: ConfirmationKind
    decision: ConfirmationDecision
    decided_by: UserId
    decided_at: datetime


class DecideRefusalOut(WireModel):
    refusal: DecideRefusal
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


class MyN8nOut(WireModel):
    access: bool = Field(description="Whether an Operator gave you n8n access.")
    account: N8nAccountState
    set_password_url: str | None = Field(
        description="Your one link to set your n8n password, until you have used it. Shown "
        "only to you, and never sent anywhere else."
    )
    can_open: bool = Field(description="Whether you can open workflows in n8n now.")
    why_not: str | None = Field(description="Why not, in words to show. Null when you can.")
    editor_url: str | None = Field(description="n8n's editor, while you can open it.")
    login: str | None = Field(
        description="The email you sign in to n8n with, as n8n holds it now. Open in n8n moves "
        "a workflow into this account's space, so only it sees the workflow. Null without n8n "
        "access, before your n8n account is made, or when n8n can't say."
    )


def current_staff(request: Request) -> StaffAccounts:
    staff: StaffAccounts = request.app.state.staff
    return staff


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
        n8n_access=p.n8n_access,
        n8n_account=(
            "none" if p.n8n_account is None else "invited" if p.n8n_account.pending else "ready"
        ),
        added_by=p.added_by,
        added_at=p.added_at,
    )


def confirmation_out(row: ConfirmationRow) -> ConfirmationOut:
    c = row.confirmation
    return ConfirmationOut(
        confirmation_id=c.id,
        kind=c.kind,
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
        why_not=row.why_not,
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


def _refusal(outcome: Refused | NotFound) -> JSONResponse:
    match outcome:
        case NotFound():
            raise HTTPException(status_code=404, detail="No such person on the list")
        case Refused(reason=PeopleRefusal.NOT_AN_OPERATOR):
            raise HTTPException(status_code=403, detail=outcome.message)
        case Refused():
            body = PeopleRefusalOut(refusal=outcome.reason, message=outcome.message)
            return JSONResponse(status_code=409, content=body.model_dump(mode="json"))


def _answer(outcome: Person | PersonRow | Refused | NotFound) -> PersonOut | JSONResponse:
    match outcome:
        case Person():
            return person_out(PersonRow(outcome, None))
        case PersonRow():
            return person_out(outcome)
        case _:
            return _refusal(outcome)


@router.get(
    "/api/v1/me/n8n",
    tags=["people"],
    response_model=MyN8nOut,
    description="Your own n8n account, and the link to set your n8n password while you have "
    "not used it (ENGINE-PLAN 2.9).",
    responses=SIGNED_IN,
)
async def my_n8n(
    principal: CurrentPrincipal, staff: Annotated[StaffAccounts, Depends(current_staff)]
) -> JSONResponse:
    mine = await staff.mine(principal.user_id)
    body = MyN8nOut(
        access=mine.access,
        account=mine.account,
        set_password_url=mine.set_password_url,
        can_open=mine.can_open,
        why_not=mine.why_not,
        editor_url=mine.editor_url,
        login=await staff.login_of(principal.user_id),
    )
    return JSONResponse(body.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


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


@router.put(
    "/api/v1/people/{person_id}/n8n-access",
    tags=["people"],
    response_model=PersonOut,
    description="Gives or ends n8n access. The platform makes or ends the person's n8n account "
    "within a minute, and only while staff access to n8n is on.",
    responses={**OPERATORS_ONLY, 404: NO_SUCH_PERSON, 409: RULE_REFUSED},
)
async def set_n8n_access(
    person_id: UserId, body: N8nAccessIn, principal: Operator, people: CurrentPeople
) -> PersonOut | JSONResponse:
    return _answer(await people.set_n8n_access(principal, person_id, body.n8n_access))


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
    return _refusal(outcome)


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
    body = DecideRefusalOut(refusal=refused.reason, message=refused.message)
    return JSONResponse(status_code=409 if conflict else 403, content=body.model_dump(mode="json"))


@router.post(
    "/api/v1/confirmations/{confirmation_id}/decisions",
    status_code=201,
    tags=["people"],
    response_model=ConfirmationDecidedOut,
    responses={
        **SIGNED_IN,
        403: {
            "model": DecideRefusalOut | ErrorBody,
            "description": "This person cannot decide this, or is not on the People list",
        },
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
    decision = (
        ConfirmationDecision.CONFIRMED
        if body.verdict == "confirm"
        else ConfirmationDecision.NOT_NOW
    )
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
    decision: ConfirmationDecision,
    digest: str,
    people: People,
    model_settings: CurrentModelSettings,
) -> ConfirmationDecidedOut | JSONResponse:
    result = await model_settings.decide(
        principal, decision is ConfirmationDecision.CONFIRMED, digest, confirmation.id
    )
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
        kind=confirmation.kind,
        decision=confirmation.decision,
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
