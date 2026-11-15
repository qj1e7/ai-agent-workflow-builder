"""The platform's own keys in n8n and the credential sweep (ADR 0045, ENGINE-PLAN E16, E17), on a
fake n8n and fake systems: the platform makes a key only after the system shows it can only read
or post, and n8n's own test passes; every other key goes within a sweep, a member's above all;
a key lent with a workflow comes back on every take-back path; a key an ending account leaves is
kept unused; and the daily self-test plants a key the next sweep must remove."""

import asyncio
import copy
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import pytest

from platform_api.builder import Builder
from platform_api.builder.key_sweep import (
    KEY_ADDED,
    KEY_CHANGED,
    KEYS_NOT_BACK,
    TAKEN_OFF,
    UNCHECKED_DRAFT,
    KeySweep,
)
from platform_api.builder.n8n_holds import MOVE_GRACE, STRANDED, Holding
from platform_api.builder.service import UNCHECKED_TEST
from platform_api.orchestration import KEYS, N8nError, PlatformKeys
from platform_api.orchestration.n8n_credentials import (
    GONE_WITHIN,
    JIRA_READS,
    PLANTED_KIND,
    key_test_line,
)
from platform_api.settings import KeySystem, N8nKey
from tests.fake_n8n import FakeN8n
from tests.support import NOW
from tests.test_builder_lifecycle import Lab, ModelConnected
from tests.test_draft_turn_on import RUNS_PATH
from tests.test_n8n_access import PLATFORM_PROJECT, Staffed, held, lab, s
from tests.test_n8n_api import api_for
from tests.test_n8n_builder import WRITES
from tests.test_n8n_lifecycle import Workflows

PAT = "jiraSoftwareServerPatApi"
"""The credential type of a Data Center personal access token."""

pytestmark = pytest.mark.anyio

__all__ = ["lab", "s"]

SLACK, GITHUB, JIRA = KEYS["slack"].id, KEYS["github"].id, KEYS["jira"].id
GIVEN: dict[KeySystem, N8nKey] = {
    "slack": N8nKey("slackApi", {"accessToken": "slack-token-for-tests"}, "http://slack/api"),
    "github": N8nKey(
        "githubApi",
        {"server": "http://github", "accessToken": "github-token-for-tests"},
        "http://github",
    ),
    "jira": N8nKey(
        PAT,
        {"domain": "http://jira", "personalAccessToken": "jira-token-for-tests"},
        "http://jira",
    ),
}
"""What Key Vault would hold. None of it is a secret: the systems below are fakes."""


@dataclass
class Systems:
    """Slack, GitHub and Jira, as each answers what a key may do."""

    slack_scopes: str | None = "chat:write,channels:read"
    github_scopes: str | None = ""
    jira_may: set[str] = field(default_factory=lambda: {"BROWSE_PROJECTS", "USER_PICKER"})
    jira_lists: set[str] = field(
        default_factory=lambda: {
            "BROWSE_PROJECTS",
            "USER_PICKER",
            "CREATE_ISSUES",
            "EDIT_ISSUES",
            "ADMINISTER",
            "SOME_PERMISSION_JIRA_ADDS_LATER",
        }
    )
    slack_down: bool = False
    asked: list[str] = field(default_factory=list[str])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(f"{request.url.host} {request.url.path}")
        match request.url.host, request.url.path:
            case "slack", "/api/auth.test" if self.slack_down:
                return httpx.Response(503)
            case "slack", "/api/auth.test":
                headers = {} if self.slack_scopes is None else {"x-oauth-scopes": self.slack_scopes}
                return httpx.Response(200, json={"ok": True}, headers=headers)
            case "github", "/user":
                headers = (
                    {} if self.github_scopes is None else {"x-oauth-scopes": self.github_scopes}
                )
                return httpx.Response(200, json={"login": "reader"}, headers=headers)
            case "jira", "/rest/api/2/permissions":
                listed = {name: {"key": name} for name in self.jira_lists}
                return httpx.Response(200, json={"permissions": listed})
            case "jira", "/rest/api/2/mypermissions":
                asked = request.url.params["permissions"].split(",")
                held = {name: {"havePermission": name in self.jira_may} for name in asked}
                return httpx.Response(200, json={"permissions": held})
            case _:
                return httpx.Response(404)


@dataclass
class Keyed:
    s: Staffed
    keys: PlatformKeys
    sweep: KeySweep
    systems: Systems

    @property
    def n8n(self) -> FakeN8n:
        return self.s.n8n

    def given(self, keys: dict[KeySystem, N8nKey]) -> None:
        self.keys._keys = dict(keys)  # pyright: ignore[reportPrivateUsage]

    def in_n8n(self) -> dict[str, str]:
        """Each key n8n holds, by id, with the project it sits in."""
        return {key: c["projectId"] for key, c in self.n8n.credentials.items()}


async def settled(k: Keyed) -> None:
    """The keys made, and the daily self-test's planted key gone with the second sweep."""
    await k.sweep.sweep()
    await k.sweep.sweep()


@pytest.fixture
async def k(s: Staffed) -> AsyncIterator[Keyed]:
    systems = Systems()
    keys = PlatformKeys(s.lab.h.db, api_for(s.n8n), GIVEN, systems.client())
    workflows = Workflows(s.n8n, s.lab.h.db)
    sweep = KeySweep(s.lab.h.db, keys, workflows, s.staff)
    s.holding = Holding(s.lab.h.db, workflows, s.staff, keys=sweep)
    s.staff.keys = keys
    lab: Lab = s.lab
    lab.builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=workflows,
        writes=WRITES,
        accounts=s.staff,
        holding=s.holding,
        keys=keys,
    )
    lab.app.state.builder = lab.builder
    yield Keyed(s, keys, sweep, systems)
    await keys.close()


async def test_the_platform_makes_each_key_in_its_own_project_once_the_system_shows_its_reach(
    k: Keyed,
):
    await k.sweep.sweep()
    assert k.in_n8n() == {
        JIRA: PLATFORM_PROJECT,
        GITHUB: PLATFORM_PROJECT,
        SLACK: PLATFORM_PROJECT,
        **{key: PLATFORM_PROJECT for key in k.n8n.credentials if key.startswith("wab-test-")},
    }
    assert await k.keys.made() == {
        JIRA: PAT,
        GITHUB: "githubApi",
        SLACK: "slackApi",
    }
    assert sorted(k.systems.asked) == [
        "github /user",
        "jira /rest/api/2/mypermissions",
        "jira /rest/api/2/permissions",
        "slack /api/auth.test",
    ]
    slack = k.n8n.credentials[SLACK]
    assert (slack["type"], slack["data"], slack["name"]) == (
        "slackApi",
        {"accessToken": "slack-token-for-tests"},
        KEYS["slack"].name,
    )
    k.systems.asked.clear()
    await k.sweep.sweep()
    assert k.systems.asked == [], "a key already made is not asked about again"


@pytest.mark.parametrize(
    ("system", "change", "says"),
    [
        (
            "slack",
            lambda s: setattr(s, "slack_scopes", "chat:write,channels:manage"),
            "channels:manage",
        ),
        ("slack", lambda s: setattr(s, "slack_scopes", None), "Slack did not say"),
        ("github", lambda s: setattr(s, "github_scopes", "repo"), "more than read (repo)"),
        ("github", lambda s: setattr(s, "github_scopes", "public_repo, read:org"), "public_repo"),
        ("github", lambda s: setattr(s, "github_scopes", None), "fine-grained"),
        ("jira", lambda s: s.jira_may.add("CREATE_ISSUES"), "CREATE_ISSUES"),
        ("jira", lambda s: s.jira_may.add("ADMINISTER"), "ADMINISTER"),
        ("jira", lambda s: s.jira_may.add("SOME_PERMISSION_JIRA_ADDS_LATER"), "ADDS_LATER"),
        ("jira", lambda s: s.jira_lists.clear(), "did not list its permissions"),
        ("slack", lambda s: setattr(s, "slack_scopes", "chat:write,some:scope"), "some:scope"),
        ("github", lambda s: setattr(s, "github_scopes", "read:org, some:scope"), "some:scope"),
    ],
    ids=[
        "slack-manages-channels",
        "slack-says-nothing",
        "github-repo",
        "github-public-repo",
        "github-fine-grained",
        "jira-creates",
        "jira-administers",
        "jira-an-unknown-permission",
        "jira-lists-nothing",
        "slack-an-unknown-scope",
        "github-an-unknown-scope",
    ],
)
async def test_a_key_that_can_write_or_does_not_say_is_refused_at_creation(
    k: Keyed, system: KeySystem, change: Any, says: str
):
    change(k.systems)
    await k.sweep.sweep()
    assert KEYS[system].id not in k.n8n.credentials, "never made in n8n"
    assert KEYS[system].id not in await k.keys.made()
    [state] = [state for state in await k.keys.states() if state.system == system]
    assert not state.made and state.refused is not None and says in state.refused


async def test_a_jira_key_may_hold_only_what_reading_needs(k: Keyed):
    """Fail closed: Jira lists every permission it has, and the account must hold none of them but
    a short list of reads."""
    assert {
        "BROWSE_PROJECTS",
        "VIEW_READONLY_WORKFLOW",
        "VIEW_DEV_TOOLS",
        "VIEW_VOTERS_AND_WATCHERS",
        "USER_PICKER",
    } == JIRA_READS
    await k.sweep.sweep()
    assert JIRA in await k.keys.made(), "browsing and picking users are reads"


async def test_a_key_n8n_cannot_connect_with_is_removed_and_says_why(k: Keyed):
    k.n8n.credential_tests[SLACK] = ("Error", "invalid_auth")
    await k.sweep.sweep()
    assert SLACK not in k.n8n.credentials
    [state] = [state for state in await k.keys.states() if state.system == "slack"]
    assert state.refused == "n8n could not connect with the Slack key: invalid_auth"


async def test_a_refused_key_is_asked_about_again_an_hour_later(k: Keyed):
    k.systems.jira_may.add("CREATE_ISSUES")
    await k.sweep.sweep()
    k.systems.jira_may.clear()
    await k.sweep.sweep()
    assert JIRA not in k.n8n.credentials, "not within the hour"
    k.s.lab.h.advance(timedelta(hours=1))
    await k.sweep.sweep()
    assert JIRA in k.n8n.credentials, "the account lost its write rights, so the key is made"


async def test_the_sweep_deletes_every_key_the_platform_did_not_make_and_keeps_its_own(k: Keyed):
    await settled(k)
    carol = await k.s.member()
    space = k.n8n.personal_project(carol)
    mine = k.n8n.add_credential(space, "jiraSoftwareCloudApi")
    owners = k.n8n.add_credential(PLATFORM_PROJECT, "githubApi")
    swept = await k.sweep.sweep()
    assert {r.id for r in swept.removed} == {mine, owners}
    assert not any(r.changed for r in swept.removed)
    assert mine not in k.n8n.credentials and owners not in k.n8n.credentials
    assert {JIRA, GITHUB, SLACK} <= set(k.n8n.credentials)


async def test_a_platform_key_changed_in_n8n_is_deleted_and_made_again(k: Keyed):
    """Its holder could have pointed it at their own server to read the token. The sweep cannot
    see what changed, only that something did."""
    await settled(k)
    made = k.n8n.credentials[JIRA]["createdAt"]
    k.n8n.edit_credential(JIRA, domain="https://elsewhere.example")
    swept = await k.sweep.sweep()
    assert [(r.id, r.changed) for r in swept.removed] == [(JIRA, True)]
    remade = k.n8n.credentials[JIRA]
    assert remade["createdAt"] != made and remade["data"]["domain"] == "http://jira"
    assert JIRA in await k.keys.made()


async def test_a_key_made_again_with_the_platform_s_id_by_someone_else_is_not_trusted(k: Keyed):
    await settled(k)
    carol = await k.s.member()
    del k.n8n.credentials[SLACK]
    k.n8n.add_credential(k.n8n.personal_project(carol), "slackApi", SLACK)
    swept = await k.sweep.sweep()
    assert [(r.id, r.changed) for r in swept.removed] == [(SLACK, True)]
    assert k.n8n.credentials[SLACK]["projectId"] == PLATFORM_PROJECT
    assert k.n8n.credentials[SLACK]["data"] == {"accessToken": "slack-token-for-tests"}


async def test_a_new_secret_in_key_vault_makes_the_key_anew_never_changes_it(k: Keyed):
    """The record is only ever what n8n answered the platform's own create."""
    await settled(k)
    made = k.n8n.credentials[SLACK]["createdAt"]
    rotated = N8nKey("slackApi", {"accessToken": "rotated-for-tests"}, "http://slack/api")
    k.given({**GIVEN, "slack": rotated})
    k.n8n.calls.clear()
    swept = await k.sweep.sweep()
    assert swept.removed == ()
    assert f"DELETE /api/v1/credentials/{SLACK}" in k.n8n.calls
    assert not [c for c in k.n8n.calls if c.startswith(("PATCH", "PUT"))], "never changed or moved"
    assert k.n8n.credentials[SLACK]["data"] == {"accessToken": "rotated-for-tests"}
    assert k.n8n.credentials[SLACK]["createdAt"] != made
    assert SLACK in await k.keys.made()


async def test_a_key_no_longer_given_is_deleted(k: Keyed):
    await settled(k)
    k.given({system: key for system, key in GIVEN.items() if system != "github"})
    await k.sweep.sweep()
    assert GITHUB not in k.n8n.credentials and GITHUB not in await k.keys.made()


async def test_keys_an_ending_account_leaves_are_kept_unused_never_as_the_platform_s(k: Keyed):
    """n8n moves what the space holds to the platform's project as the account ends (E7), a
    member's own keys included. They stay there, and nothing may name them."""
    await settled(k)
    carol = await k.s.member()
    space = k.n8n.personal_project(carol)
    hers = k.n8n.add_credential(space, "jiraSoftwareCloudApi")
    assert (await k.s.give("carol", on=False)).status_code == 200
    await k.s.settle()
    assert k.n8n.credentials[hers]["projectId"] == PLATFORM_PROJECT, "moved, not deleted"
    swept = await k.sweep.sweep()
    assert hers not in {r.id for r in swept.removed}
    assert hers in k.n8n.credentials
    assert hers not in await k.keys.made(), "never the platform's"


async def test_a_quarantined_key_found_back_in_a_member_s_space_is_deleted(k: Keyed):
    await settled(k)
    carol = await k.s.member()
    space = k.n8n.personal_project(carol)
    hers = k.n8n.add_credential(space, "slackApi")
    await k.keys.quarantine(space, carol)
    swept = await k.sweep.sweep()
    assert hers in {r.id for r in swept.removed}, "kept only while it sits in the platform's"


async def test_the_daily_self_test_plants_a_key_the_next_sweep_removes(k: Keyed):
    await k.sweep.sweep()
    [planted] = [key for key in k.n8n.credentials if key.startswith("wab-test-")]
    assert k.n8n.credentials[planted]["type"] == PLANTED_KIND
    assert planted not in await k.keys.made()
    assert (await k.keys.tested())[0] is True, "planted, and the sweep is due"
    await k.sweep.sweep()
    assert planted not in k.n8n.credentials
    ok, says = await k.keys.tested()
    assert ok and "removed within a minute" in says
    await k.sweep.sweep()
    assert not [key for key in k.n8n.credentials if key.startswith("wab-test-")], "once a day"
    k.s.lab.h.advance(timedelta(days=1))
    await k.sweep.sweep()
    assert [key for key in k.n8n.credentials if key.startswith("wab-test-")], "the next day"


def test_the_self_test_line_says_when_a_planted_key_stayed():
    later = NOW + GONE_WITHIN + timedelta(seconds=1)
    assert key_test_line((NOW, None), later)[0] is False
    assert "still in n8n" in key_test_line((NOW, None), later)[1]
    assert key_test_line((NOW, NOW + timedelta(seconds=30)), later) == (
        True,
        f"the key planted at {NOW.isoformat()} was removed within a minute",
    )
    assert key_test_line((NOW, later), later)[0] is False
    assert key_test_line(None, NOW)[0] is False
    assert key_test_line((NOW, NOW), NOW + timedelta(days=2))[0] is False, "none planted lately"


async def test_a_platform_key_moved_out_of_its_project_is_deleted_and_made_again(k: Keyed):
    """A key never leaves the platform's project, so one found elsewhere was moved by someone."""
    await settled(k)
    carol = await k.s.member()
    k.n8n.credentials[GITHUB]["projectId"] = k.n8n.personal_project(carol)
    swept = await k.sweep.sweep()
    assert [(r.id, r.changed) for r in swept.removed] == [(GITHUB, True)]
    assert k.n8n.credentials[GITHUB]["projectId"] == PLATFORM_PROJECT


def with_slack(k: Keyed, workflow_id: str) -> None:
    """The workflow's draft and the version n8n runs both post in Slack with the platform's key."""
    workflow = k.n8n.workflows[workflow_id]
    block = {
        "id": "slack",
        "name": "Tell Slack",
        "type": "n8n-nodes-base.slack",
        "typeVersion": 2.7,
        "position": [900, 0],
        "parameters": {
            "select": "channel",
            "channelId": {"__rl": True, "value": "C1", "mode": "id"},
        },
        "credentials": {"slackApi": {"id": SLACK, "name": KEYS["slack"].name}},
    }
    workflow["nodes"].append(block)
    live = workflow["activeVersionId"]
    if live is not None:
        k.n8n.history[workflow_id][live]["nodes"].append(copy.deepcopy(block))


def slack_in(k: Keyed, workflow_id: str) -> dict[str, Any]:
    [block] = [n for n in k.n8n.workflows[workflow_id]["nodes"] if n["name"] == "Tell Slack"]
    return block


async def opened(k: Keyed) -> tuple[str, str, str]:
    """Carol holds a workflow that posts in Slack: the use case, the workflow and her space."""
    await settled(k)
    carol = await k.s.member()
    use_case_id, workflow_id = await held(k.s)
    with_slack(k, workflow_id)
    answer = await k.s.open("carol", use_case_id)
    assert answer.status_code == 200, answer.text
    return use_case_id, workflow_id, k.n8n.personal_project(carol)


def her_editor_swaps_the_key(k: Keyed, workflow_id: str, space: str) -> str:
    """In her space she cannot use the platform's key, so she adds her own and points the block at
    it, and puts a platform key on a block that is not for a system."""
    hers = k.n8n.add_credential(space, "slackApi")
    slack_in(k, workflow_id)["credentials"] = {"slackApi": {"id": hers, "name": "mine"}}
    first = k.n8n.workflows[workflow_id]["nodes"][0]
    first["credentials"] = {"githubApi": {"id": GITHUB, "name": "x"}}
    k.n8n.edit(workflow_id)
    return hers


def put_back(k: Keyed, workflow_id: str, hers: str) -> None:
    """Back home, the draft's blocks name the platform's key for their system again, every other
    key is off them, and her key is gone."""
    assert slack_in(k, workflow_id)["credentials"] == {
        "slackApi": {"id": SLACK, "name": KEYS["slack"].name}
    }
    assert "credentials" not in k.n8n.workflows[workflow_id]["nodes"][0], "not a block for a system"
    assert hers not in k.n8n.credentials


async def test_open_in_n8n_never_lends_a_platform_key(k: Keyed):
    """A key in a member's space could be pointed at their own server to read its secret. So the
    workflow opens without it, and they cannot run it with the key while they hold it."""
    _, workflow_id, space = await opened(k)
    assert k.n8n.home_of(workflow_id) == space
    assert {key: k.in_n8n()[key] for key in (SLACK, JIRA, GITHUB)} == {
        SLACK: PLATFORM_PROJECT,
        JIRA: PLATFORM_PROJECT,
        GITHUB: PLATFORM_PROJECT,
    }


async def test_open_in_n8n_sweeps_first(k: Keyed):
    """So no key a member added waits in their space for the workflow that comes to it."""
    await settled(k)
    carol = await k.s.member()
    hers = k.n8n.add_credential(k.n8n.personal_project(carol), "slackApi")
    use_case_id, _ = await held(k.s)
    assert (await k.s.open("carol", use_case_id)).status_code == 200
    assert hers not in k.n8n.credentials


async def test_the_holder_s_take_back_puts_the_keys_back(k: Keyed):
    use_case_id, workflow_id, space = await opened(k)
    hers = her_editor_swaps_the_key(k, workflow_id, space)
    assert (await k.s.take_back("carol", use_case_id)).status_code == 200
    put_back(k, workflow_id, hers)


async def test_a_block_set_to_do_what_is_off_gets_no_key_back(k: Keyed):
    """Her Slack block deletes with her key. Back home it gets no key, so a test run, which runs
    the draft in the platform's project, cannot delete with the platform's key."""
    use_case_id, workflow_id, space = await opened(k)
    hers = k.n8n.add_credential(space, "slackApi")
    block = slack_in(k, workflow_id)
    block["parameters"] = {**block["parameters"], "operation": "delete", "timestamp": "1"}
    block["credentials"] = {"slackApi": {"id": hers, "name": "mine"}}
    k.n8n.edit(workflow_id)
    assert (await k.s.take_back("carol", use_case_id)).status_code == 200
    assert "credentials" not in slack_in(k, workflow_id)
    assert hers not in k.n8n.credentials


async def test_another_operator_s_take_back_puts_the_keys_back(k: Keyed):
    use_case_id, workflow_id, space = await opened(k)
    dana = await k.s.operator("dana")
    await k.s.member(dana)
    hers = her_editor_swaps_the_key(k, workflow_id, space)
    assert (await k.s.take_back(dana, use_case_id)).status_code == 200
    put_back(k, workflow_id, hers)


async def test_the_platform_s_own_take_back_puts_the_keys_back_when_access_ends(k: Keyed):
    use_case_id, workflow_id, space = await opened(k)
    hers = her_editor_swaps_the_key(k, workflow_id, space)
    assert (await k.s.give("carol", on=False)).status_code == 200
    await k.s.settle()
    assert await k.s.held_by(use_case_id) is None
    put_back(k, workflow_id, hers)


async def test_a_delete_puts_the_keys_back_before_n8n_removes_it(k: Keyed):
    use_case_id, workflow_id, space = await opened(k)
    hers = her_editor_swaps_the_key(k, workflow_id, space)
    k.n8n.calls.clear()
    assert (await k.s.lab.move("alice", "delete", use_case_id)).status_code == 200
    assert hers not in k.n8n.credentials
    keys_back = k.n8n.calls.index(f"PUT /api/v1/workflows/{workflow_id}")
    archived = k.n8n.calls.index(f"POST /api/v1/workflows/{workflow_id}/archive")
    assert keys_back < archived


async def test_a_stranded_move_s_recovery_puts_the_keys_back(k: Keyed):
    await settled(k)
    carol = await k.s.member()
    use_case_id, workflow_id = await held(k.s)
    with_slack(k, workflow_id)
    k.n8n.transfer_keeps = lambda settings: {}
    k.n8n.after_put = k.n8n.edit
    k.n8n.transfer_answers = [204, 500]
    answer = await k.s.open("carol", use_case_id)
    assert (answer.status_code, answer.json()["detail"]) == (503, STRANDED)
    hers = her_editor_swaps_the_key(k, workflow_id, k.n8n.personal_project(carol))
    k.n8n.transfer_keeps = lambda settings: settings
    k.n8n.after_put = None
    k.s.lab.h.advance(MOVE_GRACE)
    await k.s.settle()
    assert k.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    put_back(k, workflow_id, hers)


async def test_a_key_added_in_the_holder_s_space_is_removed_and_marks_the_workflow(k: Keyed):
    use_case_id, _, space = await opened(k)
    hers = k.n8n.add_credential(space, "jiraSoftwareCloudApi")
    swept = await k.sweep.sweep()
    assert hers not in k.n8n.credentials
    assert swept.marked == (use_case_id,)
    view = (await k.s.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert (view["grade"], view["findings"][-1]) == ("needs_a_fix", KEY_ADDED)
    assert (await k.s.take_back("carol", use_case_id)).status_code == 200
    view = (await k.s.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert KEY_ADDED not in view["findings"], "the mark ends with the hold"


async def test_a_platform_key_found_in_the_holder_s_space_is_put_right_and_marks_it(k: Keyed):
    use_case_id, _, space = await opened(k)
    k.n8n.credentials[SLACK]["projectId"] = space
    swept = await k.sweep.sweep()
    assert [(r.id, r.changed) for r in swept.removed] == [(SLACK, True)]
    assert swept.marked == (use_case_id,)
    view = (await k.s.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert view["findings"][-1] == KEY_CHANGED
    assert k.n8n.credentials[SLACK]["projectId"] == PLATFORM_PROJECT


async def test_member_hand_run_with_own_key_is_swept(k: Keyed):
    """n8n's allow list is by type, so a holder can set the Slack block to delete in a draft and
    run it by hand with a key of their own. The checker never sees that run; the sweep removes
    the key within a minute, and with it the run's means (ADR 0045, acceptance note)."""
    _, workflow_id, space = await opened(k)
    hers = k.n8n.add_credential(space, "slackApi")
    slack = slack_in(k, workflow_id)
    slack["parameters"]["operation"] = "delete"
    slack["credentials"] = {"slackApi": {"id": hers, "name": "mine"}}
    await k.sweep.sweep()
    assert hers not in k.n8n.credentials


async def test_a_workflow_an_ended_account_left_running_with_its_maker_s_key_is_taken_off(
    k: Keyed,
):
    """In the platform's project n8n lets a workflow use every key there is, so a published one
    that names a key the platform did not make must not stay on."""
    await settled(k)
    carol = await k.s.member()
    space = k.n8n.personal_project(carol)
    hers = k.n8n.add_credential(space, "slackApi")
    _, laid_out = await held(k.s)
    document = copy.deepcopy(k.n8n.workflows[laid_out])
    for key in ("id", "versionId", "checksum", "activeVersionId", "active", "projectId", "shared"):
        document.pop(key, None)
    left = k.n8n.make_in(space, document, published_by=carol)
    with_slack(k, left)
    live = k.n8n.workflows[left]["activeVersionId"]
    [slack] = [n for n in k.n8n.history[left][live]["nodes"] if n["name"] == "Tell Slack"]
    slack["credentials"] = {"slackApi": {"id": hers, "name": "mine"}}
    await k.keys.quarantine(space, carol)
    assert (await k.s.give("carol", on=False)).status_code == 200
    await k.s.settle()
    assert k.n8n.home_of(left) == PLATFORM_PROJECT and k.n8n.workflows[left]["active"]
    swept = await k.sweep.sweep()
    assert swept.taken_off == (left,)
    assert not k.n8n.workflows[left]["active"]
    assert hers in k.n8n.credentials, "the key stays, unused"
    assert k.n8n.workflows[laid_out]["active"], "a use case's workflow is never taken off here"


async def n8n_user(k: Keyed, person: str = "carol") -> str:
    return str((await k.s.person(person))["n8n_user_id"])


def deletes_in_slack(workflow: dict[str, Any]) -> None:
    """n8n's Slack block set to delete, still naming the platform's key, after the trigger."""
    [block] = [n for n in workflow["nodes"] if n["name"] == "Tell Slack"]
    block["parameters"] = {**block["parameters"], "operation": "delete", "timestamp": "1"}


async def finding(k: Keyed, use_case_id: str) -> tuple[str, str]:
    view = (await k.s.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    return view["grade"], view["findings"][-1]


def last(calls: list[str], call: str) -> int:
    return len(calls) - 1 - calls[::-1].index(call)


async def test_a_take_back_takes_off_a_version_published_in_n8n_that_runs_a_block_unchecked(
    k: Keyed,
):
    """In the holder's space n8n won't run it with the platform's key. In the platform's project
    it would, every time its schedule fires. So it is taken off before it moves back."""
    use_case_id, workflow_id, _ = await opened(k)
    k.n8n.publish_as(workflow_id, await n8n_user(k), deletes_in_slack)
    assert (await k.s.take_back("carol", use_case_id)).status_code == 200
    assert k.n8n.home_of(workflow_id) == PLATFORM_PROJECT
    assert k.n8n.workflows[workflow_id]["activeVersionId"] is None
    off = k.n8n.calls.index(f"POST /api/v1/workflows/{workflow_id}/unpublish")
    assert off < last(k.n8n.calls, f"PUT /api/v1/workflows/{workflow_id}/transfer")
    assert await finding(k, use_case_id) == ("needs_a_fix", TAKEN_OFF)


async def test_the_platform_s_own_take_back_takes_it_off_too(k: Keyed):
    use_case_id, workflow_id, _ = await opened(k)
    k.n8n.publish_as(workflow_id, await n8n_user(k), deletes_in_slack)
    assert (await k.s.give("carol", on=False)).status_code == 200
    await k.s.settle()
    assert await k.s.held_by(use_case_id) is None
    assert k.n8n.workflows[workflow_id]["activeVersionId"] is None
    assert await finding(k, use_case_id) == ("needs_a_fix", TAKEN_OFF)


async def test_a_take_back_of_a_draft_n8n_would_run_unchecked_marks_it(k: Keyed):
    use_case_id, workflow_id, _ = await opened(k)
    deletes_in_slack(k.n8n.workflows[workflow_id])
    k.n8n.edit(workflow_id)
    live = k.n8n.workflows[workflow_id]["activeVersionId"]
    assert (await k.s.take_back("carol", use_case_id)).status_code == 200
    assert k.n8n.workflows[workflow_id]["activeVersionId"] == live, "the checked version runs on"
    assert await finding(k, use_case_id) == ("needs_a_fix", UNCHECKED_DRAFT)


async def test_a_take_back_whose_keys_n8n_did_not_take_stays_held_and_is_tried_again(
    k: Keyed, monkeypatch: pytest.MonkeyPatch
):
    """Never let go of a draft whose keys are not put right: it stays held, marked, and the
    platform tries again."""
    use_case_id, workflow_id, space = await opened(k)
    hers = her_editor_swaps_the_key(k, workflow_id, space)
    moves = k.s.holding._n8n  # pyright: ignore[reportPrivateUsage]
    took = moves.keep_keys

    async def refused(*_: object) -> None:
        raise N8nError("n8n is busy")

    monkeypatch.setattr(moves, "keep_keys", refused)
    answer = await k.s.take_back("carol", use_case_id)
    assert (answer.status_code, answer.json()["detail"]) == (503, STRANDED)
    assert await k.s.held_by(use_case_id) == "carol"
    assert await finding(k, use_case_id) == ("needs_a_fix", KEYS_NOT_BACK)
    monkeypatch.setattr(moves, "keep_keys", took)
    await k.s.holding.release()
    assert await k.s.held_by(use_case_id) is None
    put_back(k, workflow_id, hers)


async def test_the_sweep_takes_off_every_live_version_at_home_n8n_would_run_unchecked(
    k: Keyed,
):
    """Named by a use case or not, however it got there. The use case is marked, never
    deleted."""
    await settled(k)
    carol = await k.s.member()
    use_case_id, workflow_id = await held(k.s)
    clean, _ = await held(k.s)
    with_slack(k, workflow_id)
    k.n8n.publish_as(workflow_id, carol, deletes_in_slack)
    swept = await k.sweep.sweep()
    assert swept.taken_off == (workflow_id,)
    assert k.n8n.workflows[workflow_id]["activeVersionId"] is None
    assert workflow_id in k.n8n.workflows, "never deleted"
    assert await finding(k, use_case_id) == ("needs_a_fix", TAKEN_OFF)
    view = (await k.s.call("alice", "GET", f"/api/v1/use-cases/{clean}")).json()
    assert (view["grade"], view["findings"]) == ("safe", [])


async def runs(k: Keyed, use_case_id: str) -> httpx.Response:
    path = f"/api/v1/use-cases/{use_case_id}/runs"
    return await k.s.lab.call("alice", "POST", path, {"test": True}, template=RUNS_PATH)


async def test_no_test_run_starts_while_someone_holds_the_workflow(k: Keyed):
    """A test run runs the draft as n8n holds it, where it holds it."""
    use_case_id, _, _ = await opened(k)
    answer = await runs(k, use_case_id)
    assert answer.status_code == 409
    assert answer.json()["detail"].startswith("Carol has it open in n8n")


async def test_no_test_run_starts_on_a_draft_n8n_would_run_unchecked(k: Keyed):
    """In the platform's project n8n lets the draft use every key there is."""
    await settled(k)
    use_case_id, workflow_id = await held(k.s)
    with_slack(k, workflow_id)
    deletes_in_slack(k.n8n.workflows[workflow_id])
    answer = await runs(k, use_case_id)
    assert answer.status_code == 409
    words = '"Tell Slack" does something that is off: message delete.'
    assert answer.json()["detail"] == UNCHECKED_TEST.format(found=words)
    del slack_in(k, workflow_id)["parameters"]["operation"]
    assert (await runs(k, use_case_id)).status_code == 201


async def test_the_platform_asks_again_each_day_and_takes_out_a_key_that_can_now_do_more(
    k: Keyed,
):
    """Every workflow that names it stops: the same sweep takes the live ones off."""
    await settled(k)
    use_case_id, workflow_id = await held(k.s)
    with_slack(k, workflow_id)
    k.s.lab.h.advance(timedelta(days=1))
    k.systems.slack_scopes = "chat:write,channels:read,channels:history"
    swept = await k.sweep.sweep()
    assert SLACK not in k.n8n.credentials and SLACK not in await k.keys.made()
    assert swept.taken_off == (workflow_id,)
    assert await finding(k, use_case_id) == ("needs_a_fix", TAKEN_OFF)


async def test_a_key_the_system_can_t_be_asked_about_today_stays(k: Keyed):
    await settled(k)
    k.s.lab.h.advance(timedelta(days=1))
    k.systems.slack_scopes = None
    k.systems.slack_down = True
    await k.sweep.sweep()
    assert SLACK in k.n8n.credentials and SLACK in await k.keys.made()
    k.systems.slack_down = False
    k.systems.slack_scopes = "chat:write"
    asked = len(k.systems.asked)
    await k.sweep.sweep()
    assert len(k.systems.asked) > asked, "asked again at the next sweep"


async def test_one_sweep_at_a_time_so_none_deletes_a_key_another_is_making(
    k: Keyed, monkeypatch: pytest.MonkeyPatch
):
    """n8n holds a new key a moment before the platform records it. A sweep that looked then
    would take it for one the platform did not make, so the second waits for the first."""
    api = k.keys._api  # pyright: ignore[reportPrivateUsage]
    assert api is not None
    create = api.create_credential
    others: list[asyncio.Task[object]] = []

    async def slow(*args: Any) -> Any:
        made = await create(*args)
        if not others:
            others.append(asyncio.create_task(k.keys.sweep()))
            await asyncio.sleep(0.1)
        return made

    monkeypatch.setattr(api, "create_credential", slow)
    k.n8n.calls.clear()
    await k.keys.sweep()
    await asyncio.gather(*others)
    assert not [c for c in k.n8n.calls if c.startswith("DELETE /api/v1/credentials/")]
    assert await k.keys.sweep() == [], "each key is still as the platform made it"
