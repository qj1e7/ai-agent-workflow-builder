"""Where an approval's outcome card goes when the Teams address changes while the request is open.
The platform is rebuilt from its settings at each change, as a restart does, over one database.
Each channel is a Workflows webhook that answers over HTTP, and every post is kept under the
address it reached, which is the only truth the assertions use."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest

from platform_api.orchestration.agents import GitHubWorking
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.settings import settings_from_env
from platform_api.shared import ApprovalId, Digest
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
    """Every card a Teams channel took, by the address it was posted to: its first line."""

    posts: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        card = json.loads(request.content)["attachments"][0]["content"]
        first = "".join(run["text"] for run in card["body"][0]["inlines"])
        self.posts.append((str(request.url), first))
        return httpx.Response(202)

    def on(self, address: str) -> list[str]:
        return [first for at, first in self.posts if at == address]


@dataclass
class Switches:
    h: Harness
    channels: Channels
    client: httpx.AsyncClient

    def restart(self, teams_webhook: str | None, teams_channel: str | None = None) -> None:
        """The platform as the wiring builds it from these settings."""
        env = dict(LOCAL_ENV)
        if teams_webhook is not None:
            env["TEAMS_WEBHOOK_URL"] = teams_webhook
        if teams_channel is not None:
            env["TEAMS_CHANNEL"] = teams_channel
        settings = settings_from_env(env)
        jira, _ = jira_for(settings, self.h.db, self.client)
        channel, _ = approval_channel(settings, self.h.teams, self.client)
        _, channel = connections_for(
            settings,
            self.h.db,
            jira,
            channel,
            FakeRuntime(GitHubWorking(using_token=False)),
            FakeModels(SettingsState(True, ACTIVE, None, [])),
        )
        self.h.orchestrator = Orchestrator(
            self.h.db,
            self.h.log,
            self.h.engine,
            channel,
            self.h.agent,
            WriteGateway(self.h.db, [self.h.jira], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )


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
