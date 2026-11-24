"""Scenarios (ADR 0054, section 5). Code reads a version's plan, picks the kinds of scenario that
apply, builds one from a template for each, checks any scenario against the plan, and stages it
for the simulation: what the gateway answers each of our blocks, what mock GitHub serves, and the
output pinned for each block with no mock. No model is used here."""

import secrets
from collections.abc import Sequence
from typing import Any

import pytest

from platform_api.orchestration.mock_setup import MockSetup, mock_keys, plan_copy
from platform_api.orchestration.recorded_samples import ALLOW_LISTS, MADE_UP, RecordedSamples, vary
from platform_api.orchestration.scenarios import (
    KINDS,
    SAMPLE_CHANGE,
    SAMPLE_REPLY,
    GitHubPlay,
    NotTried,
    ScenarioKind,
    ScenarioSpec,
    SimulationPlan,
    check,
    check_all,
    kinds_that_apply,
    plan_of,
    stage,
    templates,
)

START = "Start from the Portal"
GITHUB_URL = "http://mock-github:8200"
SLACK_TOKEN = secrets.token_hex(16)
PROPOSE = {
    "action": "jira.create_ticket",
    "place": "MOCK",
    "title": "Upgrade LangGraph",
    "body": "A new release is out.",
    "subject": "langgraph",
}
EXITS = ("No answer", "Make the approved changes", "Declined", "Nothing to change")
HOW_PINNED = "Its output is pinned, so a simulation can't play it as {how}."


def block(name: str, node_type: str, version: float = 1, **parameters: Any) -> dict[str, Any]:
    return {
        "id": f"id-{name}",
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "position": [0, 0],
        "parameters": parameters,
    }


def ours(name: str, kind: str, **parameters: Any) -> dict[str, Any]:
    return block(name, f"CUSTOM.wab{kind}", **parameters)


def our_read(name: str = "Read releases") -> dict[str, Any]:
    return ours(name, "Read", source="github_releases", place="langchain-ai/langgraph")


def github_read(name: str = "GitHub releases") -> dict[str, Any]:
    made = block(
        name,
        "n8n-nodes-base.github",
        1.1,
        resource="release",
        operation="getAll",
        owner="langchain-ai",
        repository="langgraph",
        returnAll=False,
        limit=3,
    )
    made["credentials"] = {"githubApi": {"id": "wab-github-read", "name": "The platform's key"}}
    return made


def jira_read(name: str = "Read the issue") -> dict[str, Any]:
    return block(name, "n8n-nodes-base.jira", resource="issue", operation="get", issueKey="SUP-1")


def tidy(name: str = "Tidy") -> dict[str, Any]:
    return block(name, "n8n-nodes-base.set", 3.4)


def release_check(
    reads: Sequence[dict[str, Any]] | None = None,
    *,
    propose: bool = True,
    ask: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    """A release check as the Planner lays one out: the reads in a line, then Compare, Propose a
    change, Ask for a yes, and on Yes Make the approved changes and Tell. Each other exit of Ask
    for a yes ends at a block of its own."""
    line = [ours(START, "StartFromPortal"), *([our_read()] if reads is None else reads)]
    inputs = {"input": [{"name": "release", "value": "={{ $json.id }}"}]}
    line.append(ours("Compare", "Agent", agent="release_checker", inputs=inputs))
    if propose:
        line.append(ours("Propose a change", "ProposeChange", **PROPOSE))
    nodes = list(line)
    edges: dict[str, Any] = {a["name"]: to(b["name"]) for a, b in zip(line, line[1:], strict=False)}
    if ask:
        nodes.append(ours("Ask for a yes", "AskForYes"))
        edges[line[-1]["name"]] = to("Ask for a yes")
        exits = [*EXITS] if write else [EXITS[0], "Done", *EXITS[2:]]
        edges["Ask for a yes"] = {
            "main": [[{"node": e, "type": "main", "index": 0}] for e in exits]
        }
        nodes += [block(e, "n8n-nodes-base.noOp") for e in exits if e != EXITS[1]]
        if write:
            nodes.append(ours(EXITS[1], "MakeApprovedChanges"))
            nodes.append(ours("Tell", "Tell", where="channel", what="result"))
            edges[EXITS[1]] = to("Tell")
    return {"name": "Release check", "nodes": nodes, "connections": edges, "settings": {}}


def to(target: str) -> dict[str, Any]:
    return {"main": [[{"node": target, "type": "main", "index": 0}]]}


def planned(version: dict[str, Any]) -> SimulationPlan:
    setup = plan_copy(version, mock_keys(GITHUB_URL, None, SLACK_TOKEN), {})
    assert isinstance(setup, MockSetup), setup
    plan = plan_of(version, setup.blocks)
    assert isinstance(plan, SimulationPlan), plan
    return plan


def spec(kind: ScenarioKind, **given: Any) -> ScenarioSpec:
    return ScenarioSpec.model_validate({"kind": kind, **given})


def by_kind(plan: SimulationPlan, samples: RecordedSamples) -> dict[ScenarioKind, ScenarioSpec]:
    return {made.kind: made for made in templates(plan, samples)}


# The plan


def test_the_plan_gives_each_block_its_role_its_mode_and_what_it_reads() -> None:
    plan = planned(release_check([our_read(), github_read(), jira_read(), tidy()]))
    assert {b.name: (b.role, b.mode, b.answer) for b in plan.blocks} == {
        START: ("start", "ours", None),
        "Read releases": ("read", "ours", "read.release"),
        "GitHub releases": ("read", "mock", "github.release"),
        "Read the issue": ("read", "pinned", "jira.issue"),
        "Tidy": ("other", "runs", None),
        "Compare": ("agent", "ours", None),
        "Propose a change": ("propose", "ours", None),
        "Ask for a yes": ("ask", "ours", None),
        "No answer": ("other", "runs", None),
        "Declined": ("other", "runs", None),
        "Nothing to change": ("other", "runs", None),
        "Make the approved changes": ("write", "ours", None),
        "Tell": ("tell", "ours", None),
    }


def test_a_block_after_a_write_is_one_a_simulation_never_runs() -> None:
    """The gateway refuses every write, and the refusal ends the run (ADR 0054, PR 3)."""
    assert planned(release_check()).after_write == frozenset({"Tell"})
    assert planned(release_check(write=False)).after_write == frozenset()


def test_a_version_with_no_start_from_the_portal_is_refused_in_words() -> None:
    version = release_check()
    version["nodes"] = [n for n in version["nodes"] if n["name"] != START]
    setup = plan_copy(version, mock_keys(GITHUB_URL, None, None), {})
    assert isinstance(setup, MockSetup)
    assert plan_of(version, setup.blocks) == (
        "A simulation starts a version from Start from the Portal, and this one has none."
    )


# Which kinds apply


def test_every_kind_applies_to_a_release_check() -> None:
    assert kinds_that_apply(planned(release_check())) == KINDS


def test_a_version_with_no_ask_for_a_yes_gets_no_approver_says_no() -> None:
    kinds = kinds_that_apply(planned(release_check(ask=False, write=False)))
    assert "approver_says_no" not in kinds
    assert len(kinds) == len(KINDS) - 1


def test_a_version_with_no_outside_read_gets_only_the_happy_path_and_the_no() -> None:
    assert kinds_that_apply(planned(release_check([]))) == ("happy_path", "approver_says_no")


# The templates


def test_the_templates_give_one_scenario_for_each_kind_that_applies() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    made = templates(plan, samples)
    assert [s.kind for s in made] == list(KINDS)
    assert [s.name for s in made] == list(KINDS)
    assert check_all(made, plan, samples) == ()
    plays = {s.kind: s.reads["Read releases"] for s in made}
    recorded = MADE_UP["read.release"].id
    assert {k: (p.serve, p.sample, p.vary) for k, p in plays.items()} == {
        "happy_path": ("recorded", recorded, []),
        "nothing_new": ("empty", None, []),
        "source_not_found": ("not_found", None, []),
        "timeout": ("too_slow", None, []),
        "approver_says_no": ("recorded", recorded, []),
        "odd_data": ("varied", recorded, list(ALLOW_LISTS["read.release"].varies)),
    }


def test_a_template_serves_a_blocks_own_recorded_sample_first() -> None:
    samples = RecordedSamples()
    release = {"kind": "release", "id": "0.9.1", "name": "0.9.1", "published_at": "2026-11-01"}
    own = samples.record("read.release", [release], "real_run", block="Read releases")
    made = by_kind(planned(release_check()), samples)
    assert made["happy_path"].reads["Read releases"].sample == own.id


def test_the_agent_proposes_a_change_only_where_no_block_proposes_one() -> None:
    made = by_kind(planned(release_check()), RecordedSamples())
    assert made["happy_path"].agents["Compare"].items == [SAMPLE_REPLY]
    assert made["happy_path"].agents["Compare"].proposes == []
    assert made["nothing_new"].agents["Compare"].items == []
    alone = by_kind(planned(release_check(propose=False)), RecordedSamples())
    assert alone["happy_path"].agents["Compare"].proposes == [SAMPLE_CHANGE]
    assert alone["nothing_new"].agents["Compare"].proposes == []


def test_a_pinned_read_is_never_played_as_not_found_or_too_slow() -> None:
    made = by_kind(planned(release_check([jira_read(), our_read()])), RecordedSamples())
    assert made["source_not_found"].reads["Read the issue"].serve == "recorded"
    assert made["source_not_found"].reads["Read releases"].serve == "not_found"
    assert made["nothing_new"].reads["Read the issue"].serve == "empty"


# The check: a scenario can't add a block, a system or a sample


@pytest.mark.parametrize(
    ("given", "problem"),
    [
        (
            spec("happy_path", reads={"Nowhere": {"serve": "recorded"}}),
            'The version has no block "Nowhere" that reads a source.',
        ),
        (
            spec("happy_path", reads={"Compare": {"serve": "recorded"}}),
            'The version has no block "Compare" that reads a source.',
        ),
        (
            spec("happy_path", agents={"Propose a change": {}}),
            'The version has no Agent block "Propose a change".',
        ),
        (
            spec("happy_path", reads={"Read releases": {"serve": "recorded", "sample": "nope"}}),
            'There is no recorded sample "nope".',
        ),
        (
            spec(
                "happy_path",
                reads={"Read releases": {"serve": "recorded", "sample": "made_up.read.page"}},
            ),
            'The sample "made_up.read.page" is not what "Read releases" reads.',
        ),
        (
            spec("odd_data", reads={"Read releases": {"serve": "varied"}}),
            '"Read releases" is varied, so it names how to vary it.',
        ),
        (
            spec("happy_path", reads={"Read releases": {"serve": "recorded", "vary": ["suffix"]}}),
            '"Read releases" is not varied, so it names no way to vary it.',
        ),
        (
            spec(
                "odd_data",
                reads={"Read releases": {"serve": "varied", "vary": ["suffix", "suffix"]}},
            ),
            '"Read releases" names "suffix" twice.',
        ),
        (
            spec("nothing_new", reads={"Read releases": {"serve": "recorded"}}),
            '"Nothing new" serves every read empty.',
        ),
        (
            spec("source_not_found", reads={"Read releases": {"serve": "recorded"}}),
            '"Source not found" plays at least one read as not found, and serves every other '
            "as recorded.",
        ),
        (
            spec("timeout", reads={"Read releases": {"serve": "not_found"}}),
            '"Timeout" plays at least one read as too slow, and serves every other as recorded.',
        ),
        (
            spec("happy_path", reads={"Read releases": {"serve": "empty"}}),
            '"Happy path" serves every read as recorded.',
        ),
        (
            spec("approver_says_no", reads={"Read releases": {"serve": "too_slow"}}),
            '"Approver says no" serves every read as recorded.',
        ),
        (
            spec("odd_data", reads={"Read releases": {"serve": "empty"}}),
            '"Odd data" varies at least one read, and serves every other as recorded.',
        ),
        (
            spec("happy_path", agents={"Compare": {"serve": "too_slow"}}),
            'Only "Timeout" plays an agent as too slow.',
        ),
    ],
)
def test_a_scenario_that_does_not_fit_the_version_is_refused_in_words(
    given: ScenarioSpec, problem: str
) -> None:
    assert check(given, planned(release_check()), RecordedSamples()) == (problem,)


def test_a_variation_the_sample_has_no_field_for_is_refused() -> None:
    version = release_check([ours("Read the page", "Read", source="confluence_page", place="1")])
    plan = planned(version)
    given = spec("odd_data", reads={"Read the page": {"serve": "varied", "vary": ["suffix"]}})
    assert check(given, plan, RecordedSamples()) == (
        'A Confluence page has no version to vary with "suffix".',
    )


def test_a_kind_that_does_not_apply_is_refused() -> None:
    no_ask = planned(release_check(ask=False, write=False))
    assert check(spec("approver_says_no"), no_ask, RecordedSamples()) == (
        '"Approver says no" needs an Ask for a yes block, and this version has none.',
    )
    no_read = planned(release_check([]))
    assert check(spec("timeout"), no_read, RecordedSamples()) == (
        '"Timeout" needs a block that reads a source, and this version has none.',
    )


def test_two_blocks_that_read_mock_github_get_one_answer() -> None:
    plan = planned(release_check([github_read("First"), github_read("Second")]))
    given = spec(
        "source_not_found",
        reads={"First": {"serve": "not_found"}, "Second": {"serve": "recorded"}},
    )
    assert check(given, plan, RecordedSamples()) == (
        "Blocks that read mock GitHub get one answer in a scenario.",
    )


def test_every_problem_names_its_scenario_and_names_are_kept_apart() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    bad = spec("happy_path", name="first", reads={"Nowhere": {"serve": "recorded"}})
    again = spec("nothing_new", name="first")
    assert check_all([bad, again], plan, samples) == (
        'first: The version has no block "Nowhere" that reads a source.',
        'Two scenarios are named "first".',
    )


def test_a_read_a_scenario_leaves_out_is_served_as_recorded() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    staged = stage(spec("happy_path"), plan, samples)
    assert staged.gateway.blocks["Read releases"].items == list(MADE_UP["read.release"].items)
    assert staged.gateway.blocks["Compare"].items == [SAMPLE_REPLY]


# Staging: what the gateway, mock GitHub and the pins get


def test_our_read_is_answered_from_the_scenario_by_the_gateway() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    staged = {k: stage(s, plan, samples) for k, s in by_kind(plan, samples).items()}
    read = {k: s.gateway.blocks["Read releases"] for k, s in staged.items()}
    recorded = list(MADE_UP["read.release"].items)
    varied = vary(MADE_UP["read.release"].items, "read.release", ALLOW_LISTS["read.release"].varies)
    assert isinstance(varied, tuple)
    assert {k: (a.serve, a.items) for k, a in read.items()} == {
        "happy_path": ("recorded", recorded),
        "nothing_new": ("recorded", []),
        "source_not_found": ("not_found", []),
        "timeout": ("timeout", []),
        "approver_says_no": ("recorded", recorded),
        "odd_data": ("recorded", list(varied)),
    }
    assert {k: s.gateway.approver for k, s in staged.items()} == {
        k: "no" if k == "approver_says_no" else "yes" for k in KINDS
    }
    assert all(s.github is None and s.pins == {} and s.runs for s in staged.values())
    assert {k: s.gateway.name for k, s in staged.items()} == {k: k for k in KINDS}


def test_mock_github_serves_each_scenario_or_plays_its_failure() -> None:
    plan, samples = planned(release_check([github_read()])), RecordedSamples()
    staged = {k: stage(s, plan, samples) for k, s in by_kind(plan, samples).items()}
    releases = MADE_UP["github.release"].items
    varied = vary(releases, "github.release", ALLOW_LISTS["github.release"].varies)
    assert isinstance(varied, tuple)
    assert {k: s.github for k, s in staged.items()} == {
        "happy_path": GitHubPlay("ok", releases),
        "nothing_new": GitHubPlay("ok", ()),
        "source_not_found": GitHubPlay("not_found", None),
        "timeout": GitHubPlay("drop", None),
        "approver_says_no": GitHubPlay("ok", releases),
        "odd_data": GitHubPlay("ok", varied),
    }
    assert all("GitHub releases" not in s.gateway.blocks for s in staged.values())


def test_a_pinned_read_gets_its_sample_as_its_pin_and_is_not_tried_as_a_failure() -> None:
    plan, samples = planned(release_check([jira_read(), our_read()])), RecordedSamples()
    staged = {k: stage(s, plan, samples) for k, s in by_kind(plan, samples).items()}
    issue = list(MADE_UP["jira.issue"].items)
    varied = vary(MADE_UP["jira.issue"].items, "jira.issue", ALLOW_LISTS["jira.issue"].varies)
    assert isinstance(varied, tuple)
    assert {k: s.pins for k, s in staged.items()} == {
        "happy_path": {"Read the issue": issue},
        "nothing_new": {"Read the issue": []},
        "source_not_found": {"Read the issue": issue},
        "timeout": {"Read the issue": issue},
        "approver_says_no": {"Read the issue": issue},
        "odd_data": {"Read the issue": list(varied)},
    }
    assert staged["source_not_found"].not_tried == (
        NotTried("Read the issue", HOW_PINNED.format(how="not found")),
    )
    assert staged["timeout"].not_tried == (
        NotTried("Read the issue", HOW_PINNED.format(how="too slow")),
    )
    assert staged["happy_path"].not_tried == ()
    assert all(s.runs for s in staged.values()), "our Read plays every kind"


def test_a_scenario_no_block_can_play_is_staged_not_to_run() -> None:
    plan, samples = planned(release_check([jira_read()])), RecordedSamples()
    staged = {k: stage(s, plan, samples) for k, s in by_kind(plan, samples).items()}
    assert {k for k, s in staged.items() if not s.runs} == {"source_not_found", "timeout"}


def test_an_agent_that_is_too_slow_is_answered_as_timed_out() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    given = spec(
        "timeout",
        reads={"Read releases": {"serve": "too_slow"}},
        agents={"Compare": {"serve": "too_slow"}},
    )
    assert check(given, plan, samples) == ()
    assert stage(given, plan, samples).gateway.blocks["Compare"].serve == "timeout"


def test_a_given_sample_is_scrubbed_before_a_scenario_serves_it() -> None:
    """The store scrubs on the way in, so a scenario only ever serves what the allow list keeps."""
    samples = RecordedSamples()
    who = f"person.{secrets.token_hex(4)}@example.com"
    kept = samples.record(
        "read.release",
        [{"kind": "release", "id": "1.0.1", "name": who, "published_at": "2026-11-01", "by": who}],
        "real_run",
    )
    staged = stage(
        spec("happy_path", reads={"Read releases": {"serve": "recorded", "sample": kept.id}}),
        planned(release_check()),
        samples,
    )
    assert who not in staged.gateway.model_dump_json()
