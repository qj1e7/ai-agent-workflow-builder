"""The Jira contract (ADR 0035): what the platform needs from any Jira, run against a target.

CI always runs it against the practice Jira, in both flavors, over HTTP. With JIRA_CONTRACT_URL
set, the same tests run against a real sandbox too:

    JIRA_CONTRACT_URL      the sandbox, such as https://example.atlassian.net
    JIRA_CONTRACT_FLAVOR   datacenter or cloud (default datacenter)
    JIRA_CONTRACT_TOKEN    the token (a personal access token, or an API token for Cloud)
    JIRA_CONTRACT_EMAIL    the account's email, for Cloud
    JIRA_CONTRACT_PROJECT  a project the account may write to

Every ticket a test makes carries a fresh marker, so the tests never assume an empty Jira.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from platform_api.db import Database
from platform_api.orchestration.jira import (
    CLAIM_LEASE,
    CONNECTOR_DEADLINE,
    IssueSearch,
    JiraFlavor,
    JiraIssue,
    JiraRefused,
    JiraUnavailable,
    JiraWriteConnector,
    NewIssue,
    write_label,
)
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from platform_api.orchestration.write_actions import (
    CONNECTOR_TIMEOUT,
    WriteAction,
    WriteKey,
    WriteRefused,
)
from platform_api.practice_jira import PRACTICE_EMAIL, PracticeJira, practice_token
from platform_api.practice_jira import router as practice_router
from platform_api.shared import ProposalId, RunId

pytestmark = pytest.mark.anyio

SIGNING_KEY = "test-callback-key"
PRACTICE_BASE = "http://platform-api:8000/practice-jira"
PORTAL = "http://localhost:8080"
MARKUP = "*bold* _it_ -gone- {code}x{code} [a link|https://evil.test] !img.png! h1. top"
SANDBOX = os.environ.get("JIRA_CONTRACT_URL", "").strip()
TIME_LIMIT = 10.0
"""Seconds a test that waits on a deadline or on two tries at once may take."""


@dataclass
class Waits:
    seconds: list[float] = field(default_factory=list[float])

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


@dataclass
class Target:
    name: str
    flavor: JiraFlavor
    project: str
    jira: JiraRestAdapter
    waits: Waits
    client: httpx.AsyncClient
    base_url: str
    practice: PracticeJira | None = None

    def adapter(self, auth: JiraAuth) -> JiraRestAdapter:
        return JiraRestAdapter(self.base_url, self.flavor, auth, self.client, sleep=self.waits)

    def needs_practice(self) -> PracticeJira:
        if self.practice is None:
            pytest.skip("only the practice Jira can be told to fail")
        return self.practice


def practice_app(practice: PracticeJira) -> FastAPI:
    app = FastAPI()
    app.state.practice_jira = practice
    app.include_router(practice_router)
    return app


@pytest.fixture(params=["practice-datacenter", "practice-cloud", "sandbox"])
async def target(request: pytest.FixtureRequest, db: Database) -> AsyncIterator[Target]:
    waits = Waits()
    name: str = request.param
    if name == "sandbox":
        if not SANDBOX:
            pytest.skip("JIRA_CONTRACT_URL is not set")
        flavor: JiraFlavor = (
            "cloud" if os.environ.get("JIRA_CONTRACT_FLAVOR") == "cloud" else "datacenter"
        )
        token = os.environ["JIRA_CONTRACT_TOKEN"]
        auth = (
            JiraAuth.basic(os.environ["JIRA_CONTRACT_EMAIL"], token)
            if flavor == "cloud"
            else JiraAuth.bearer(token)
        )
        async with httpx.AsyncClient(timeout=20) as client:
            jira = JiraRestAdapter(SANDBOX, flavor, auth, client, sleep=waits)
            yield Target(
                name, flavor, os.environ["JIRA_CONTRACT_PROJECT"], jira, waits, client, SANDBOX
            )
        return
    flavor = "cloud" if name == "practice-cloud" else "datacenter"
    practice = PracticeJira(db, practice_token(SIGNING_KEY), PORTAL)
    transport = httpx.ASGITransport(app=practice_app(practice))
    async with httpx.AsyncClient(transport=transport) as client:
        auth = JiraAuth.of(flavor, practice_token(SIGNING_KEY), PRACTICE_EMAIL)
        jira = JiraRestAdapter(PRACTICE_BASE, flavor, auth, client, sleep=waits)
        yield Target(name, flavor, "MOCK", jira, waits, client, PRACTICE_BASE, practice)


def marker() -> str:
    return "wab" + uuid.uuid4().hex[:12]


async def made(target: Target, title: str, body: str = "", label: str | None = None) -> str:
    labels = (label,) if label else ()
    return await target.jira.create_issue(NewIssue(target.project, title, body, labels))


def as_stored(target: Target, body: str) -> str:
    """Data Center's body sits in a {noformat} block, so a {noformat} inside it is broken up."""
    if target.flavor == "datacenter":
        return body.replace("{noformat", "{ noformat")
    return body


async def test_a_new_ticket_reads_back_as_written(target: Target):
    word = marker()
    body = f"First line {word}.\nSecond line.\n\nA new paragraph.\n{MARKUP} {{noformat}} end"
    key = await made(target, f"Upgrade LangGraph to 1.2.16 {word}", body, f"{word}-label")
    assert key.startswith(f"{target.project}-")
    issue = await target.jira.get_issue(key)
    assert issue is not None
    assert (issue.key, issue.project) == (key, target.project)
    assert issue.title == f"Upgrade LangGraph to 1.2.16 {word}"
    assert issue.body == as_stored(target, body)
    assert issue.status == "To Do" and issue.done_at is None
    assert f"{word}-label" in issue.labels
    assert abs(issue.created_at - datetime.now(UTC)) < timedelta(minutes=5)


async def test_our_write_label_finds_the_ticket_and_who_made_it(target: Target):
    word = marker()
    key = await made(target, f"Labelled {word}", label=f"{word}-write")
    found = await target.jira.find_by_label(target.project, f"{word}-write")
    assert found is not None and found.key == key
    assert found.creator is not None and found.creator == await target.jira.whoami()
    assert await target.jira.find_by_label(target.project, f"{word}-other") is None


async def test_a_search_matches_any_word_in_the_projects_newest_first(target: Target):
    first, second = marker(), marker()
    older = await made(target, f"Older {first}")
    newer = await made(target, "Newer", f"The body names {second}.")
    found = await target.jira.search(IssueSearch((target.project,), (first, second)))
    assert [issue.key for issue in found] == [newer, older]
    only = await target.jira.search(IssueSearch((target.project,), (second,)))
    assert [issue.key for issue in only] == [newer]


async def test_moving_a_ticket_to_done_sets_its_status_and_resolution_day(target: Target):
    word = marker()
    open_key = await made(target, f"Stays open {word}")
    done_key = await made(target, f"Gets done {word}")
    await target.jira.move_to_done(done_key)
    issue = await target.jira.get_issue(done_key)
    assert issue is not None and issue.status == "Done" and issue.done_at is not None
    done = await target.jira.search(IssueSearch((target.project,), (word,), status="Done"))
    assert [i.key for i in done] == [done_key]
    to_do = await target.jira.search(IssueSearch((target.project,), (word,), status="To Do"))
    assert [i.key for i in to_do] == [open_key]
    since = datetime.now(UTC) - timedelta(days=1)
    recent = await target.jira.search(IssueSearch((target.project,), (word,), done_since=since))
    assert [i.key for i in recent] == [done_key]


async def test_done_tickets_answers_the_done_ones_and_skips_a_key_that_is_gone(target: Target):
    word = marker()
    open_key = await made(target, f"Open {word}")
    done_key = await made(target, f"Done {word}")
    await target.jira.move_to_done(done_key)
    gone = f"{target.project}-987654"
    done = await target.jira.done_tickets([open_key, done_key, gone])
    assert list(done) == [done_key]


async def test_a_ticket_that_is_not_there_is_none(target: Target):
    assert await target.jira.get_issue(f"{target.project}-987654") is None


async def test_a_ticket_with_no_title_is_refused_for_good(target: Target):
    with pytest.raises(JiraRefused) as refused:
        await made(target, "")
    assert refused.value.retryable is False
    assert "summary" in str(refused.value).lower()


async def test_a_wrong_token_is_a_failure_that_may_be_retried(target: Target):
    wrong = target.adapter(JiraAuth.bearer("not-the-token"))
    with pytest.raises(JiraUnavailable) as failed:
        await wrong.get_issue(f"{target.project}-1")
    assert failed.value.retryable is True
    assert "token" in str(failed.value)


async def test_errors_come_in_jiras_own_shape(target: Target):
    version = "3" if target.flavor == "cloud" else "2"
    response = await target.client.post(
        f"{target.base_url}/rest/api/{version}/issue",
        json={"fields": {"project": {"key": target.project}, "issuetype": {"name": "Task"}}},
        headers={"Authorization": target.jira.auth_header},
    )
    assert response.status_code == 400
    body = response.json()
    assert isinstance(body["errorMessages"], list) and isinstance(body["errors"], dict)
    assert "summary" in body["errors"]
    anonymous = await target.client.get(f"{target.base_url}/rest/api/{version}/project/MOCK")
    assert anonymous.status_code == 401


async def test_a_busy_jira_is_waited_for_by_its_retry_after(target: Target):
    practice = target.needs_practice()
    practice.fail_next(429, times=1, retry_after=2)
    assert await target.jira.get_issue("MOCK-987654") is None
    assert target.waits.seconds == [2]


async def test_a_long_retry_after_is_cut_short(target: Target):
    practice = target.needs_practice()
    practice.fail_next(503, times=1, retry_after=600)
    assert await target.jira.get_issue("MOCK-987654") is None
    assert target.waits.seconds == [5]


async def test_jira_down_three_times_fails_in_a_way_that_may_be_retried(target: Target):
    practice = target.needs_practice()
    practice.fail_next(503, times=3)
    with pytest.raises(JiraUnavailable) as failed:
        await target.jira.get_issue("MOCK-1")
    assert failed.value.retryable is True
    assert len(target.waits.seconds) == 2


async def test_a_rate_limited_create_is_tried_again_and_makes_one_ticket(target: Target):
    practice = target.needs_practice()
    practice.fail_next(429, times=1, retry_after=1)
    key = await made(target, "Made after one wait")
    assert [t.key for t in await practice.tickets()] == [key]


ACTION = WriteAction(
    "jira", "create_ticket", {"project": "MOCK"}, {"title": "Upgrade", "body": "Soon."}
)
WRITE = WriteKey(RunId("run_01ABC"), ProposalId("prp_01DEF"), 0)


async def test_a_retry_after_a_made_ticket_uses_our_record_and_never_searches(
    target: Target, db: Database
):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    first = await connector.execute(ACTION, WRITE)
    practice.calls.clear()
    assert await connector.execute(ACTION, WRITE) == first
    assert list(practice.calls) == []
    other = await connector.execute(ACTION, WriteKey(WRITE.run_id, WRITE.proposal_id, 1))
    tickets = await practice.tickets()
    assert [t.key for t in tickets] == [first, other]
    assert tickets[0].labels == (write_label(WRITE),)
    assert (tickets[0].run_id, tickets[0].proposal_id) == ("run_01ABC", "prp_01DEF")


async def test_a_crash_after_jiras_201_finds_our_own_ticket_and_makes_no_second(
    target: Target, db: Database
):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    # As if the platform stopped after Jira made the ticket and before it noted the key.
    await crashed(connector, WRITE)
    made = await target.jira.create_issue(
        NewIssue("MOCK", "Upgrade", "Soon.", (write_label(WRITE),))
    )
    assert await connector.execute(ACTION, WRITE) == made
    assert [t.key for t in await practice.tickets()] == [made]


async def test_a_ticket_someone_else_planted_with_our_label_is_never_taken_as_ours(
    target: Target, db: Database
):
    practice = target.needs_practice()
    planted = await practice.create(
        "MOCK", "Looks like ours", "", [write_label(WRITE)], "Task", creator="mallory"
    )
    connector = JiraWriteConnector(target.jira, db)
    # With no record of our own, the platform does not search: it makes its own ticket.
    ours = await connector.execute(ACTION, WRITE)
    assert ours != planted.key
    # After a crash, a label match that another account made needs a person.
    other = WriteKey(WRITE.run_id, WRITE.proposal_id, 2)
    await practice.create("MOCK", "Planted", "", [write_label(other)], "Task", creator="mallory")
    await crashed(connector, other)
    with pytest.raises(WriteRefused, match="did not make it"):
        await connector.execute(ACTION, other)


async def test_a_create_jira_refused_or_was_too_busy_for_is_tried_fresh_next_time(
    target: Target, db: Database
):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    practice.fail_next(429, times=3, retry_after=1)
    with pytest.raises(JiraUnavailable):
        await connector.execute(ACTION, WRITE)
    practice.calls.clear()
    made = await connector.execute(ACTION, WRITE)
    assert not [call for call in practice.calls if "search" in call]
    assert [t.key for t in await practice.tickets()] == [made]


async def test_the_connector_turns_a_refusal_into_a_write_that_is_not_retried(
    target: Target, db: Database
):
    target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "", "body": ""})
    with pytest.raises(WriteRefused):
        await connector.execute(action, WriteKey(RunId("run_1"), ProposalId("prp_1"), 0))


async def crashed(connector: JiraWriteConnector, key: WriteKey) -> None:
    """As if a try for this key began, and stopped before noting a ticket, its claim gone."""
    assert await connector.records.claim(key.text) is not None
    await connector.records.release(key.text)


async def ours(target: Target, title: str, labels: list[str]) -> str:
    return await target.jira.create_issue(NewIssue("MOCK", title, "", tuple(labels)))


async def test_a_found_ticket_with_no_creator_is_refused(target: Target, db: Database):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    await practice.create("MOCK", "Upgrade", "", [write_label(WRITE)], "Task", creator=None)
    await crashed(connector, WRITE)
    with pytest.raises(WriteRefused, match="did not make it"):
        await connector.execute(ACTION, WRITE)


async def test_a_found_ticket_already_recorded_for_another_write_is_refused(
    target: Target, db: Database
):
    target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    other = WriteKey(WRITE.run_id, WRITE.proposal_id, 5)
    theirs = await connector.execute(ACTION, other)
    # A person gave that ticket this write's label and took the other one off.
    await target.needs_practice().set_labels(theirs, [write_label(WRITE)])
    await crashed(connector, WRITE)
    with pytest.raises(WriteRefused, match="another write"):
        await connector.execute(ACTION, WRITE)


async def test_a_found_ticket_with_another_writes_label_is_refused(target: Target, db: Database):
    target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    other = WriteKey(WRITE.run_id, WRITE.proposal_id, 6)
    await ours(target, "Upgrade", [write_label(other), write_label(WRITE)])
    await crashed(connector, WRITE)
    with pytest.raises(WriteRefused, match="another write"):
        await connector.execute(ACTION, WRITE)


async def test_a_found_ticket_with_another_title_is_refused(target: Target, db: Database):
    target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    await ours(target, "Rotate the keys", [write_label(WRITE)])
    await crashed(connector, WRITE)
    with pytest.raises(WriteRefused, match="title"):
        await connector.execute(ACTION, WRITE)


async def test_two_tries_of_one_write_at_once_make_one_ticket(target: Target, db: Database):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    results = await asyncio.wait_for(
        asyncio.gather(
            connector.execute(ACTION, WRITE),
            connector.execute(ACTION, WRITE),
            return_exceptions=True,
        ),
        TIME_LIMIT,
    )
    keys = [r for r in results if isinstance(r, str)]
    others = [r for r in results if not isinstance(r, str)]
    assert len(await practice.tickets()) == 1
    assert keys and all(key == keys[0] for key in keys)
    assert all(
        isinstance(e, JiraUnavailable) and e.retryable and "in progress" in str(e) for e in others
    )


class HangingJira:
    """A Jira that never answers."""

    async def find_by_label(self, project: str, label: str) -> JiraIssue | None:
        await asyncio.sleep(3600)
        return None

    async def create_issue(self, issue: NewIssue) -> str:
        await asyncio.sleep(3600)
        return ""

    def browse_url(self, key: str) -> str:
        return key


def test_a_try_ends_before_its_claim_and_the_claim_before_the_gateway_calls_it_lost():
    assert CONNECTOR_DEADLINE < CLAIM_LEASE < CONNECTOR_TIMEOUT
    assert timedelta(seconds=5) <= CLAIM_LEASE - CONNECTOR_DEADLINE


async def test_a_jira_that_never_answers_fails_the_try_in_time_and_frees_the_write(db: Database):
    connector = JiraWriteConnector(HangingJira(), db, deadline=timedelta(seconds=0.2))  # type: ignore[arg-type]
    started = asyncio.get_running_loop().time()
    with pytest.raises(JiraUnavailable) as failed:
        # Its own limit, so a deadline that stops working fails here in seconds.
        await asyncio.wait_for(connector.execute(ACTION, WRITE), TIME_LIMIT)
    assert failed.value.retryable is True
    assert asyncio.get_running_loop().time() - started < 2
    record = await connector.records.get(WRITE.text)
    assert record is not None and record.claimed_at is None and record.ticket_key is None


async def test_a_found_ticket_made_before_the_write_began_is_refused(target: Target, db: Database):
    practice = target.needs_practice()
    connector = JiraWriteConnector(target.jira, db)
    earlier = practice.now() - timedelta(minutes=10)
    await practice.create("MOCK", "Upgrade", "", [write_label(WRITE)], "Task", created_at=earlier)
    await crashed(connector, WRITE)
    with pytest.raises(WriteRefused, match="before this write began"):
        await connector.execute(ACTION, WRITE)


async def test_the_practice_jira_notes_only_signed_in_calls_and_only_the_latest(target: Target):
    practice = target.needs_practice()
    version = "3" if target.flavor == "cloud" else "2"
    await target.client.get(f"{target.base_url}/rest/api/{version}/project/MOCK")
    assert list(practice.calls) == []
    assert practice.calls.maxlen is not None and practice.calls.maxlen <= 500


async def test_done_since_means_the_same_moment_in_jiras_own_time_zone(target: Target):
    word = marker()
    key = await made(target, f"Done just now {word}")
    await target.jira.move_to_done(key)
    issue = await target.jira.get_issue(key)
    assert issue is not None and issue.done_at is not None
    later = issue.done_at + timedelta(minutes=2)
    earlier = issue.done_at - timedelta(minutes=2)
    project = (target.project,)
    assert await target.jira.search(IssueSearch(project, (word,), done_since=later)) == []
    found = await target.jira.search(IssueSearch(project, (word,), done_since=earlier))
    assert [i.key for i in found] == [key]
