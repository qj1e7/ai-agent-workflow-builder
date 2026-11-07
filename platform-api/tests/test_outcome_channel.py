import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest

from platform_api.monitoring import ActivityEvent
from platform_api.orchestration.agents import GitHubWorking
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.store import SHOW_OUTCOME, Store
from platform_api.orchestration.teams import TeamsStub
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.settings import settings_from_env
from platform_api.shared import ApprovalId, Digest, RunId
from platform_api.wiring import approval_channel, connections_for, jira_for
from tests.conftest import PostgresUrls
from tests.support import BOB, LOCAL_ENV, SPEC
from tests.test_connections import FakeModels, FakeRuntime
from tests.test_orchestrator import (
    PUBLIC_BASE_URL,
    Harness,
    mint,
    open_harness,
    work_leg_to_approval,
)
from tests.test_settings_http import ACTIVE

pytestmark = pytest.mark.anyio

HOOK_A = "https://teams.example/workflows/a/run?sig=signature-of-channel-a"
HOOK_B = "https://teams.example/workflows/b/run?sig=signature-of-channel-b"
ASKED = (
    f"{SPEC.use_case_name} wants to make 1 change. Nothing is written until an Approver says yes."
)
APPROVED = f"{SPEC.use_case_name}: approved by bob."


@dataclass
class Channels:
    first_lines: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        card = json.loads(request.content)["attachments"][0]["content"]
        first = "".join(run["text"] for run in card["body"][0]["inlines"])
        self.first_lines.setdefault(str(request.url), []).append(first)
        return httpx.Response(202)

    def on(self, address: str) -> list[str]:
        return self.first_lines.get(address, [])


@dataclass
class Switches:
    h: Harness
    channels: Channels
    client: httpx.AsyncClient

    def platform(self, teams_webhook: str | None, teams_channel: str | None = None) -> Orchestrator:
        env = dict(LOCAL_ENV)
        if teams_webhook is not None:
            env["TEAMS_WEBHOOK_URL"] = teams_webhook
        if teams_channel is not None:
            env["TEAMS_CHANNEL"] = teams_channel
        settings = settings_from_env(env)
        jira, _ = jira_for(settings, self.h.db, self.client)
        practice = TeamsStub(self.h.db, settings.teams_channel)
        channel, _ = approval_channel(settings, practice, self.client)
        _, channel = connections_for(
            settings,
            self.h.db,
            jira,
            channel,
            FakeRuntime(GitHubWorking(using_token=False)),
            FakeModels(SettingsState(True, ACTIVE, None, [])),
        )
        return Orchestrator(
            self.h.db,
            self.h.log,
            self.h.engine,
            channel,
            self.h.agent,
            WriteGateway(self.h.db, [self.h.jira], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )

    def restart(self, teams_webhook: str | None, teams_channel: str | None = None) -> None:
        self.h.orchestrator = self.platform(teams_webhook, teams_channel)

    async def notes(self, run_id: RunId) -> list[ActivityEvent]:
        events = await self.h.log.read_after(run_id, 0)
        return [e for e in events if e.kind == "approval_outcome_not_posted"]


@pytest.fixture
async def s(postgres: PostgresUrls) -> AsyncIterator[Switches]:
    channels = Channels()
    async with (
        open_harness(postgres) as h,
        httpx.AsyncClient(transport=httpx.MockTransport(channels.handle)) as client,
    ):
        yield Switches(h, channels, client)


async def digest_of(h: Harness, approval_id: ApprovalId) -> Digest:
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    return detail.request.digest


async def approve(h: Harness, approval_id: ApprovalId) -> None:
    await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(h, approval_id)
    )
    await h.orchestrator.tick()


async def test_after_the_address_changes_an_earlier_outcome_never_reaches_the_new_channel(
    s: Switches,
):
    s.restart(HOOK_A)
    _, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(HOOK_B)
    await approve(s.h, approval_id)
    assert s.channels.on(HOOK_A) == [ASKED]
    assert s.channels.on(HOOK_B) == []


NOT_POSTED = (
    "The outcome card could not go to the Teams channel that had the approval card, because "
    "the channel set up now does not match it. It was not posted to any other channel."
)


async def test_the_run_says_the_outcome_card_could_not_go_to_the_channel_that_had_the_request(
    s: Switches,
):
    s.restart(HOOK_A)
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(HOOK_B)
    await approve(s.h, approval_id)
    [note] = await s.notes(run_id)
    assert (note.actor.kind, note.summary) == ("platform", NOT_POSTED)
    assert note.model_dump(mode="json")["data"] == {
        "approval_id": approval_id,
        "channel": "CODESparks Ops",
    }
    async with s.h.db.transaction("orchestration") as uow:
        kept = await (
            await uow.conn.execute("SELECT * FROM orchestration.approval_messages")
        ).fetchall()
        outcome = await (
            await uow.conn.execute(
                "SELECT status, attempt FROM orchestration.outbox WHERE kind = %s",
                (SHOW_OUTCOME,),
            )
        ).fetchone()
    for secret in ("signature-of-channel", "teams.example", "workflows/"):
        assert secret not in repr(kept)
    assert outcome is not None and (outcome["status"], outcome["attempt"]) == ("sent", 0)


async def test_the_outcome_goes_to_the_channel_that_had_the_request_once_it_is_set_up_again(
    s: Switches,
):
    s.restart(HOOK_A)
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(HOOK_B)
    await s.h.orchestrator.tick()
    s.restart(HOOK_A)
    await approve(s.h, approval_id)
    assert s.channels.on(HOOK_A) == [ASKED, APPROVED]
    assert s.channels.on(HOOK_B) == []
    assert await s.notes(run_id) == []


async def test_with_teams_turned_off_the_outcome_is_posted_nowhere(s: Switches):
    s.restart(HOOK_A)
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(None)
    await approve(s.h, approval_id)
    assert s.channels.on(HOOK_A) == [ASKED]
    assert await s.h.teams.messages() == []
    assert [note.summary for note in await s.notes(run_id)] == [NOT_POSTED]


async def test_the_practice_copy_still_shows_the_outcome_after_its_channel_is_renamed(
    s: Switches,
):
    s.restart(None)
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(None, teams_channel="Support desk")
    await approve(s.h, approval_id)
    [message] = await s.h.teams.messages()
    assert message.card is not None
    assert message.card.as_json()["body"][0]["inlines"][0]["text"] == "Approved by Bob"
    assert s.channels.first_lines == {}
    assert await s.notes(run_id) == []


async def test_a_repeat_of_the_outcome_post_sends_nothing_twice(s: Switches):
    s.restart(HOOK_A)
    _, _, approval_id = await work_leg_to_approval(s.h)
    await s.h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, await digest_of(s.h, approval_id)
    )
    other = s.platform(HOOK_A)
    await asyncio.gather(s.h.orchestrator.tick(), other.tick())
    s.h.advance(timedelta(minutes=2))
    await asyncio.gather(s.h.orchestrator.tick(), other.tick())
    assert s.channels.on(HOOK_A) == [ASKED, APPROVED]


async def test_a_repeat_of_an_outcome_that_cannot_be_posted_says_so_once(s: Switches):
    s.restart(HOOK_A)
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    s.restart(HOOK_B)
    await approve(s.h, approval_id)
    async with s.h.db.transaction("orchestration") as uow:
        [payload] = [
            row["payload"]
            for row in await (
                await uow.conn.execute(
                    "SELECT payload FROM orchestration.outbox WHERE kind = %s", (SHOW_OUTCOME,)
                )
            ).fetchall()
        ]
        await Store().enqueue(uow, run_id, SHOW_OUTCOME, payload, uow.now)
    await s.h.orchestrator.tick()
    await s.h.orchestrator.tick()
    assert s.channels.on(HOOK_B) == []
    assert len(await s.notes(run_id)) == 1
