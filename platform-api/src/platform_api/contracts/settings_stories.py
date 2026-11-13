from datetime import UTC, datetime

from platform_api.orchestration.agents import Connected, FoundModel, ModelProblem
from platform_api.orchestration.model_settings import (
    ModelChange,
    SettingsState,
    StoredModel,
)
from platform_api.orchestration.settings_http import (
    AwaitingConfirmationOut,
    ConnectionOut,
    ConnectionsView,
    SavedOut,
    view_of,
)
from platform_api.shared import Principal, Role, UserId
from platform_api.wire import WireModel

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
BOB = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
TURNED_ON = datetime(2026, 11, 2, 6, 2, tzinfo=UTC)
ASKED = datetime(2026, 11, 9, 3, 40, tzinfo=UTC)
SENTENCE = "Two new LangGraph releases came out after 1.2.14: 1.2.16 and 1.2.15."

ACTIVE = StoredModel(
    provider="AI Singapore gateway",
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    model="claude-haiku-5-5",
    sealed_key="not stored in fixtures",
    key_hint="x7",
    test_seconds=1.4,
    by=ALICE.user_id,
    by_name=ALICE.display,
    at=TURNED_ON,
)
PENDING = StoredModel(
    provider="ai-gateway.ncs.example",
    style="openai",
    base_url="https://ai-gateway.ncs.example/v1",
    model="ncs-llm-small",
    sealed_key="not stored in fixtures",
    key_hint="q4",
    test_seconds=1.8,
    by=ALICE.user_id,
    by_name=ALICE.display,
    at=ASKED,
)
TURNED_ON_CHANGE = ModelChange(
    TURNED_ON,
    ALICE.user_id,
    "Alice turned on claude-haiku-5-5 (AI Singapore gateway), with a key ending in x7.",
)
ASKED_CHANGE = ModelChange(
    ASKED,
    ALICE.user_id,
    "Alice asked to use ncs-llm-small at ai-gateway.ncs.example. "
    "An Approver must confirm the new address.",
)
ACTIVE_STATE = SettingsState(True, ACTIVE, None, [TURNED_ON_CHANGE])
PENDING_STATE = SettingsState(True, ACTIVE, PENDING, [ASKED_CHANGE, TURNED_ON_CHANGE])


CHECKED = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)


def connections_view() -> ConnectionsView:
    return ConnectionsView(
        connections=[
            ConnectionOut(
                id="jira",
                name="Jira",
                practice=True,
                state="working",
                checked_at=CHECKED,
                last_ok_at=CHECKED,
                problem=None,
                key_ends_in=None,
                expires_at=None,
                fix=None,
            ),
            ConnectionOut(
                id="github",
                name="GitHub",
                practice=False,
                state="working",
                checked_at=CHECKED,
                last_ok_at=CHECKED,
                problem="The key runs out soon.",
                key_ends_in=None,
                expires_at=datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
                fix="Ask whoever set up GitHub for a new key before this one runs out.",
            ),
            ConnectionOut(
                id="teams",
                name="Teams",
                practice=False,
                state="not_answering",
                checked_at=CHECKED,
                last_ok_at=datetime(2026, 11, 8, 3, 0, tzinfo=UTC),
                problem="Teams did not take the last message.",
                key_ends_in=None,
                expires_at=None,
                fix="Ask whoever set up the Teams address to check that it still works.",
            ),
            ConnectionOut(
                id="confluence",
                name="Confluence",
                practice=False,
                state="not_set_up",
                checked_at=None,
                last_ok_at=None,
                problem="Confluence is not connected.",
                key_ends_in=None,
                expires_at=None,
                fix="Ask whoever set up the platform to connect Confluence.",
            ),
            ConnectionOut(
                id="model",
                name="AI model",
                practice=False,
                state="not_set_up",
                checked_at=None,
                last_ok_at=None,
                problem="No AI model is turned on.",
                key_ends_in=None,
                expires_at=None,
                fix="Add an AI model under Settings, AI model.",
            ),
        ],
        you_can_check=True,
    )


def settings_fixtures() -> dict[str, WireModel]:
    return {
        "settings/model.empty.json": view_of(SettingsState(True, None, None, []), ALICE),
        "settings/model.active.json": view_of(ACTIVE_STATE, ALICE),
        "settings/model.pending.alice.json": view_of(PENDING_STATE, ALICE),
        "settings/model.pending.bob.json": view_of(PENDING_STATE, BOB),
        "settings/connections.json": connections_view(),
        "settings/connection.checked.json": connections_view().connections[0],
        "settings/connection.not_checked.json": ConnectionOut(
            id="teams",
            name="Teams",
            practice=False,
            state="not_checked",
            checked_at=None,
            last_ok_at=None,
            problem="Not checked yet. Teams is tried when the first approval request is sent.",
            key_ends_in=None,
            expires_at=None,
            fix=None,
        ),
        "settings/connect.connected.json": Connected(
            style="anthropic",
            base_url="https://llm-gateway.aisg.sg",
            models=[
                FoundModel(id="claude-haiku-5-5", display="Claude Haiku 5.5", suggested=True),
                FoundModel(id="claude-sonnet-5-5", display="Claude Sonnet 5.5", suggested=False),
                FoundModel(id="claude-opus-5-5", display="Claude Opus 5.5", suggested=False),
            ],
        ),
        "settings/connect.problem.json": ModelProblem(
            reason="key_refused",
            message="The address answered, but it refused this key. Check that you copied all of "
            "it.",
        ),
        "settings/save.saved.json": SavedOut(seconds=1.4, text=SENTENCE),
        "settings/save.awaiting_confirmation.json": AwaitingConfirmationOut(
            seconds=1.8, text=SENTENCE
        ),
        "settings/save.too_slow.json": ModelProblem(
            reason="too_slow",
            message="The model answered in 11.2 seconds. Summaries wait 10 seconds, so runs would "
            "use the built-in sentence. Pick a faster model.",
        ),
    }
