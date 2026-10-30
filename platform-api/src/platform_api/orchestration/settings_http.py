from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, model_validator

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.orchestration.agents import ConnectResult, ModelProblem, ModelStyle
from platform_api.orchestration.http import Operator
from platform_api.orchestration.model_settings import (
    KNOWN_PROVIDERS,
    AddressDecided,
    KeyNeeded,
    KnownProviderId,
    ModelSettings,
    NotAnApprover,
    NothingPending,
    OwnAddress,
    PendingChanged,
    RuntimeDown,
    Saved,
    SettingsOff,
    SettingsState,
    StoredModel,
)
from platform_api.shared import Principal, Role, UserId
from platform_api.wire import WireIn, WireModel, error_response

router = APIRouter()

KEY_DESCRIPTION = (
    "Sent once and stored sealed. It is never sent back, only its last two characters."
)


class KnownProviderOut(WireModel):
    id: KnownProviderId
    name: str
    base_url: str


class ModelOut(WireModel):
    provider: str = Field(description="The known provider's name, or the address's host.")
    style: ModelStyle
    base_url: str
    model: str
    key_hint: str = Field(description="The key's last two characters.")
    test_seconds: float
    by: UserId
    by_name: str
    at: datetime


class PendingModelOut(ModelOut):
    digest: str = Field(description="Quote it in the decision, so it applies to this entry only.")
    you_can_decide: bool
    why_not: str | None


class ModelChangeOut(WireModel):
    at: datetime
    by: UserId = Field(description="Whose change it is: the person who made it, or who asked.")
    confirmed_by: UserId | None = Field(
        default=None, description="The Approver who decided it, when a second person was needed."
    )
    summary: str


class ModelSettingsView(WireModel):
    available: bool
    unavailable_message: str | None
    you_can_change: bool
    active: ModelOut | None
    pending: PendingModelOut | None
    providers: list[KnownProviderOut]
    changes: list[ModelChangeOut]


class ConnectIn(WireIn):
    provider_id: KnownProviderId | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(
        default=None, max_length=4096, repr=False, description=KEY_DESCRIPTION
    )
    use_saved_key: bool = False

    @model_validator(mode="after")
    def _one_address_and_a_key(self) -> Self:
        if (self.provider_id is None) == (self.base_url is None):
            raise ValueError("Give provider_id or base_url, not both.")
        if not self.use_saved_key and not self.api_key:
            raise ValueError("Paste the key, or set use_saved_key.")
        return self


class SaveIn(WireIn):
    style: ModelStyle
    base_url: str = Field(max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(
        default=None, max_length=4096, repr=False, description=KEY_DESCRIPTION
    )
    use_saved_key: bool = False

    @model_validator(mode="after")
    def _a_key(self) -> Self:
        if not self.use_saved_key and not self.api_key:
            raise ValueError("Paste the key, or set use_saved_key.")
        return self


class SavedOut(WireModel):
    status: Literal["saved"] = "saved"
    seconds: float
    text: str


class AwaitingConfirmationOut(WireModel):
    status: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    seconds: float
    text: str


type SaveOut = Annotated[
    SavedOut | AwaitingConfirmationOut | ModelProblem, Field(discriminator="status")
]


class AddressDecisionIn(WireIn):
    verdict: Literal["confirm", "decline"]
    digest: str = Field(description="The digest of the waiting entry the Approver looked at.")


def current_model_settings(request: Request) -> ModelSettings:
    settings: ModelSettings = request.app.state.model_settings
    return settings


def require_approver(principal: CurrentPrincipal) -> Principal:
    if Role.APPROVER not in principal.roles:
        raise HTTPException(
            status_code=403, detail="Only an Approver can confirm an address. Ask an Approver."
        )
    return principal


CurrentModelSettings = Annotated[ModelSettings, Depends(current_model_settings)]
Approver = Annotated[Principal, Depends(require_approver)]

SETTINGS_OFF = error_response("Settings are off until SETTINGS_ENCRYPTION_KEY is set")
RUNTIME_DOWN = error_response("The agent runtime did not answer, so nothing was checked")
WRONG_SAVED_KEY = error_response("The saved key belongs to another address, or no longer opens")


def _model_out(model: StoredModel) -> ModelOut:
    return ModelOut(
        provider=model.provider,
        style=model.style,
        base_url=model.base_url,
        model=model.model,
        key_hint=model.key_hint,
        test_seconds=model.test_seconds,
        by=model.by,
        by_name=model.by_name,
        at=model.at,
    )


def view_of(state: SettingsState, principal: Principal) -> ModelSettingsView:
    pending = None
    if state.pending is not None:
        own = state.pending.by == principal.user_id
        approver = Role.APPROVER in principal.roles
        why_not = None
        if own:
            why_not = OwnAddress().message
        elif not approver:
            why_not = "Only an Approver can confirm an address."
        pending = PendingModelOut(
            **_model_out(state.pending).model_dump(),
            digest=state.pending.digest,
            you_can_decide=why_not is None,
            why_not=why_not,
        )
    return ModelSettingsView(
        available=state.available,
        unavailable_message=None if state.available else SettingsOff().message,
        you_can_change=state.available and Role.OPERATOR in principal.roles,
        active=_model_out(state.active) if state.active is not None else None,
        pending=pending,
        providers=[
            KnownProviderOut(id=p.id, name=p.name, base_url=p.base_url) for p in KNOWN_PROVIDERS
        ],
        changes=[
            ModelChangeOut(at=c.at, by=c.by, confirmed_by=c.confirmed_by, summary=c.summary)
            for c in state.changes
        ],
    )


@router.get("/api/v1/settings/model", tags=["settings"], responses=SIGNED_IN)
async def get_model_settings(
    principal: CurrentPrincipal, settings: CurrentModelSettings
) -> ModelSettingsView:
    return view_of(await settings.view(), principal)


@router.post(
    "/api/v1/settings/model/connect",
    tags=["settings"],
    responses={**OPERATORS_ONLY, 409: WRONG_SAVED_KEY, 502: RUNTIME_DOWN, 503: SETTINGS_OFF},
)
async def connect_model(
    body: ConnectIn, principal: Operator, settings: CurrentModelSettings
) -> ConnectResult:
    result = await settings.connect(
        principal, body.provider_id, body.base_url, body.api_key, body.use_saved_key
    )
    match result:
        case SettingsOff(message):
            raise HTTPException(status_code=503, detail=message)
        case KeyNeeded(message):
            raise HTTPException(status_code=409, detail=message)
        case RuntimeDown(message):
            raise HTTPException(status_code=502, detail=message)
        case _:
            return result


@router.put(
    "/api/v1/settings/model",
    tags=["settings"],
    responses={**OPERATORS_ONLY, 409: WRONG_SAVED_KEY, 502: RUNTIME_DOWN, 503: SETTINGS_OFF},
)
async def save_model(body: SaveIn, principal: Operator, settings: CurrentModelSettings) -> SaveOut:
    result = await settings.save(
        principal, body.style, body.base_url, body.model, body.api_key, body.use_saved_key
    )
    match result:
        case Saved(test, awaiting_confirmation=True):
            return AwaitingConfirmationOut(seconds=test.seconds, text=test.text)
        case Saved(test):
            return SavedOut(seconds=test.seconds, text=test.text)
        case SettingsOff(message):
            raise HTTPException(status_code=503, detail=message)
        case KeyNeeded(message):
            raise HTTPException(status_code=409, detail=message)
        case RuntimeDown(message):
            raise HTTPException(status_code=502, detail=message)
        case ModelProblem():
            return result


@router.delete(
    "/api/v1/settings/model",
    status_code=204,
    tags=["settings"],
    responses={**OPERATORS_ONLY, 503: SETTINGS_OFF},
)
async def turn_model_off(principal: Operator, settings: CurrentModelSettings) -> Response:
    if isinstance(off := await settings.turn_off(principal), SettingsOff):
        raise HTTPException(status_code=503, detail=off.message)
    return Response(status_code=204)


@router.post(
    "/api/v1/settings/model/address-decision",
    tags=["settings"],
    responses={
        **SIGNED_IN,
        403: error_response("Not an Approver, or the person who entered the address"),
        404: error_response("No address is waiting for confirmation"),
        409: error_response("The waiting address changed after it was seen"),
        503: SETTINGS_OFF,
    },
)
async def decide_address(
    body: AddressDecisionIn, principal: Approver, settings: CurrentModelSettings
) -> ModelSettingsView:
    result = await settings.decide(principal, body.verdict == "confirm", body.digest)
    match result:
        case AddressDecided():
            return view_of(await settings.view(), principal)
        case OwnAddress(message) | NotAnApprover(message):
            raise HTTPException(status_code=403, detail=message)
        case PendingChanged(message):
            raise HTTPException(status_code=409, detail=message)
        case NothingPending():
            raise HTTPException(status_code=404, detail="No address is waiting for confirmation")
        case SettingsOff(message):
            raise HTTPException(status_code=503, detail=message)
