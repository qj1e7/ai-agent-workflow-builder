"""The scenario writer and the explainer as a simulation's driver asks them (ADR 0054, PR 6). Each is
off unless a caller asks, and needs a connected model. The writer's picks become scenarios in PR 5's
schema, and the gateway checks them with PR 5's own check, running code's templates on any refusal.
The explainer's picks are checked again here, and code writes the sentence. The grade stays the
verdict."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    FailureNote,
    ModelAccess,
    ModelProblem,
    ScenarioExplainRequest,
    ScenarioExplainResult,
    ScenariosExplained,
    ScenariosKept,
    ScenariosWritten,
    ScenarioWriteRequest,
    ScenarioWriteResult,
)
from platform_api.orchestration.recorded_samples import RecordedSamples
from platform_api.orchestration.scenarios import ScenarioSpec, check_all
from platform_api.orchestration.simulation_gateway import (
    PlanOut,
    PlayOut,
    ResultOut,
    plan_out,
)
from platform_api.orchestration.simulation_model import (
    EXPLAIN_SECONDS,
    WRITE_SECONDS,
    SimulationModel,
    note_words,
    specs_of,
)
from tests.test_scenarios import START, jira_read, our_read, planned, release_check

pytestmark = pytest.mark.anyio

ACCESS = ModelAccess(
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    model="claude-sonnet-5-5",
    api_key="sk-" + "example-key-not-real-q4",
)
READ = "Read releases"
WRITTEN = ScenariosWritten.model_validate(
    {
        "scenarios": [
            {"kind": "happy_path", "reads": [{"block": READ, "serve": "recorded"}]},
            {"kind": "nothing_new", "reads": [{"block": READ, "serve": "empty"}]},
            {"kind": "source_not_found", "reads": [{"block": READ, "serve": "not_found"}]},
            {
                "kind": "timeout",
                "reads": [{"block": READ, "serve": "too_slow"}],
                "slow_agents": ["Compare"],
            },
            {"kind": "approver_says_no"},
            {
                "kind": "odd_data",
                "reads": [
                    {
                        "block": READ,
                        "serve": "varied",
                        "sample": "made_up.read.release",
                        "vary": ["suffix"],
                    }
                ],
            },
        ]
    }
)


@dataclass
class FakeAgents:
    """The agent runtime's two simulation routes."""

    write_answer: ScenarioWriteResult | AgentUnavailable | AgentRejected = WRITTEN
    explain_answer: ScenarioExplainResult | AgentUnavailable | AgentRejected = field(
        default_factory=lambda: ScenariosExplained(notes=[], kept=[])
    )
    written: list[ScenarioWriteRequest] = field(default_factory=list[ScenarioWriteRequest])
    explained: list[ScenarioExplainRequest] = field(default_factory=list[ScenarioExplainRequest])

    async def write_scenarios(
        self, request: ScenarioWriteRequest
    ) -> ScenarioWriteResult | AgentUnavailable | AgentRejected:
        self.written.append(request)
        return self.write_answer

    async def explain_scenarios(
        self, request: ScenarioExplainRequest
    ) -> ScenarioExplainResult | AgentUnavailable | AgentRejected:
        self.explained.append(request)
        return self.explain_answer


def model_for(agents: FakeAgents, access: ModelAccess | None = ACCESS) -> SimulationModel:
    async def connected() -> ModelAccess | None:
        return access

    return SimulationModel(agents, connected)


def the_plan(version: dict[str, Any] | None = None) -> PlanOut:
    return plan_out(planned(version or release_check()), RecordedSamples())


# The writer


async def test_without_a_model_nothing_is_asked_and_the_templates_run() -> None:
    agents = FakeAgents()
    assert await model_for(agents, None).write(the_plan()) is None
    assert agents.written == []


async def test_the_writers_picks_become_scenarios_in_pr_5s_schema() -> None:
    agents = FakeAgents()
    specs = await model_for(agents).write(the_plan())
    assert specs == specs_of(WRITTEN)
    assert specs is not None
    assert [s.name for s in specs] == [s.kind for s in WRITTEN.scenarios]
    assert specs[3] == ScenarioSpec.model_validate(
        {
            "kind": "timeout",
            "name": "timeout",
            "reads": {READ: {"serve": "too_slow"}},
            "agents": {"Compare": {"serve": "too_slow"}},
        }
    )
    plan, samples = planned(release_check()), RecordedSamples()
    assert check_all(specs, plan, samples) == (), "PR 5's own check takes them"


@pytest.mark.parametrize(
    "answer",
    [
        ScenariosKept(why="not_a_read"),
        ModelProblem(reason="failed", message="No AI model is connected."),
        AgentUnavailable("The agent runtime did not answer: ReadTimeout"),
        AgentRejected("The agent runtime refused the request (422)"),
    ],
    ids=["kept", "problem", "unavailable", "rejected"],
)
async def test_any_answer_but_written_scenarios_runs_the_templates(answer: Any) -> None:
    assert await model_for(FakeAgents(write_answer=answer)).write(the_plan()) is None


async def test_the_writer_is_offered_only_the_plans_own_facts_within_its_bounds() -> None:
    agents = FakeAgents()
    samples = RecordedSamples()
    for n in range(25):
        items = [{"kind": "release", "id": f"1.{n}.{i}"} for i in range(5)]
        samples.record("read.release", items, "real_run", block=READ)
    plan = plan_out(planned(release_check([our_read(), jira_read()])), samples)
    await model_for(agents).write(plan)
    (asked,) = agents.written
    assert asked.model == ACCESS and asked.within_seconds == WRITE_SECONDS
    assert [b.name for b in asked.blocks] == [b.name for b in plan.blocks]
    assert asked.kinds == plan.kinds
    assert len(asked.samples) == 20
    assert {len(s.items) for s in asked.samples} <= {1, 2, 3}
    reads = {b.name: b for b in asked.blocks if b.role == "read"}
    assert reads["Read the issue"].plays == ["recorded", "varied", "empty"]


# The explainer

ODD = ResultOut(
    name="odd_data",
    kind="odd_data",
    verdict="failed",
    expected="It ends in one of the cases above, never in a failure with no reason.",
    happened='It failed at "Compare", which is not a stop with a reason: Cannot read '
    "properties of undefined (reading 'tag_name')",
    ran=[START, READ, "Compare"],
    not_tried=[],
    ending="failed",
    stopped_at="Compare",
    plays=[PlayOut(block=READ, serve="varied", vary=["suffix"])],
)
NOTHING_NEW = ResultOut(
    name="nothing_new",
    kind="nothing_new",
    verdict="failed",
    expected="It ends as Nothing new and proposes nothing.",
    happened="It reached the yes with 1 change proposed.",
    ran=[START, READ, "Compare", "Propose a change", "Ask for a yes"],
    not_tried=[],
    ending="reached_yes",
    stopped_at=None,
    plays=[PlayOut(block=READ, serve="empty")],
)
PASSED = ResultOut(
    name="happy_path",
    kind="happy_path",
    verdict="passed",
    expected="It reaches the yes with the expected change.",
    happened="It reached the yes and would have made 1 change, which the simulation refused.",
    ran=[START, READ],
    not_tried=[],
    ending="reached_yes",
    stopped_at=None,
    plays=[],
)


def note(**fields: Any) -> FailureNote:
    return FailureNote.model_validate({"source": None, "detail": None, **fields})


ODD_NOTE = note(
    scenario="odd_data", block="Compare", kind="stopped", source=READ, detail="tag_name"
)
NEW_NOTE = note(scenario="nothing_new", block="Compare", kind="went_on", source=READ)


async def test_each_failed_scenario_gets_one_plain_sentence_code_writes() -> None:
    agents = FakeAgents(explain_answer=ScenariosExplained(notes=[ODD_NOTE, NEW_NOTE], kept=[]))
    said = await model_for(agents).explain([PASSED, ODD, NOTHING_NEW])
    assert said == {
        "odd_data": '"Compare" stopped the run with no reason people can act on when "Read '
        'releases" gave a version with a suffix. The records name tag_name.',
        "nothing_new": '"Compare" let the run go on when "Read releases" found nothing new.',
    }
    (asked,) = agents.explained
    assert [f.name for f in asked.failed] == ["odd_data", "nothing_new"]
    assert asked.within_seconds == EXPLAIN_SECONDS and asked.model == ACCESS


async def test_nothing_is_asked_without_a_model_or_without_a_failure() -> None:
    agents = FakeAgents()
    assert await model_for(agents, None).explain([ODD]) == {}
    assert await model_for(agents).explain([PASSED]) == {}
    assert agents.explained == []


@pytest.mark.parametrize(
    "picked",
    [
        note(scenario="happy_path", block="Compare", kind="stopped"),
        note(scenario="odd_data", block="Ask for a yes", kind="stopped"),
        note(scenario="odd_data", block="Compare", kind="stopped", source="Compare"),
    ],
    ids=["a-scenario-that-passed", "a-block-that-did-not-run", "a-source-not-played"],
)
async def test_a_note_outside_its_scenarios_facts_is_left_out_here_too(picked: FailureNote) -> None:
    agents = FakeAgents(explain_answer=ScenariosExplained(notes=[picked], kept=[]))
    assert await model_for(agents).explain([PASSED, ODD]) == {}


@pytest.mark.parametrize(
    "answer",
    [
        ModelProblem(reason="failed", message="No AI model is connected."),
        AgentUnavailable("The agent runtime did not answer: ReadTimeout"),
    ],
    ids=["problem", "unavailable"],
)
async def test_an_answer_with_no_notes_leaves_only_codes_own_words(answer: Any) -> None:
    assert await model_for(FakeAgents(explain_answer=answer)).explain([ODD]) == {}


async def test_the_explainer_is_sent_each_failure_within_its_bounds() -> None:
    long = ODD.model_copy(update={"happened": "x" * 5000, "ran": [f"B{n}" for n in range(150)]})
    many = [long.model_copy(update={"name": f"odd_{n}"}) for n in range(25)]
    agents = FakeAgents()
    await model_for(agents).explain(many)
    (asked,) = agents.explained
    assert len(asked.failed) == 20
    assert {len(f.happened) for f in asked.failed} == {2000}
    assert {len(f.ran) for f in asked.failed} == {100}


@pytest.mark.parametrize(
    ("kind", "plays", "said"),
    [
        ("stopped", [], '"Compare" stopped the run with no reason people can act on.'),
        ("went_on", [], '"Compare" let the run go on.'),
        ("ended_early", [], '"Compare" ended the run before the yes.'),
        ("changes", [], '"Compare" asked for other changes than expected.'),
        ("no_end", [], '"Compare" kept the run from ending.'),
        ("unknown", [], 'Something went wrong at "Compare".'),
        (
            "unknown",
            [PlayOut(block=READ, serve="varied", vary=["suffix", "empty_field", "long_text"])],
            'Something went wrong at "Compare" when "Read releases" gave a version with a '
            "suffix, an empty field and very long text.",
        ),
        (
            "unknown",
            [PlayOut(block=READ, serve="not_found")],
            'Something went wrong at "Compare" when "Read releases" could not find its source.',
        ),
        (
            "unknown",
            [PlayOut(block=READ, serve="too_slow")],
            'Something went wrong at "Compare" when "Read releases" did not answer in time.',
        ),
    ],
)
def test_code_writes_each_sentence_from_the_picks(
    kind: str, plays: Sequence[PlayOut], said: str
) -> None:
    source = plays[0].block if plays else None
    picked = note(scenario="odd_data", block="Compare", kind=kind, source=source)
    assert note_words(picked, plays) == said
