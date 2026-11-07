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
    ConnectionId,
    Connections,
    Entry,
    Reading,
    Shown,
    due,
    github_probe,
    jira_probe,
    model_probe,
    settle,
    teams_probe,
)
from platform_api.orchestration.jira_rest import JiraAuth, JiraReach, JiraRestAdapter
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import ANNOUNCE, SHOW_OUTCOME, START_LEG, RunRecord, Store
from platform_api.shared import RunId
from tests.practice import BASE, PracticeKit, no_wait
from tests.support import ALICE, NOW, SPEC
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
    assert first.checked_at == later
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
    assert settle(down, WORKING, later, at_once=True).last_ok_at == later


def test_a_tick_checks_what_was_never_checked_what_waits_for_a_second_reading_and_the_hourly():
    assert due(None, T0)
    assert due(shown(unconfirmed_state="not_answering"), T0 + timedelta(minutes=5))
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
        entries = [Entry(id, name, False, self.probes[id]) for id, name in names.items()]
        self.connections = Connections(self.db, entries)


@pytest.fixture
def rig(db: Database) -> Rig:
    return Rig(db)


async def test_the_first_view_checks_each_connection_once_and_keeps_the_result(rig: Rig):
    first = await rig.connections.view()
    again = await rig.connections.view()
    assert [c.id for c in first] == ["jira", "github", "teams", "model"]
    assert all(c.state == "working" for c in first)
    assert [p.calls for p in rig.probes.values()] == [1, 1, 1, 1]
    assert again == first


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
    assert [p.calls for p in rig.probes.values()] == [3, 1, 1, 1]


async def _age(db: Database, connection: str, by: timedelta) -> None:
    async with db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.connection_checks SET checked_at = checked_at - %s "
            "WHERE connection = %s",
            (by, connection),
        )


async def test_what_needs_attention_is_read_from_what_was_kept_and_asks_nobody(rig: Rig):
    assert await rig.connections.needing_attention() == []
    assert [p.calls for p in rig.probes.values()] == [0, 0, 0, 0]

    rig.probes["jira"].reading = DOWN
    rig.probes["model"].reading = Reading("not_set_up", "No AI model is turned on.")
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


async def test_the_practice_teams_always_takes_a_message(db: Database):
    assert await teams_probe(db, practice=True)() == Reading("working")


async def test_a_real_teams_channel_is_judged_by_the_last_message_the_outbox_tried(db: Database):
    probe = teams_probe(db, practice=False)
    assert await probe() == Reading("working")
    store = Store()
    async with db.transaction("orchestration") as uow:
        pending = Pending(RUN, 1, None, NOW)
        record = RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, pending, (), None)
        await store.insert_run(uow, record, "k")
        await store.enqueue(uow, RUN, ANNOUNCE, {}, NOW)
        await store.enqueue(uow, RUN, START_LEG, {}, NOW)
    assert await probe() == Reading("working")

    async def newest(kind: str) -> int:
        async with db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT max(id) AS id FROM orchestration.outbox WHERE kind = %s", (kind,)
                )
            ).fetchone()
        assert row is not None
        return int(row["id"])

    announce = await newest(ANNOUNCE)
    async with db.transaction("orchestration") as uow:
        await store.outbox_retry(uow, announce, NOW, "Teams answered 500 at https://secret")
    failing = await probe()
    assert (failing.state, failing.problem) == (
        "not_answering",
        "Teams did not take the last message.",
    )
    assert "secret" not in repr(failing)

    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, announce)
    assert await probe() == Reading("working")

    async with db.transaction("orchestration") as uow:
        await store.enqueue(uow, RUN, SHOW_OUTCOME, {}, NOW)
    outcome = await newest(SHOW_OUTCOME)
    async with db.transaction("orchestration") as uow:
        await store.outbox_give_up(uow, outcome, "gone")
    assert (await probe()).state == "not_answering"

    async with db.transaction("orchestration") as uow:
        await store.enqueue(uow, RUN, ANNOUNCE, {}, NOW)
    again = await newest(ANNOUNCE)
    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, again)
        await store.outbox_retry(uow, await newest(START_LEG), NOW, "n8n is down")
    assert await probe() == Reading("working")


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
