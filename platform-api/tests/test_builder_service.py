from dataclasses import dataclass, field

import pytest

from platform_api.builder import TAG_PATTERN, Builder
from platform_api.builder.models import CreateUseCase, UseCaseCreated
from platform_api.builder.templates import ParamErrors, UnknownTemplate
from platform_api.db import Database
from platform_api.orchestration import AnyApprover, Binding, ReleaseTask, RunSpec, RunStarted
from platform_api.shared import Principal, Role, RunId, UseCaseId, UserId

pytestmark = pytest.mark.anyio

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
INSTRUCTION = "Check langchain-ai/langgraph for new releases and open a ticket for the team."


@dataclass
class FakeRuns:
    carry_forward: str | None = None
    started: list[tuple[RunSpec, Principal, str]] = field(default_factory=lambda: [])

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.started.append((spec, principal, idempotency_key))
        return RunStarted(RunId("run_1"), created=True)

    async def latest_carry_forward(self, use_case_id: UseCaseId) -> str | None:
        return self.carry_forward


def body(**params: str) -> CreateUseCase:
    return CreateUseCase(
        template="release_check",
        name="LangGraph releases",
        instruction=INSTRUCTION,
        params={"repo": "langchain-ai/langgraph", "ticket_project": "MOCK", **params},
    )


async def created(builder: Builder, **params: str) -> UseCaseCreated:
    result = await builder.create_use_case(ALICE, body(**params))
    assert isinstance(result, UseCaseCreated)
    return result


@pytest.fixture
def runs() -> FakeRuns:
    return FakeRuns()


@pytest.fixture
def builder(db: Database, runs: FakeRuns) -> Builder:
    return Builder(db, runs, "http://localhost:8080")


async def test_a_created_use_case_reads_back_as_version_one_owned_by_the_creator(
    builder: Builder,
):
    result = await created(builder)
    assert result.version == 1
    assert result.use_case_id.startswith("uc_")
    view = await builder.get_use_case(result.use_case_id)
    assert view is not None
    assert (view.version, view.owner, view.template, view.name) == (
        1,
        "alice",
        "release_check",
        "LangGraph releases",
    )
    assert view.params == {
        "repo": "langchain-ai/langgraph",
        "ticket_project": "MOCK",
        "tag_pattern": TAG_PATTERN,
    }
    assert view.instruction == INSTRUCTION


async def test_listing_shows_every_use_case_newest_first(builder: Builder):
    first = await created(builder)
    second = await created(builder)
    listed = await builder.list_use_cases()
    assert [u.use_case_id for u in listed.use_cases] == [second.use_case_id, first.use_case_id]


async def test_a_missing_use_case_is_none(builder: Builder):
    assert await builder.get_use_case("uc_nope") is None
    assert await builder.run_spec_for(UseCaseId("uc_nope")) is None


async def test_bad_params_and_unknown_templates_save_nothing(builder: Builder):
    bad = await builder.create_use_case(ALICE, body(repo="owner/.."))
    assert isinstance(bad, ParamErrors)
    unknown = await builder.create_use_case(
        ALICE, CreateUseCase(template="nope", name="n", instruction="i", params={})
    )
    assert unknown == UnknownTemplate("nope")
    assert (await builder.list_use_cases()).use_cases == []


async def test_the_run_spec_snapshots_the_current_version(builder: Builder):
    result = await created(builder)
    spec = await builder.run_spec_for(UseCaseId(result.use_case_id))
    assert spec is not None
    assert (spec.use_case_id, spec.use_case_version, spec.use_case_name) == (
        result.use_case_id,
        1,
        "LangGraph releases",
    )
    assert (spec.owner, spec.workflow, spec.instruction) == ("alice", "release_check", INSTRUCTION)
    assert spec.task == ReleaseTask("langchain-ai/langgraph", TAG_PATTERN, None)
    assert spec.bindings == {"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})}
    assert [step.label for step in spec.approval_policy.steps] == ["Team approver"]
    assert spec.approval_policy.steps[0].eligible == AnyApprover()


@pytest.mark.parametrize(
    ("carried", "seen", "expected"),
    [
        ("1.2.16", "1.2.14", "1.2.16"),
        (None, "1.2.14", "1.2.14"),
        (None, None, None),
    ],
)
async def test_the_watermark_is_the_last_succeeded_run_else_the_saved_start(
    builder: Builder, runs: FakeRuns, carried: str | None, seen: str | None, expected: str | None
):
    runs.carry_forward = carried
    result = await created(builder, **({"last_seen_tag": seen} if seen else {}))
    spec = await builder.run_spec_for(UseCaseId(result.use_case_id))
    assert spec is not None
    assert isinstance(spec.task, ReleaseTask)
    assert spec.task.last_known_tag == expected


async def test_start_run_hands_the_spec_principal_and_key_to_the_starter(
    builder: Builder, runs: FakeRuns
):
    result = await created(builder)
    started = await builder.start_run(UseCaseId(result.use_case_id), ALICE, "key-1")
    assert started == RunStarted(RunId("run_1"), created=True)
    [(spec, principal, key)] = runs.started
    assert (spec.use_case_id, principal, key) == (result.use_case_id, ALICE, "key-1")


async def test_start_run_on_a_missing_use_case_starts_nothing(builder: Builder, runs: FakeRuns):
    assert await builder.start_run(UseCaseId("uc_nope"), ALICE, "k") is None
    assert runs.started == []
