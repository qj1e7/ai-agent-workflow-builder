from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from platform_api.db import Database
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    GitHubCheckResult,
    GitHubProblem,
    GitHubWorking,
)
from platform_api.orchestration.connections import (
    RECHECK_AFTER,
    TEAMS_NOT_CHECKED,
    Checked,
    ConnectionId,
    Connections,
    Entry,
    Observed,
    ReadFresh,
    Reading,
    Shown,
    WatchedChannel,
    due,
    github_probe,
    jira_probe,
    model_probe,
    practice_teams,
    settle,
)
from platform_api.orchestration.dispatch import (
    ApprovalNotice,
    ApprovalOutcome,
    DispatchFailure,
    Identity,
    MessageRef,
    identity_of,
)
from platform_api.orchestration.jira_rest import JiraAuth, JiraReach, JiraRestAdapter
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.teams import TeamsStub
from platform_api.settings import settings_from_env
from platform_api.shared import ApprovalId, RunId
from platform_api.wiring import KEY_HINT_MIN_LENGTH, approval_channel, connections_for, key_hint
from tests.practice import BASE, PracticeKit, no_wait
from tests.support import LOCAL_ENV
from tests.test_settings_http import ACTIVE

pytestmark = pytest.mark.anyio

T0 = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
RUN = RunId("run_t1")
WORKING = Reading("working", key_ends_in="x7")
DOWN = Reading("not_answering", "Jira is not answering.")
REFUSED = Reading("needs_attention", "Jira does not accept the key.")


def shown(state: str = "working", **changes: object) -> Shown:
    base = Shown(state, None, T0, T0 if state == "working" else None, None, None)  # type: ignore[arg-type]
    return Shown(**{**base.__dict__, **changes})


def test_the_first_reading_is_shown_as_it_is():
    result = settle(None, DOWN, T0, at_once=False)
    assert (result.state, result.problem, result.last_ok_at) == (
        "not_answering",
        "Jira is not answering.",
        None,
    )


def test_one_different_reading_from_a_tick_waits_for_a_second_to_agree():
    later = T0 + RECHECK_AFTER
    first = settle(shown(), DOWN, later, at_once=False)
    assert first.state == "working"
    assert first.unconfirmed_state == "not_answering"
    assert first.checked_at == T0
    assert first.last_ok_at == T0
    second = settle(first, DOWN, later + timedelta(minutes=5), at_once=False)
    assert second.state == "not_answering"
    assert second.unconfirmed_state is None
    assert second.problem == "Jira is not answering."
    assert second.last_ok_at == T0


def test_a_reading_that_goes_back_to_the_shown_state_drops_the_doubt():
    doubtful = settle(shown(), DOWN, T0 + RECHECK_AFTER, at_once=False)
    back = settle(doubtful, WORKING, T0 + RECHECK_AFTER * 2, at_once=False)
    assert back.state == "working" and back.unconfirmed_state is None


def test_two_different_readings_in_a_row_change_nothing():
    first = settle(shown(), DOWN, T0 + RECHECK_AFTER, at_once=False)
    second = settle(first, REFUSED, T0 + RECHECK_AFTER * 2, at_once=False)
    assert second.state == "working"
    assert second.unconfirmed_state == "needs_attention"


def test_check_now_shows_what_it_found_at_once():
    result = settle(shown(), DOWN, T0 + timedelta(minutes=1), at_once=True)
    assert result.state == "not_answering" and result.unconfirmed_state is None
    assert result.last_ok_at == T0


def test_working_again_sets_the_last_time_it_worked():
    later = T0 + timedelta(hours=3)
    down = shown("not_answering", problem="x", last_ok_at=T0)
    healed = settle(down, WORKING, later, at_once=True)
    assert healed.last_ok_at == later
    assert healed.last_ok_at is not None and healed.last_ok_at > T0


def test_a_tick_checks_what_was_never_checked_what_does_not_work_and_the_rest_hourly():
    assert due(None, T0)
    assert due(shown(unconfirmed_state="not_answering"), T0 + timedelta(minutes=5))
    assert due(shown("not_answering"), T0 + timedelta(minutes=5))
    assert due(shown("needs_attention"), T0 + timedelta(minutes=5))
    assert not due(shown(), T0 + RECHECK_AFTER - timedelta(seconds=1))
    assert due(shown(), T0 + RECHECK_AFTER)


@dataclass
class Scripted:
    """A probe that answers what it was told, and counts its calls."""

    reading: Reading = WORKING
    calls: int = 0
    error: Exception | None = None

    async def __call__(self) -> Reading:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reading


@dataclass
class Rig:
    db: Database
    probes: dict[ConnectionId, Scripted] = field(default_factory=dict[ConnectionId, Scripted])
    connections: Connections = field(init=False)

    def __post_init__(self) -> None:
        names: dict[ConnectionId, str] = {
            "jira": "Jira",
            "github": "GitHub",
            "teams": "Teams",
            "model": "AI model",
        }
        self.probes = {id: Scripted() for id in names}
        entries = [
            Entry(
                id,
                name,
                Identity(id),
                ReadFresh(self.probes[id]) if id == "model" else Checked(self.probes[id]),
            )
            for id, name in names.items()
        ]
        self.connections = Connections(self.db, entries)


@pytest.fixture
def rig(db: Database) -> Rig:
    return Rig(db)


async def test_the_first_view_checks_each_connection_once_and_keeps_the_result(rig: Rig):
    first = await rig.connections.view()
    again = await rig.connections.view()
    assert [c.id for c in first] == ["jira", "github", "teams", "model"]
    assert all(c.state == "working" for c in first)
    assert [p.calls for p in rig.probes.values()] == [1, 1, 1, 2]
    assert again[:3] == first[:3]


async def test_check_now_runs_one_check_and_shows_a_problem_at_once(rig: Rig):
    await rig.connections.view()
    rig.probes["jira"].reading = DOWN
    checked = await rig.connections.check_now("jira")
    assert checked is not None
    assert (checked.state, checked.problem) == ("not_answering", "Jira is not answering.")
    assert checked.fix == "Nothing to change yet. Check again in a few minutes."
    assert rig.probes["github"].calls == 1
    assert await rig.connections.check_now("nothing") is None


async def test_a_check_that_raises_is_a_connection_that_is_not_answering_without_the_error(
    rig: Rig,
):
    rig.probes["jira"].error = RuntimeError("secret-token-value was refused")
    checked = await rig.connections.check_now("jira")
    assert checked is not None
    assert checked.state == "not_answering"
    assert checked.problem == "The check of Jira did not finish."
    assert "secret-token-value" not in repr(await rig.connections.view())


async def test_a_tick_checks_only_what_is_due_and_needs_two_readings_to_raise_a_problem(
    rig: Rig, db: Database
):
    await rig.connections.view()
    await rig.connections.check_due()
    assert [p.calls for p in rig.probes.values()] == [1, 1, 1, 1]

    rig.probes["jira"].reading = DOWN
    await _age(db, "jira", RECHECK_AFTER)
    await rig.connections.check_due()
    jira = next(c for c in await rig.connections.view() if c.id == "jira")
    assert jira.state == "working"

    await rig.connections.check_due()
    jira = next(c for c in await rig.connections.view() if c.id == "jira")
    assert jira.state == "not_answering"
    assert [p.calls for p in rig.probes.values()] == [3, 1, 1, 3]


async def test_a_tick_checks_a_failing_connection_every_time_and_a_working_one_hourly(rig: Rig):
    rig.probes["jira"].reading = DOWN
    await rig.connections.check_now("jira")
    await rig.connections.check_due()
    await rig.connections.check_due()
    assert [rig.probes[id].calls for id in ("jira", "github", "teams")] == [3, 1, 1]

    rig.probes["jira"].reading = WORKING
    await rig.connections.check_due()
    jira = next(c for c in await rig.connections.view() if c.id == "jira")
    assert jira.state == "not_answering"
    await rig.connections.check_due()
    jira = next(c for c in await rig.connections.view() if c.id == "jira")
    assert jira.state == "working"
    await rig.connections.check_due()
    assert [rig.probes[id].calls for id in ("jira", "github", "teams")] == [5, 1, 1]


async def _age(db: Database, connection: str, by: timedelta) -> None:
    async with db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.connection_checks SET checked_at = checked_at - %s "
            "WHERE connection = %s",
            (by, connection),
        )


async def test_what_needs_attention_is_read_from_what_was_kept_and_checks_nothing(rig: Rig):
    assert await rig.connections.needing_attention() == []
    assert [rig.probes[id].calls for id in ("jira", "github", "teams")] == [0, 0, 0]

    rig.probes["jira"].reading = DOWN
    rig.probes["github"].reading = Reading(
        "working", expires_at=datetime.now(UTC) + timedelta(days=9)
    )
    rig.probes["teams"].reading = Reading(
        "working", expires_at=datetime.now(UTC) + timedelta(days=40)
    )
    await rig.connections.view()
    found = await rig.connections.needing_attention()
    assert [(c.id, c.state) for c in found] == [("jira", "not_answering"), ("github", "working")]
    assert found[1].problem == "The key runs out soon."
    assert found[1].fix == "Ask whoever set up GitHub for a new key before this one runs out."


async def test_no_ai_model_needs_attention_as_its_settings_say_now_with_no_check_first(rig: Rig):
    rig.probes["model"].reading = Reading("not_set_up", "No AI model is turned on.")
    (model,) = await rig.connections.needing_attention()
    assert (model.id, model.state, model.fix) == (
        "model",
        "not_set_up",
        "Add an AI model under Settings, AI model.",
    )
    assert [rig.probes[id].calls for id in ("jira", "github", "teams")] == [0, 0, 0]

    rig.probes["model"].reading = WORKING
    assert await rig.connections.needing_attention() == []


async def test_the_stored_result_holds_no_secret_and_no_error_text(rig: Rig, db: Database):
    rig.probes["jira"].error = RuntimeError("Bearer ghp_super_secret")
    await rig.connections.check_now("jira")
    async with db.transaction("orchestration") as uow:
        rows = await (
            await uow.conn.execute("SELECT * FROM orchestration.connection_checks")
        ).fetchall()
    assert "ghp_super_secret" not in repr(rows)


@dataclass
class FakeJira:
    answer: JiraReach

    async def check(self) -> JiraReach:
        return self.answer


async def test_jira_answers_map_to_states_in_plain_words():
    probe = lambda answer: jira_probe(FakeJira(answer), "Jira", "x7")  # noqa: E731
    assert await probe("working")() == Reading("working", key_ends_in="x7")
    refused = await probe("token_refused")()
    assert (refused.state, refused.problem) == ("needs_attention", "Jira does not accept the key.")
    down = await probe("not_answering")()
    assert (down.state, down.problem) == ("not_answering", "Jira is not answering.")


@dataclass
class FakeRuntime:
    answer: GitHubCheckResult | AgentUnavailable | AgentRejected

    async def check_github(self) -> GitHubCheckResult | AgentUnavailable | AgentRejected:
        return self.answer


async def test_the_runtimes_github_answer_becomes_a_state_without_its_own_words():
    ends = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    working = await github_probe(FakeRuntime(GitHubWorking(using_token=True, expires_at=ends)))()
    assert working == Reading("working", expires_at=ends)

    refused = await github_probe(
        FakeRuntime(GitHubProblem(reason="token_refused", message="ghp_leaked_by_mistake"))
    )()
    assert refused.state == "needs_attention"
    assert refused.problem == "GitHub does not accept the key."

    unreachable = await github_probe(
        FakeRuntime(GitHubProblem(reason="unreachable", message="anything"))
    )()
    assert unreachable.state == "not_answering"

    silent = await github_probe(FakeRuntime(AgentUnavailable("the runtime is down")))()
    assert silent.state == "not_answering"
    assert silent.problem == "The agent runtime did not answer, so GitHub was not checked."
    rejected = await github_probe(FakeRuntime(AgentRejected("401")))()
    assert rejected.state == "not_answering"


@dataclass
class FakeModels:
    state: SettingsState

    async def view(self) -> SettingsState:
        return self.state


async def test_the_model_is_read_from_its_settings():
    working = await model_probe(FakeModels(SettingsState(True, ACTIVE, None, [])))()
    assert working == Reading("working", key_ends_in="x7")
    none = await model_probe(FakeModels(SettingsState(True, None, None, [])))()
    assert (none.state, none.problem) == ("not_set_up", "No AI model is turned on.")
    off = await model_probe(FakeModels(SettingsState(False, None, None, [])))()
    assert off.state == "not_set_up"


async def test_the_practice_teams_always_takes_a_message():
    assert await practice_teams() == Reading("working")


REAL_TEAMS = identity_of("teams_workflows", "https://example.invalid/hook?sig=secret-value")
NOTICE = ApprovalNotice(
    run_id=RunId("run_t1"),
    approval_id=ApprovalId("apr_t1"),
    use_case_name="Watch LangGraph",
    actions=("create a Jira ticket",),
    link="/approvals/apr_t1",
    open_url="http://localhost:8080/approvals/apr_t1",
)
OUTCOME = ApprovalOutcome("approved", ("Bob",), "Watch LangGraph", NOTICE.open_url)


@dataclass
class Channel:
    """A Teams channel that takes a post, or refuses the next `refusing` of them."""

    refusing: int = 0
    posts: int = 0
    name: str = "Ops"
    identity: Identity = REAL_TEAMS

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        await self._post()
        return MessageRef(self.name, notice.approval_id, self.identity)

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        await self._post()

    async def _post(self) -> None:
        self.posts += 1
        if self.refusing:
            self.refusing -= 1
            raise DispatchFailure("Teams answered 500 at https://example.invalid/hook?sig=x")


def real_teams(db: Database, channel: Channel) -> tuple[Connections, WatchedChannel]:
    connections = Connections(
        db, [Entry("teams", "Teams", REAL_TEAMS, Observed(TEAMS_NOT_CHECKED))]
    )
    return connections, WatchedChannel(channel, connections)


async def test_a_real_teams_channel_with_no_post_yet_is_not_checked_and_never_tried(db: Database):
    channel = Channel()
    connections, _ = real_teams(db, channel)
    (teams,) = await connections.view()
    assert (teams.state, teams.checked_at, teams.last_ok_at, teams.fix) == (
        "not_checked",
        None,
        None,
        None,
    )
    assert teams.problem == TEAMS_NOT_CHECKED
    assert await connections.check_now("teams") == teams
    await connections.check_due()
    assert await connections.view() == [teams]
    assert await connections.needing_attention() == []
    assert channel.posts == 0


async def test_the_first_post_is_the_result_at_once(db: Database):
    connections, watched = real_teams(db, Channel())
    assert await watched.announce(NOTICE) == MessageRef("Ops", "apr_t1", REAL_TEAMS)
    (teams,) = await connections.view()
    assert (teams.state, teams.problem) == ("working", None)
    assert teams.checked_at is not None and teams.last_ok_at == teams.checked_at


async def test_a_first_post_teams_refuses_shows_not_answering_without_its_error(db: Database):
    connections, watched = real_teams(db, Channel(refusing=1))
    with pytest.raises(DispatchFailure):
        await watched.announce(NOTICE)
    (teams,) = await connections.view()
    assert (teams.state, teams.problem, teams.last_ok_at) == (
        "not_answering",
        "Teams did not take the last message.",
        None,
    )
    assert teams.fix == "Ask whoever set up the Teams address to check that it still works."
    assert "secret" not in repr(teams) and "500" not in repr(teams)
    assert [c.id for c in await connections.needing_attention()] == ["teams"]


async def test_one_refused_post_after_working_waits_for_a_second_to_agree(db: Database):
    channel = Channel()
    connections, watched = real_teams(db, channel)
    await watched.announce(NOTICE)
    channel.refusing = 2
    with pytest.raises(DispatchFailure):
        await watched.update(MessageRef("Ops", "apr_t1", REAL_TEAMS), OUTCOME)
    (teams,) = await connections.view()
    assert teams.state == "working"
    with pytest.raises(DispatchFailure):
        await watched.announce(NOTICE)
    (teams,) = await connections.view()
    assert teams.state == "not_answering"
    assert teams.last_ok_at is not None and teams.last_ok_at < teams.checked_at  # type: ignore[operator]
    await watched.announce(NOTICE)
    await watched.announce(NOTICE)
    (teams,) = await connections.view()
    assert teams.state == "working"


async def test_a_result_that_cannot_be_kept_never_fails_the_post(db: Database):
    channel = Channel()
    connections, watched = real_teams(db, channel)

    async def broken(*args: object) -> None:
        raise RuntimeError("the database went away")

    connections.observe = broken  # type: ignore[method-assign]
    assert await watched.announce(NOTICE) == MessageRef("Ops", "apr_t1", REAL_TEAMS)
    channel.refusing = 1
    with pytest.raises(DispatchFailure):
        await watched.announce(NOTICE)
    assert channel.posts == 2


async def test_the_wiring_watches_only_a_real_teams_channel(db: Database):
    practice = settings_from_env(LOCAL_ENV)
    stub = TeamsStub(db, "Ops")
    channel, _ = approval_channel(practice, stub)
    _, used = connections_for(
        practice,
        db,
        FakeJira("working"),
        channel,
        FakeRuntime(GitHubWorking(using_token=False)),
        FakeModels(SettingsState(True, ACTIVE, None, [])),
    )
    assert used is stub

    real = settings_from_env({**LOCAL_ENV, "TEAMS_WEBHOOK_URL": "https://example.invalid/hook"})
    channel, webhook = approval_channel(real, stub)
    connections, used = connections_for(
        real,
        db,
        FakeJira("working"),
        channel,
        FakeRuntime(GitHubWorking(using_token=False)),
        FakeModels(SettingsState(True, ACTIVE, None, [])),
    )
    assert isinstance(used, WatchedChannel) and webhook is not None
    await webhook.close()
    (teams,) = [c for c in await connections.view() if c.id == "teams"]
    assert (teams.state, teams.practice) == ("not_checked", False)


async def test_the_model_row_is_read_fresh_on_every_view_and_never_kept(db: Database):
    state = SettingsState(True, ACTIVE, None, [])
    models = FakeModels(state)
    connections = Connections(
        db, [Entry("model", "AI model", Identity("model"), ReadFresh(model_probe(models)))]
    )
    (working,) = await connections.view()
    assert (working.state, working.key_ends_in) == ("working", "x7")
    assert (working.checked_at, working.last_ok_at) == (None, None)

    models.state = SettingsState(True, None, None, [])
    (gone,) = await connections.view()
    assert (gone.state, gone.key_ends_in, gone.last_ok_at) == ("not_set_up", None, None)

    models.state = SettingsState(True, ACTIVE, None, [])
    (back,) = await connections.view()
    assert (back.state, back.key_ends_in) == ("working", "x7")
    checked = await connections.check_now("model")
    assert checked is not None and checked.state == "working"

    await connections.check_due()
    assert await connections.needing_attention() == []
    async with db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute("SELECT count(*) AS n FROM orchestration.connection_checks")
        ).fetchone()
    assert row is not None and row["n"] == 0


def test_a_jira_token_shows_its_last_two_characters_only_when_it_is_long_enough():
    assert key_hint(None) is None
    assert key_hint("") is None
    assert key_hint("a" * (KEY_HINT_MIN_LENGTH - 1)) is None
    assert key_hint("a" * (KEY_HINT_MIN_LENGTH - 2) + "q4") == "q4"
    assert key_hint("a" * (KEY_HINT_MIN_LENGTH - 3) + "q4") is None


async def test_the_jira_check_reads_once_and_never_writes(db: Database):
    kit = PracticeKit(db)
    assert await kit.jira.check() == "working"
    assert list(kit.store.calls) == ["GET /rest/api/2/myself"]
    assert await kit.store.tickets() == []

    kit.store.fail_next(503, times=3)
    assert await kit.jira.check() == "not_answering"
    assert list(kit.store.calls) == ["GET /rest/api/2/myself"]
    assert [kit.store.take_failure() is None for _ in range(3)] == [False, False, True]

    kit.store.fail_next(429)
    assert await kit.jira.check() == "not_answering"

    kit.store.answering = False
    assert await kit.jira.check() == "not_answering"
    kit.store.answering = True
    assert await kit.jira.check() == "working"


async def test_jira_that_does_not_accept_the_token_needs_attention(db: Database):
    kit = PracticeKit(db)
    other = JiraRestAdapter(
        BASE, "datacenter", JiraAuth.bearer("not-the-token"), kit.client, sleep=no_wait
    )
    assert await other.check() == "token_refused"
    kit.store.fail_next(403)
    assert await kit.jira.check() == "token_refused"


async def test_jira_that_cannot_be_reached_is_not_answering():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    jira = JiraRestAdapter(BASE, "datacenter", JiraAuth.bearer("t"), client, sleep=no_wait)
    assert await jira.check() == "not_answering"


async def test_an_answer_that_is_not_jiras_is_not_a_working_jira():
    def sign_in_page(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Sign in</html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(sign_in_page))
    jira = JiraRestAdapter(BASE, "datacenter", JiraAuth.bearer("t"), client, sleep=no_wait)
    assert await jira.check() == "not_answering"


def jira_at(db: Database, identity: Identity, probe: Scripted) -> Connections:
    return Connections(db, [Entry("jira", "Jira", identity, Checked(probe))])


async def test_going_back_to_an_address_and_key_shows_what_was_found_with_them(db: Database):
    first, second = identity_of("jira", "https://a", "k1"), identity_of("jira", "https://a", "k2")
    refused = Scripted(Reading("needs_attention", REFUSED.problem, key_ends_in="k1"))
    (before,) = await jira_at(db, first, refused).view()
    (other,) = await jira_at(db, second, Scripted(Reading("working", key_ends_in="k2"))).view()
    assert (other.state, other.key_ends_in) == ("working", "k2")
    asked = Scripted()
    (back,) = await jira_at(db, first, asked).view()
    assert back == before and asked.calls == 0


async def test_the_identity_kept_is_a_fingerprint_never_the_address_or_the_key(db: Database):
    env = {
        **LOCAL_ENV,
        "TEAMS_WEBHOOK_URL": "https://example.invalid/hook?sig=secret-value",
        "JIRA_BASE_URL": "https://jira.example.invalid",
        "JIRA_API_TOKEN": "jira-token-secret-q4",
    }
    settings = settings_from_env(env)
    teams = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(202)))
    channel, _ = approval_channel(settings, TeamsStub(db, "Ops"), teams)
    connections, watched = connections_for(
        settings,
        db,
        FakeJira("token_refused"),
        channel,
        FakeRuntime(GitHubWorking(using_token=False)),
        FakeModels(SettingsState(True, ACTIVE, None, [])),
    )
    await connections.view()
    await watched.announce(NOTICE)
    async with db.transaction("orchestration") as uow:
        rows = await (
            await uow.conn.execute("SELECT * FROM orchestration.connection_checks")
        ).fetchall()
    for secret in ("secret-value", "example.invalid", "jira-token-secret"):
        assert secret not in repr(rows)
    assert sorted(row["identity"].split(":")[0] for row in rows) == [
        "github",
        "jira",
        "teams_workflows",
    ]
    assert {row["key_ends_in"] for row in rows} == {None, "q4"}
