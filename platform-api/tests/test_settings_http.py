from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.orchestration.agents import Connected, FoundModel, ModelProblem, ModelTestPassed
from platform_api.orchestration.model_settings import (
    AddressDecided,
    KeyNeeded,
    NothingPending,
    OwnAddress,
    PendingChanged,
    RuntimeDown,
    Saved,
    SettingsOff,
    SettingsState,
    StoredModel,
)
from platform_api.shared import UserId
from tests.declared import ALICE, BOB, app_with, declared_status

CAROL = {"X-Dev-User": "carol"}
AT = datetime(2026, 10, 24, 6, 2, tzinfo=UTC)
KEY = "sk-example-key-not-real-x7"
ACTIVE = StoredModel(
    provider="AI Singapore gateway",
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    model="claude-haiku-5-5",
    sealed_key="sealed-text-not-a-key",
    key_hint="x7",
    test_seconds=1.4,
    by=UserId("alice"),
    by_name="Alice",
    at=AT,
)
PENDING = StoredModel(
    provider="ai-gateway.ncs.example",
    style="openai",
    base_url="https://ai-gateway.ncs.example/v1",
    model="ncs-llm-small",
    sealed_key="sealed-text-not-a-key",
    key_hint="q4",
    test_seconds=1.8,
    by=UserId("alice"),
    by_name="Alice",
    at=AT,
)
PASSED = ModelTestPassed(seconds=1.4, text="Two new releases came out.")
CONNECTED = Connected(
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    models=[FoundModel(id="claude-haiku-5-5", display="Claude Haiku 5.5", suggested=True)],
)
PROBLEM = ModelProblem(reason="key_refused", message="The address refused this key.")


@dataclass
class FakeModelSettings:
    state: SettingsState = field(default_factory=lambda: SettingsState(True, ACTIVE, PENDING, []))
    connected: object = field(default_factory=lambda: CONNECTED)
    saved: object = field(default_factory=lambda: Saved(PASSED, awaiting_confirmation=False))
    off: object = None
    decided: object = field(default_factory=lambda: AddressDecided(confirmed=True))
    calls: list[tuple[str, object]] = field(default_factory=list[tuple[str, object]])

    async def view(self) -> SettingsState:
        return self.state

    async def connect(self, principal: object, *args: object) -> object:
        self.calls.append(("connect", args))
        return self.connected

    async def save(self, principal: object, *args: object) -> object:
        self.calls.append(("save", args))
        return self.saved

    async def turn_off(self, principal: object) -> object:
        return self.off

    async def decide(self, principal: object, confirm: bool, digest: str) -> object:
        self.calls.append(("decide", (confirm, digest)))
        return self.decided


def app_for(settings: FakeModelSettings) -> FastAPI:
    app = app_with()
    app.state.model_settings = settings
    return app


MODEL = "/api/v1/settings/model"
CONNECT = "/api/v1/settings/model/connect"
DECISION = "/api/v1/settings/model/address-decision"
CONNECT_BODY = {"provider_id": "aisg", "api_key": KEY}
SAVE_BODY = {
    "style": "anthropic",
    "base_url": "https://llm-gateway.aisg.sg",
    "model": "claude-haiku-5-5",
    "api_key": KEY,
}
CONFIRM = {"verdict": "confirm", "digest": "sha256:" + "0" * 64}


def fake(**changes: object) -> FakeModelSettings:
    return FakeModelSettings(**changes)  # type: ignore[arg-type]


CASES = [
    pytest.param("GET", MODEL, {}, None, fake(), 401, id="view-401"),
    pytest.param("GET", MODEL, BOB, None, fake(), 200, id="view-200"),
    pytest.param("POST", CONNECT, {}, CONNECT_BODY, fake(), 401, id="connect-401"),
    pytest.param("POST", CONNECT, BOB, CONNECT_BODY, fake(), 403, id="connect-403"),
    pytest.param("POST", CONNECT, ALICE, CONNECT_BODY, fake(), 200, id="connect-200"),
    pytest.param(
        "POST", CONNECT, ALICE, CONNECT_BODY, fake(connected=PROBLEM), 200, id="connect-problem"
    ),
    pytest.param(
        "POST", CONNECT, ALICE, CONNECT_BODY, fake(connected=KeyNeeded("x")), 409, id="connect-409"
    ),
    pytest.param(
        "POST", CONNECT, ALICE, CONNECT_BODY, fake(connected=RuntimeDown()), 502, id="connect-502"
    ),
    pytest.param(
        "POST", CONNECT, ALICE, CONNECT_BODY, fake(connected=SettingsOff()), 503, id="connect-503"
    ),
    pytest.param("PUT", MODEL, {}, SAVE_BODY, fake(), 401, id="save-401"),
    pytest.param("PUT", MODEL, BOB, SAVE_BODY, fake(), 403, id="save-403"),
    pytest.param("PUT", MODEL, ALICE, SAVE_BODY, fake(), 200, id="save-200"),
    pytest.param("PUT", MODEL, ALICE, SAVE_BODY, fake(saved=PROBLEM), 200, id="save-problem"),
    pytest.param("PUT", MODEL, ALICE, SAVE_BODY, fake(saved=KeyNeeded("x")), 409, id="save-409"),
    pytest.param("PUT", MODEL, ALICE, SAVE_BODY, fake(saved=RuntimeDown()), 502, id="save-502"),
    pytest.param("PUT", MODEL, ALICE, SAVE_BODY, fake(saved=SettingsOff()), 503, id="save-503"),
    pytest.param("DELETE", MODEL, {}, None, fake(), 401, id="off-401"),
    pytest.param("DELETE", MODEL, BOB, None, fake(), 403, id="off-403"),
    pytest.param("DELETE", MODEL, ALICE, None, fake(off=SettingsOff()), 503, id="off-503"),
    pytest.param("POST", DECISION, {}, CONFIRM, fake(), 401, id="decide-401"),
    pytest.param("POST", DECISION, CAROL, CONFIRM, fake(), 403, id="decide-not-approver"),
    pytest.param("POST", DECISION, BOB, CONFIRM, fake(), 200, id="decide-200"),
    pytest.param(
        "POST", DECISION, ALICE, CONFIRM, fake(decided=OwnAddress()), 403, id="decide-own"
    ),
    pytest.param(
        "POST", DECISION, BOB, CONFIRM, fake(decided=NothingPending()), 404, id="decide-404"
    ),
    pytest.param("POST", DECISION, BOB, CONFIRM, fake(decided=SettingsOff()), 503, id="decide-503"),
    pytest.param(
        "POST", DECISION, BOB, CONFIRM, fake(decided=PendingChanged()), 409, id="decide-409"
    ),
]


@pytest.mark.parametrize(("method", "path", "headers", "body", "settings", "status"), CASES)
def test_the_route_answers_the_status_and_declares_it(
    method: str,
    path: str,
    headers: dict[str, str],
    body: object,
    settings: FakeModelSettings,
    status: int,
):
    app = app_for(settings)
    response = TestClient(app).request(method, path, headers=headers, json=body)
    assert response.status_code == status
    declared_status(app, method, path, response)


def test_turning_the_model_off_answers_no_content():
    response = TestClient(app_for(fake())).delete(MODEL, headers=ALICE)
    assert response.status_code == 204


def view_as(
    headers: dict[str, str], settings: FakeModelSettings | None = None
) -> dict[str, object]:
    response = TestClient(app_for(settings or fake())).get(MODEL, headers=headers)
    return response.json()


def test_an_approver_who_did_not_enter_the_address_can_decide():
    pending = view_as(BOB)["pending"]
    assert isinstance(pending, dict)
    assert (pending["you_can_decide"], pending["why_not"]) == (True, None)


def test_the_person_who_entered_the_address_is_told_why_not():
    pending = view_as(ALICE)["pending"]
    assert isinstance(pending, dict)
    assert pending["you_can_decide"] is False
    assert pending["why_not"] == "You entered this address, so another Approver must confirm it."


def test_an_operator_who_is_not_an_approver_is_told_why_not():
    pending = view_as(CAROL)["pending"]
    assert isinstance(pending, dict)
    assert pending["why_not"] == "Only an Approver can confirm an address."


def test_only_operators_may_change_settings():
    assert view_as(ALICE)["you_can_change"] is True
    assert view_as(BOB)["you_can_change"] is False


def test_the_view_never_holds_the_sealed_key():
    response = TestClient(app_for(fake())).get(MODEL, headers=BOB)
    assert "sealed-text-not-a-key" not in response.text
    assert "sealed_key" not in response.text


def test_settings_that_are_off_say_why_and_allow_no_change():
    off = fake(state=SettingsState(False, None, None, []))
    view = view_as(ALICE, off)
    assert view["available"] is False
    assert view["you_can_change"] is False
    assert view["unavailable_message"] == SettingsOff().message


def test_a_save_at_a_new_address_answers_awaiting_confirmation():
    settings = fake(saved=Saved(PASSED, awaiting_confirmation=True))
    response = TestClient(app_for(settings)).put(MODEL, headers=ALICE, json=SAVE_BODY)
    assert response.json() == {
        "status": "awaiting_confirmation",
        "seconds": 1.4,
        "text": "Two new releases came out.",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": KEY},
        {"provider_id": "aisg", "base_url": "https://llm-gateway.aisg.sg", "api_key": KEY},
        {"provider_id": "aisg"},
        {"provider_id": "nobody", "api_key": KEY},
    ],
    ids=["no address", "both addresses", "no key", "unknown provider"],
)
def test_a_connect_request_must_name_one_address_and_a_key(body: dict[str, object]):
    settings = fake()
    response = TestClient(app_for(settings)).post(CONNECT, headers=ALICE, json=body)
    assert response.status_code == 422
    assert settings.calls == []


def test_the_saved_key_can_stand_in_for_a_pasted_one():
    settings = fake()
    body = {"base_url": "https://llm-gateway.aisg.sg", "use_saved_key": True}
    response = TestClient(app_for(settings)).post(CONNECT, headers=ALICE, json=body)
    assert response.status_code == 200
    assert settings.calls == [("connect", (None, "https://llm-gateway.aisg.sg", None, True))]


def test_a_decision_must_quote_the_digest_of_what_was_seen():
    settings = fake()
    response = TestClient(app_for(settings)).post(
        DECISION, headers=BOB, json={"verdict": "confirm"}
    )
    assert response.status_code == 422
    assert settings.calls == []


def test_the_waiting_entry_carries_its_digest():
    pending = view_as(BOB)["pending"]
    assert isinstance(pending, dict)
    assert str(pending["digest"]).startswith("sha256:")
