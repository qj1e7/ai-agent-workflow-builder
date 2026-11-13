"""A new use case is born on an n8n workflow of its own, saved there as a draft that the safety
checker graded (ENGINE-PLAN 2.5), and node calls learn about it from the builder's facts."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, LiteralString

import httpx
import pytest

from platform_api.builder import Builder
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.n8n_draft import ADDING, CHECKING, EVERY_WRITE, FIT, SAVED
from platform_api.builder.n8n_facts import BuilderWorkflowFacts
from platform_api.db import Database
from platform_api.orchestration import (
    AgentRejected,
    AgentToRun,
    AgentUnavailable,
    CannotRun,
    NodeOption,
    Publisher,
    RanVersion,
    ReadFailed,
    ReadReleasesRequest,
    ReadReleasesResult,
    ReleasesNotRead,
    ReleasesRead,
    grade,
)
from platform_api.orchestration.agents import ReleaseRead
from platform_api.orchestration.n8n import N8nApi, N8nWorkflows
from platform_api.settings import N8nOwner
from platform_api.shared import UserId
from tests import test_builder_lifecycle
from tests.fake_n8n import OWNER_EMAIL, OWNER_PASSWORD, FakeN8n
from tests.test_builder_lifecycle import VALUES, Lab, ModelConnected

pytestmark = pytest.mark.anyio

lab = test_builder_lifecycle.lab
ERROR_WORKFLOW = "wfErrorReporter01"
REPO = VALUES["GitHub repository"]
BODY: dict[str, Any] = {
    "name": "LangGraph release check",
    "instruction": "Check LangGraph for new releases.",
    "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
    "schedule": {"day": "every_day", "at": "08:00"},
    "on": False,
}


class Drafts(N8nWorkflows):
    """The real drafts store on a fake n8n, with bootstrap's error workflow loaded."""

    def __init__(
        self, n8n: FakeN8n, db: Database, error_workflow: str | None = ERROR_WORKFLOW
    ) -> None:
        owner = N8nOwner(OWNER_EMAIL, OWNER_PASSWORD)
        super().__init__(N8nApi("http://n8n", owner, n8n.client()), db)
        self._error_workflow = error_workflow

    async def error_workflow(self) -> str | None:
        return self._error_workflow


@dataclass
class Releases:
    answer: ReadReleasesResult | AgentUnavailable | AgentRejected

    async def read_releases(
        self, request: ReadReleasesRequest
    ) -> ReadReleasesResult | AgentUnavailable | AgentRejected:
        return self.answer


@dataclass
class N8nLab:
    lab: Lab
    n8n: FakeN8n

    async def create(self, body: Mapping[str, Any] = BODY) -> httpx.Response:
        return await self.lab.call("alice", "POST", "/api/v1/agent-use-cases", body)

    async def row(self, sql: LiteralString, *args: object) -> dict[str, Any] | None:
        async with self.lab.h.db.connection("builder") as conn:
            found = await (await conn.execute(sql, args)).fetchone()
        return None if found is None else dict(found)

    def facts(self, releases: Releases | None = None) -> BuilderWorkflowFacts:
        reader = releases or Releases(ReleasesRead(releases=[]))
        return BuilderWorkflowFacts(self.lab.h.db, self.lab.builder, reader)


def with_n8n(lab: Lab, drafts: N8nWorkflows) -> None:
    lab.builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=drafts,
    )
    lab.app.state.builder = lab.builder


@pytest.fixture
async def n8n_lab(lab: Lab) -> AsyncIterator[N8nLab]:
    n8n = FakeN8n()
    with_n8n(lab, Drafts(n8n, lab.h.db))
    yield N8nLab(lab, n8n)


async def test_a_new_use_case_is_saved_in_n8n_as_a_draft_the_checker_graded_safe(n8n_lab: N8nLab):
    created = await n8n_lab.create()
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["n8n_workflow_id"], body["grade"]) == ("wf1", "safe")
    held = n8n_lab.n8n.workflows["wf1"]
    assert held["activeVersionId"] is None, "a draft is never published"
    assert grade(held, ERROR_WORKFLOW).grade == "safe"
    names = [block["name"] for block in body["blocks"]]
    assert names == [
        "Daily 8:00",
        "Start from the Portal",
        "Read release",
        "Compare",
        "Newer?",
        "Ask for a yes",
        "Create ticket",
        "Nothing to change",
    ]
    ask = next(b for b in body["blocks"] if b["name"] == "Ask for a yes")
    assert {"exit": "Yes", "to": "Create ticket"} in ask["next"]


async def test_the_build_log_replays_in_the_sketch_s_words_and_order(n8n_lab: N8nLab):
    log = (await n8n_lab.create()).json()["build_log"]
    assert [(line["kind"], line["text"]) for line in log] == [
        ("status", ADDING),
        ("check", FIT),
        ("status", CHECKING),
        ("note", "Added a yes before the ticket."),
        ("check", EVERY_WRITE),
        ("status", SAVED),
    ]
    times = [datetime.fromisoformat(line["at"]) for line in log]
    assert times == sorted(times)


async def test_the_use_case_keeps_its_workflow_and_the_version_keeps_n8n_s_record(
    n8n_lab: N8nLab,
):
    use_case_id = (await n8n_lab.create()).json()["use_case_id"]
    use_case = await n8n_lab.row(
        "SELECT engine, n8n_workflow_id, draft FROM builder.use_cases WHERE use_case_id = %s",
        use_case_id,
    )
    assert use_case == {"engine": "own", "n8n_workflow_id": "wf1", "draft": True}
    version = await n8n_lab.row(
        "SELECT n8n_version_id, grade, published_by, published_in, document"
        " FROM builder.use_case_versions WHERE use_case_id = %s",
        use_case_id,
    )
    assert version is not None
    held = n8n_lab.n8n.workflows["wf1"]
    assert (version["n8n_version_id"], version["grade"]) == (held["versionId"], "safe")
    assert (version["published_by"], version["published_in"]) == (None, None)
    assert version["document"]["nodes"] == held["nodes"]
    view = await n8n_lab.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")
    assert [b["name"] for b in view.json()["blocks"]][:3] == [
        "Daily 8:00",
        "Start from the Portal",
        "Read release",
    ]


async def test_when_n8n_does_not_take_the_draft_nothing_is_set_up(lab: Lab):
    n8n = FakeN8n()
    n8n.keeps = lambda document: {**document, "nodes": document["nodes"][1:]}
    with_n8n(lab, Drafts(n8n, lab.h.db))
    refused = await N8nLab(lab, n8n).create()
    assert refused.status_code == 503
    assert refused.json()["detail"] == "n8n did not take the draft. Try again in a minute."
    assert n8n.workflows == {}, "the draft n8n changed on the way in is removed"
    assert await lab.listed() == []


async def test_n8n_without_its_error_workflow_is_not_ready(lab: Lab):
    n8n = FakeN8n()
    with_n8n(lab, Drafts(n8n, lab.h.db, error_workflow=None))
    refused = await N8nLab(lab, n8n).create()
    assert refused.status_code == 503
    assert (n8n.workflows, await lab.listed()) == ({}, [])


async def test_without_n8n_a_use_case_runs_on_the_shared_workflow(lab: Lab):
    created = await lab.call("alice", "POST", "/api/v1/agent-use-cases", BODY)
    assert created.status_code == 201
    assert (created.json()["n8n_workflow_id"], created.json()["build_log"]) == (None, [])
    [listed] = await lab.listed()
    assert listed["blocks"] == []


async def test_node_calls_find_the_use_case_and_its_draft_s_grade(n8n_lab: N8nLab):
    use_case_id = (await n8n_lab.create()).json()["use_case_id"]
    facts = n8n_lab.facts()
    own = await facts.workflow("wf1")
    assert own is not None
    assert (own.spec.use_case_id, own.holder) == (use_case_id, None)
    assert await facts.workflow("wf-someone-else") is None
    draft = n8n_lab.n8n.workflows["wf1"]["versionId"]
    assert await facts.version("wf1", draft) == RanVersion("safe", None)
    assert await facts.version("wf1", "v-unknown") is None


async def test_a_version_published_from_the_portal_runs_as_the_person_who_published_it(
    n8n_lab: N8nLab,
):
    use_case_id = (await n8n_lab.create()).json()["use_case_id"]
    async with n8n_lab.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET published_by = 'bob', published_in = 'portal'"
            " WHERE use_case_id = %s",
            (use_case_id,),
        )
    draft = n8n_lab.n8n.workflows["wf1"]["versionId"]
    ran = await n8n_lab.facts().version("wf1", draft)
    assert ran == RanVersion("safe", Publisher(UserId("bob")))


async def test_a_deleted_use_case_s_workflow_is_no_longer_ours(n8n_lab: N8nLab):
    use_case_id = (await n8n_lab.create()).json()["use_case_id"]
    await n8n_lab.lab.move("alice", "delete", use_case_id)
    assert await n8n_lab.facts().workflow("wf1") is None


async def test_the_version_checker_runs_with_its_repository_as_what_its_change_is_about(
    n8n_lab: N8nLab,
):
    facts = n8n_lab.facts()
    run = await facts.agent_run(VERSION_CHECKER_ID, VALUES)
    assert isinstance(run, AgentToRun)
    assert run.release_of == REPO
    assert run.card_run.bindings["jira.create_ticket"].target == {"project": "MOCK"}
    assert await facts.agent_run("crd_nobody", VALUES) is None


async def test_an_agent_without_its_write_target_is_refused_never_given_a_default(
    n8n_lab: N8nLab,
):
    refused = await n8n_lab.facts().agent_run(VERSION_CHECKER_ID, {"GitHub repository": REPO})
    assert refused == CannotRun(
        '"Version checker" needs "Jira project", so our platform knows where its change goes.'
    )


async def test_a_read_block_may_read_the_repositories_the_version_checker_watches(
    n8n_lab: N8nLab,
):
    await n8n_lab.create()
    facts = n8n_lab.facts()
    assert await facts.places("github_releases") == [NodeOption(REPO, REPO)]
    assert await facts.places("confluence_page") == []


async def test_a_read_block_gets_the_releases_newest_first_or_github_s_trouble(n8n_lab: N8nLab):
    read = ReleasesRead(
        releases=[
            ReleaseRead(tag="1.2.16", name="1.2.16", published_at="2026-11-12T08:00:00Z"),
            ReleaseRead(tag="1.2.15", name=None, published_at=None),
        ]
    )
    items = await n8n_lab.facts(Releases(read)).read("github_releases", REPO, None)
    assert [item["id"] for item in items] == ["1.2.16", "1.2.15"]  # type: ignore[index]
    trouble = ReleasesNotRead(message="GitHub returned 503 Service Unavailable.", retryable=True)
    failed = await n8n_lab.facts(Releases(trouble)).read("github_releases", REPO, None)
    assert failed == ReadFailed("GitHub returned 503 Service Unavailable.")
    down = await n8n_lab.facts(Releases(AgentUnavailable("down"))).read(
        "github_releases", REPO, None
    )
    assert down == ReadFailed("down")
