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
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
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
    source_of,
    teams_probe,
)
from platform_api.orchestration.dispatch import MessageRef
from platform_api.orchestration.jira_rest import JiraAuth, JiraReach, JiraRestAdapter
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import ANNOUNCE, SHOW_OUTCOME, START_LEG, RunRecord, Store
from platform_api.orchestration.write_actions import Proposal, WriteAction, digest
from platform_api.shared import ApprovalId, ProposalId, RunId
from platform_api.wiring import KEY_HINT_MIN_LENGTH, key_hint
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
        entries = [
            Entry(id, name, False, self.probes[id], live=id == "model")
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


REAL = "teams_workflows"


async def _post(db: Database, store: Store, kind: str, n: int, adapter: str | None) -> int:
    """An outbox row for approval n, with a posted message when adapter is given. Returns its id."""
    approval = ApprovalId(f"apr_t{n}")
    action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
    proposal = Proposal(ProposalId(f"prp_t{n}"), RUN, (action,), digest((action,)))
    request = ApprovalRequest(
        approval,
        RUN,
        proposal.id,
        proposal.digest,
        ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
        frozenset({ALICE.user_id}),
    )
    async with db.transaction("orchestration") as uow:
        await store.insert_proposal(uow, proposal)
        await store.insert_approval(uow, request)
        if adapter is not None:
            await store.save_message_ref(uow, approval, MessageRef("channel", f"m{n}", adapter))
        await store.enqueue(uow, RUN, kind, {"approval_id": approval}, NOW)
        row = await (
            await uow.conn.execute(
                "SELECT max(id) AS id FROM orchestration.outbox WHERE kind = %s", (kind,)
            )
        ).fetchone()
    assert row is not None
    return int(row["id"])


async def _insert_run(db: Database, store: Store) -> None:
    async with db.transaction("orchestration") as uow:
        pending = Pending(RUN, 1, None, NOW)
        record = RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, pending, (), None)
        await store.insert_run(uow, record, "k")


async def test_a_real_teams_channel_with_no_history_is_not_checked_yet(db: Database):
    result = await teams_probe(db, practice=False)()
    assert result == Reading(
        "not_checked", "Not checked yet. Teams is tried when the first approval request is sent."
    )
    connections = Connections(db, [Entry("teams", "Teams", False, teams_probe(db, practice=False))])
    (teams,) = await connections.view()
    assert (teams.state, teams.checked_at, teams.last_ok_at, teams.fix) == (
        "not_checked",
        None,
        None,
        None,
    )
    assert teams.problem == result.problem
    assert await connections.needing_attention() == []


async def test_the_first_outbox_result_turns_not_checked_into_a_state_at_once(db: Database):
    store = Store()
    await _insert_run(db, store)
    connections = Connections(db, [Entry("teams", "Teams", False, teams_probe(db, practice=False))])
    await connections.view()
    first = await _post(db, store, ANNOUNCE, 1, REAL)
    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, first)
    await connections.check_due()
    (teams,) = await connections.view()
    assert (teams.state, teams.problem) == ("working", None)
    assert teams.checked_at is not None and teams.last_ok_at is not None


async def test_a_first_failure_shows_not_answering_at_once(db: Database):
    store = Store()
    await _insert_run(db, store)
    connections = Connections(db, [Entry("teams", "Teams", False, teams_probe(db, practice=False))])
    await connections.view()
    failing = await _post(db, store, ANNOUNCE, 1, None)
    async with db.transaction("orchestration") as uow:
        await store.outbox_retry(uow, failing, NOW, "Teams answered 500 at https://secret")
    await connections.check_due()
    (teams,) = await connections.view()
    assert (teams.state, teams.last_ok_at) == ("not_answering", None)
    assert "secret" not in repr(teams)


async def test_messages_the_practice_copy_took_say_nothing_about_a_real_channel(db: Database):
    store = Store()
    await _insert_run(db, store)
    probe = teams_probe(db, practice=False)
    sent = await _post(db, store, ANNOUNCE, 1, "practice")
    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, sent)
    assert (await probe()).state == "not_checked"

    outcome = await _post(db, store, SHOW_OUTCOME, 2, "practice")
    async with db.transaction("orchestration") as uow:
        await store.outbox_give_up(uow, outcome, "gone")
    assert (await probe()).state == "not_checked"

    real = await _post(db, store, ANNOUNCE, 3, REAL)
    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, real)
    assert await probe() == Reading("working")


async def test_a_real_teams_channel_is_judged_by_the_last_message_the_outbox_tried(db: Database):
    store = Store()
    await _insert_run(db, store)
    probe = teams_probe(db, practice=False)
    pending = await _post(db, store, ANNOUNCE, 1, None)
    leg = await _post(db, store, START_LEG, 2, None)
    assert (await probe()).state == "not_checked"

    async with db.transaction("orchestration") as uow:
        await store.outbox_retry(uow, pending, NOW, "Teams answered 500 at https://secret")
    failing = await probe()
    assert (failing.state, failing.problem) == (
        "not_answering",
        "Teams did not take the last message.",
    )
    assert "secret" not in repr(failing)

    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, pending)
        await store.save_message_ref(uow, ApprovalId("apr_t1"), MessageRef("channel", "m1", REAL))
    assert await probe() == Reading("working")

    outcome = await _post(db, store, SHOW_OUTCOME, 3, REAL)
    async with db.transaction("orchestration") as uow:
        await store.outbox_give_up(uow, outcome, "gone")
    assert (await probe()).state == "not_answering"

    again = await _post(db, store, ANNOUNCE, 4, REAL)
    async with db.transaction("orchestration") as uow:
        await store.outbox_sent(uow, again)
        await store.outbox_retry(uow, leg, NOW, "n8n is down")
    assert await probe() == Reading("working")


async def test_the_model_row_is_read_fresh_on_every_view_and_never_kept(db: Database):
    state = SettingsState(True, ACTIVE, None, [])
    models = FakeModels(state)
    connections = Connections(
        db, [Entry("model", "AI model", False, model_probe(models), live=True)]
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


LIVE_SOURCE = source_of("teams_workflows", "https://example.invalid/hook?sig=secret-value")


def pair(db: Database, id: ConnectionId, name: str, first: Scripted, second: Scripted):
    """The same connection before and after a switch, sharing one table."""
    return (
        Connections(db, [Entry(id, name, True, first, "practice")]),
        Connections(db, [Entry(id, name, False, second, LIVE_SOURCE)]),
    )


@pytest.mark.parametrize(
    ("id", "name", "real_reading"),
    [
        ("teams", "Teams", Reading("not_checked", "Not checked yet.")),
        ("jira", "Jira", REFUSED),
        ("github", "GitHub", Reading("needs_attention", "GitHub does not accept the key.")),
    ],
)
async def test_going_live_starts_with_no_history_from_the_practice_copy(
    db: Database, id: ConnectionId, name: str, real_reading: Reading
):
    practice, real = pair(db, id, name, Scripted(), Scripted(real_reading))
    (before,) = await practice.view()
    assert (before.state, before.last_ok_at) == ("working", before.checked_at)

    (after,) = await real.view()
    assert after.state == real_reading.state
    assert after.last_ok_at is None
    assert after.practice is False
    checked = await real.check_now(id)
    assert checked is not None and checked.last_ok_at is None
    assert [c.id for c in await real.needing_attention()] == (
        [] if real_reading.state == "not_checked" else [id]
    )


async def test_a_real_copy_that_worked_is_not_shown_as_the_practice_copy(db: Database):
    real_side = Connections(db, [Entry("teams", "Teams", False, Scripted(), LIVE_SOURCE)])
    practice_side = Connections(db, [Entry("teams", "Teams", True, Scripted(DOWN), "practice")])
    await real_side.view()
    assert [c.id for c in await practice_side.needing_attention()] == []
    (back,) = await practice_side.view()
    assert (back.state, back.practice) == ("not_answering", True)
    assert back.last_ok_at is None


async def test_a_new_address_is_a_new_connection(db: Database):
    other = source_of("teams_workflows", "https://example.invalid/other-hook")
    old = Connections(db, [Entry("teams", "Teams", False, Scripted(), LIVE_SOURCE)])
    new = Connections(db, [Entry("teams", "Teams", False, Scripted(DOWN), other)])
    await old.view()
    (after,) = await new.view()
    assert (after.state, after.last_ok_at) == ("not_answering", None)


async def test_a_tick_checks_a_row_another_source_made_as_never_checked(db: Database):
    practice, real = pair(db, "jira", "Jira", Scripted(), Scripted(WORKING))
    await practice.view()
    await real.check_due()
    (after,) = await real.view()
    assert after.state == "working" and after.last_ok_at == after.checked_at


async def test_the_source_kept_is_a_fingerprint_never_the_address(db: Database):
    address = "https://example.invalid/hook?sig=secret-value"
    await Connections(
        db, [Entry("teams", "Teams", False, Scripted(), source_of("teams_workflows", address))]
    ).view()
    async with db.transaction("orchestration") as uow:
        rows = await (
            await uow.conn.execute("SELECT * FROM orchestration.connection_checks")
        ).fetchall()
    assert "secret-value" not in repr(rows) and "example.invalid" not in repr(rows)
    assert rows[0]["source"].startswith("teams_workflows:")
