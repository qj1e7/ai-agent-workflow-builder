import asyncio
from dataclasses import dataclass, field

import psycopg
import pytest

from platform_api.db import Database
from platform_api.orchestration.agents import (
    AgentUnavailable,
    Connected,
    ConnectRequest,
    FoundModel,
    ModelAccess,
    ModelProblem,
    ModelTestPassed,
)
from platform_api.orchestration.model_settings import (
    AddressDecided,
    KeyBox,
    KeyNeeded,
    ModelSettings,
    NothingPending,
    OwnAddress,
    PendingChanged,
    RuntimeDown,
    Saved,
    SettingsOff,
)
from platform_api.shared import Principal, Role, UserId
from tests.conftest import PostgresUrls

pytestmark = pytest.mark.anyio

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
BOB = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
KEY = "sk-example-key-not-real-x7"
NEW_KEY = "sk-another-key-not-real-k2"
AISG = "https://llm-gateway.aisg.sg"
NCS = "https://ai-gateway.ncs.example/v1"
PASSED = ModelTestPassed(seconds=1.4, text="Two new LangGraph releases came out.")
SECRET = "test-settings-secret-not-real"


@dataclass
class FakeChecks:
    test_result: object = field(default_factory=lambda: PASSED)
    connect_result: object = field(
        default_factory=lambda: Connected(
            style="anthropic",
            base_url=AISG,
            models=[FoundModel(id="claude-haiku-5-5", display="Claude Haiku 5.5", suggested=True)],
        )
    )
    connected: list[ConnectRequest] = field(default_factory=list[ConnectRequest])
    tested: list[ModelAccess] = field(default_factory=list[ModelAccess])

    async def connect_model(self, request: ConnectRequest) -> object:
        self.connected.append(request)
        return self.connect_result

    async def test_model(self, access: ModelAccess) -> object:
        self.tested.append(access)
        return self.test_result


def settings_for(db: Database, checks: FakeChecks | None = None, secret: str | None = SECRET):
    return ModelSettings(db, checks or FakeChecks(), KeyBox(secret) if secret else None)  # type: ignore[arg-type]


async def save(settings: ModelSettings, who: Principal = ALICE, **changes: object) -> object:
    values: dict[str, object] = {
        "style": "anthropic",
        "base_url": AISG,
        "model": "claude-haiku-5-5",
        "api_key": KEY,
        "use_saved_key": False,
    }
    values.update(changes)
    return await settings.save(who, **values)  # type: ignore[arg-type]


async def runs_use(db: Database, settings: ModelSettings) -> ModelAccess | None:
    async with db.transaction("orchestration") as uow:
        return await settings.access(uow)


async def waiting(settings: ModelSettings) -> str:
    pending = (await settings.view()).pending
    return pending.digest if pending is not None else "sha256:none"


async def summaries(settings: ModelSettings) -> list[str]:
    return [c.summary for c in (await settings.view()).changes]


async def test_nothing_is_set_at_first(db: Database):
    state = await settings_for(db).view()
    assert state.available
    assert (state.active, state.pending, state.changes) == (None, None, [])
    assert await runs_use(db, settings_for(db)) is None


async def test_a_tested_model_at_a_known_provider_is_saved_and_runs_use_it(db: Database):
    settings = settings_for(db)
    assert await save(settings) == Saved(PASSED, awaiting_confirmation=False)
    state = await settings.view()
    assert state.active is not None
    assert (state.active.provider, state.active.model, state.active.key_hint) == (
        "AI Singapore gateway",
        "claude-haiku-5-5",
        "x7",
    )
    assert await runs_use(db, settings) == ModelAccess(
        style="anthropic", base_url=AISG, model="claude-haiku-5-5", api_key=KEY
    )
    assert await summaries(settings) == [
        "Alice turned on claude-haiku-5-5 (AI Singapore gateway), with a key ending in x7."
    ]


async def test_the_key_is_stored_sealed_and_never_in_plain_text(db: Database):
    settings = settings_for(db)
    await save(settings)
    async with db.connection("orchestration") as conn:
        rows = await (await conn.execute("SELECT * FROM orchestration.model_setting")).fetchall()
        log = await (await conn.execute("SELECT * FROM orchestration.settings_changes")).fetchall()
    assert rows
    assert KEY not in str(rows)
    assert KEY not in str(log)


async def test_a_failed_test_saves_nothing(db: Database):
    refused = ModelProblem(reason="key_refused", message="The address refused this key.")
    settings = settings_for(db, FakeChecks(test_result=refused))
    assert await save(settings) == refused
    state = await settings.view()
    assert (state.active, state.pending, state.changes) == (None, None, [])


async def test_the_agent_runtime_being_down_saves_nothing(db: Database):
    settings = settings_for(db, FakeChecks(test_result=AgentUnavailable("refused")))
    assert isinstance(await save(settings), RuntimeDown)
    assert (await settings.view()).active is None


async def test_a_new_address_waits_for_an_approver_and_runs_keep_the_old_model(db: Database):
    settings = settings_for(db)
    await save(settings)
    outcome = await save(
        settings, style="openai", base_url=NCS, model="ncs-llm-small", api_key=NEW_KEY
    )
    assert outcome == Saved(PASSED, awaiting_confirmation=True)
    state = await settings.view()
    assert state.pending is not None
    assert (state.pending.provider, state.pending.by) == ("ai-gateway.ncs.example", "alice")
    access = await runs_use(db, settings)
    assert access is not None
    assert access.model == "claude-haiku-5-5"
    assert (await summaries(settings))[0] == (
        "Alice asked to use ncs-llm-small at ai-gateway.ncs.example. "
        "An Approver must confirm the new address."
    )


async def test_the_person_who_entered_an_address_cannot_confirm_it(db: Database):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    assert isinstance(
        await settings.decide(ALICE, confirm=True, digest=await waiting(settings)), OwnAddress
    )
    assert (await settings.view()).pending is not None


async def test_another_approver_confirms_and_runs_switch(db: Database):
    settings = settings_for(db)
    await save(settings)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small", api_key=NEW_KEY)
    assert await settings.decide(
        BOB, confirm=True, digest=await waiting(settings)
    ) == AddressDecided(confirmed=True)
    state = await settings.view()
    assert state.pending is None
    assert await runs_use(db, settings) == ModelAccess(
        style="openai", base_url=NCS, model="ncs-llm-small", api_key=NEW_KEY
    )
    assert (await summaries(settings))[0] == (
        "Bob confirmed ai-gateway.ncs.example. Runs now use ncs-llm-small."
    )


async def test_a_confirmed_address_needs_no_second_confirmation(db: Database):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    await settings.decide(BOB, confirm=True, digest=await waiting(settings))
    outcome = await save(settings, style="openai", base_url=NCS, model="ncs-llm-large")
    assert outcome == Saved(PASSED, awaiting_confirmation=False)


async def test_declining_deletes_the_waiting_key(db: Database):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    assert await settings.decide(
        BOB, confirm=False, digest=await waiting(settings)
    ) == AddressDecided(confirmed=False)
    assert (await settings.view()).pending is None
    async with db.connection("orchestration") as conn:
        rows = await (await conn.execute("SELECT * FROM orchestration.model_setting")).fetchall()
    assert rows == []
    assert (await summaries(settings))[0] == (
        "Bob declined ai-gateway.ncs.example, and its key was deleted."
    )


async def test_deciding_with_nothing_waiting_says_so(db: Database):
    assert isinstance(
        await settings_for(db).decide(BOB, confirm=True, digest="sha256:none"), NothingPending
    )


async def test_the_saved_key_is_reused_only_at_the_same_host(db: Database):
    checks = FakeChecks()
    settings = settings_for(db, checks)
    await save(settings)
    await save(settings, model="claude-sonnet-5-5", api_key=None, use_saved_key=True)
    assert checks.tested[-1].api_key == KEY
    elsewhere = await save(settings, base_url=NCS, api_key=None, use_saved_key=True)
    assert isinstance(elsewhere, KeyNeeded)


async def test_connect_with_a_known_provider_uses_its_address(db: Database):
    checks = FakeChecks()
    found = await settings_for(db, checks).connect(
        ALICE, provider_id="aisg", base_url=None, api_key=KEY, use_saved_key=False
    )
    assert isinstance(found, Connected)
    assert [(r.base_url, r.api_key) for r in checks.connected] == [(AISG, KEY)]


async def test_connect_with_the_saved_key_needs_a_saved_model_at_that_host(db: Database):
    settings = settings_for(db)
    found = await settings.connect(
        ALICE, provider_id=None, base_url=NCS, api_key=None, use_saved_key=True
    )
    assert isinstance(found, KeyNeeded)


async def test_changes_are_logged_in_plain_words(db: Database):
    settings = settings_for(db)
    await save(settings)
    await save(settings, model="claude-sonnet-5-5", api_key=None, use_saved_key=True)
    await save(settings, model="claude-sonnet-5-5", api_key=NEW_KEY)
    await save(settings, model="claude-sonnet-5-5", api_key=None, use_saved_key=True)
    assert await summaries(settings) == [
        "Alice replaced the key, now ending in k2.",
        "Alice switched to claude-sonnet-5-5 (AI Singapore gateway).",
        "Alice turned on claude-haiku-5-5 (AI Singapore gateway), with a key ending in x7.",
    ]


async def test_turning_off_deletes_the_key_and_runs_go_back_to_the_template(db: Database):
    settings = settings_for(db)
    await save(settings)
    assert await settings.turn_off(ALICE) is None
    assert await runs_use(db, settings) is None
    assert (await summaries(settings))[0] == (
        "Alice turned the AI model off, and the saved key was deleted."
    )


async def test_without_an_encryption_key_settings_are_off(db: Database):
    settings = settings_for(db, secret=None)
    assert not (await settings.view()).available
    assert isinstance(await save(settings), SettingsOff)
    assert isinstance(await settings.turn_off(ALICE), SettingsOff)
    assert await runs_use(db, settings) is None


async def test_a_key_sealed_under_another_secret_gives_runs_no_model(db: Database):
    await save(settings_for(db, secret="first-secret-not-real"))
    assert await runs_use(db, settings_for(db, secret="second-secret-not-real")) is None


def test_a_sealed_key_opens_only_with_the_same_secret():
    sealed = KeyBox("one").seal(KEY)
    assert KEY not in sealed
    assert KeyBox("one").open(sealed) == KEY
    assert KeyBox("two").open(sealed) is None


async def test_a_decision_on_an_address_that_changed_since_it_was_seen_is_refused(db: Database):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    seen = await waiting(settings)
    await save(settings, style="openai", base_url="https://elsewhere.example/v1", model="other")
    assert isinstance(await settings.decide(BOB, confirm=True, digest=seen), PendingChanged)
    state = await settings.view()
    assert state.pending is not None
    assert state.pending.base_url == "https://elsewhere.example/v1"
    assert await runs_use(db, settings) is None


async def test_the_digest_changes_with_every_save(db: Database):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    first = await waiting(settings)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small", api_key=NEW_KEY)
    assert await waiting(settings) != first


async def test_a_save_and_a_decision_at_the_same_moment_both_finish(
    db: Database, postgres: PostgresUrls
):
    settings = settings_for(db)
    await save(settings, style="openai", base_url=NCS, model="ncs-llm-small")
    seen = await waiting(settings)
    async with await psycopg.AsyncConnection.connect(postgres.owner) as holder:
        await holder.execute(
            "SELECT 1 FROM orchestration.model_setting WHERE slot = 'pending' FOR UPDATE"
        )
        saving = asyncio.create_task(
            save(settings, style="openai", base_url="https://elsewhere.example/v1", model="other")
        )
        await asyncio.sleep(0.3)
        deciding = asyncio.create_task(settings.decide(BOB, confirm=True, digest=seen))
        await asyncio.sleep(0.3)
        await holder.rollback()
    saved, decided = await asyncio.gather(saving, deciding)
    assert isinstance(saved, Saved) and saved.awaiting_confirmation
    assert isinstance(decided, PendingChanged)
    pending = (await settings.view()).pending
    assert pending is not None and pending.base_url == "https://elsewhere.example/v1"
