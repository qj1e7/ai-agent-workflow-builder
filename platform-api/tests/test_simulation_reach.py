"""What a fix's simulation needs of the gateway (ADR 0055, PR 5).

A play can name places that are gone: the read answers not found there, and as the play says at
any other place. So a scenario can replay a stop at a renamed source. And each simulated run says
what it reached, read from the gateway's record of our blocks' calls and n8n's record of its own
blocks, beside the systems the version names, so code can find a system a fix reaches at run time
that the stopped version never reached."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from platform_api.orchestration.n8n import ExecutionRecord, NodeError, NodeRun, node_runs
from platform_api.orchestration.reach import named, reached
from platform_api.orchestration.recorded_samples import MADE_UP, RecordedSamples
from platform_api.orchestration.scenarios import GitHubPlay, ScenarioSpec, check, stage
from platform_api.orchestration.simulated_calls import CallRecord, MockGitHub, SimulatedRun
from platform_api.orchestration.simulations import Simulation
from tests.test_scenarios import (
    github_read,
    jira_read,
    our_read,
    ours,
    planned,
    release_check,
    spec,
)
from tests.test_simulations import Stack, verdicts

GONE = "langchain-ai/langgraph"
RENAMED = "langchain-ai/langgraph-renamed"
REPLAY = "replay_the_stop"


def replay(block: str, places: tuple[str, ...] = (GONE,)) -> dict[str, Any]:
    return {
        "kind": "happy_path",
        "name": REPLAY,
        "reads": {block: {"serve": "recorded", "gone": list(places)}},
    }


def our_read_at(place: str) -> dict[str, Any]:
    return ours("Read releases", "Read", source="github_releases", place=place)


def github_read_at(owner: str, repository: str) -> dict[str, Any]:
    made = github_read()
    made["parameters"] |= {"owner": owner, "repository": repository}
    return made


@pytest.fixture
def stack() -> Stack:
    return Stack()


# Gone places


def test_a_play_may_name_gone_places_on_a_read_that_can_be_not_found() -> None:
    plan, samples = planned(release_check([our_read(), jira_read()])), RecordedSamples()
    ours_gone = {"Read releases": {"serve": "recorded", "gone": [GONE]}}
    assert check(spec("happy_path", reads=ours_gone), plan, samples) == ()
    github = planned(release_check([github_read()]))
    github_gone = {"GitHub releases": {"serve": "recorded", "gone": [GONE]}}
    assert check(spec("happy_path", reads=github_gone), github, samples) == ()
    pinned = {"Read the issue": {"serve": "recorded", "gone": ["SUP"]}}
    assert check(spec("happy_path", reads=pinned), plan, samples) == (
        '"Read the issue" names places that are gone, but its output is pinned, so a '
        "simulation can't play it as not found.",
    )


def test_only_a_read_served_as_recorded_or_varied_names_gone_places() -> None:
    plan, samples = planned(release_check()), RecordedSamples()
    empty = {"Read releases": {"serve": "empty", "gone": [GONE]}}
    assert check(spec("nothing_new", reads=empty), plan, samples) == (
        '"Read releases" names places that are gone, so it is served as recorded or varied.',
    )


def test_gone_places_are_staged_for_our_read_and_for_mock_github() -> None:
    samples = RecordedSamples()
    plan = planned(release_check())
    staged = stage(ScenarioSpec.model_validate(replay("Read releases")), plan, samples)
    assert staged.gateway.blocks["Read releases"].gone == [GONE]
    assert staged.runs
    github = planned(release_check([github_read()]))
    staged = stage(ScenarioSpec.model_validate(replay("GitHub releases")), github, samples)
    releases = MADE_UP["github.release"].items
    assert staged.github == GitHubPlay("ok", releases, (GONE,))


@pytest.mark.anyio
async def test_a_replay_of_a_renamed_source_fails_the_stopped_version_and_passes_the_fix(
    stack: Stack,
) -> None:
    stopped = release_check([our_read_at(GONE)])
    fixed = release_check([our_read_at(RENAMED)])
    assert verdicts(await stack.simulate(stopped, [replay("Read releases")])) == {REPLAY: "failed"}
    assert verdicts(await stack.simulate(fixed, [replay("Read releases")])) == {REPLAY: "passed"}


@pytest.mark.anyio
async def test_mock_github_replays_a_renamed_repository_too(stack: Stack) -> None:
    stopped = release_check([github_read_at("langchain-ai", "langgraph")])
    fixed = release_check([github_read_at("langchain-ai", "langgraph-renamed")])
    assert verdicts(await stack.simulate(stopped, [replay("GitHub releases")])) == {
        REPLAY: "failed"
    }
    assert verdicts(await stack.simulate(fixed, [replay("GitHub releases")])) == {REPLAY: "passed"}


@pytest.mark.anyio
async def test_mock_github_answers_not_found_only_at_the_gone_repositories() -> None:
    posted: list[tuple[str, Any]] = []

    def github(request: httpx.Request) -> httpx.Response:
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(github))
    mock = MockGitHub("http://mock-github:8200", client)
    await mock.play(GitHubPlay("ok", None, (GONE,)))
    await mock.play(None)
    await client.aclose()
    assert posted == [
        ("/_admin/mode", {"mode": "ok"}),
        ("/_admin/releases", {"releases": None}),
        ("/_admin/mode", {"mode": "not_found", "repo": GONE}),
        ("/_admin/mode", {"mode": "ok"}),
        ("/_admin/releases", {"releases": None}),
    ]


# What each run reached


@pytest.mark.anyio
async def test_each_run_names_what_it_reached_and_the_simulation_what_the_version_names(
    stack: Stack,
) -> None:
    simulation = await stack.simulate(release_check([github_read()]))
    assert isinstance(simulation, Simulation)
    by_name = {r.name: r.reached for r in simulation.results}
    assert by_name["happy_path"] == (
        "agent:release_checker",
        "mock:github",
        "propose:jira.create_ticket",
    )
    assert by_name["source_not_found"] == ("mock:github",)
    assert simulation.named == (
        "agent:release_checker",
        "mock:github",
        "outbound:GitHub releases@n8n-nodes-base.github",
        "propose:jira.create_ticket",
        "tell:channel",
    )
    assert not any(word.startswith("unknown:") for r in simulation.results for word in r.reached)


def _run(*calls: tuple[str, str, dict[str, Any]]) -> SimulatedRun:
    at = datetime(2026, 11, 25, tzinfo=UTC)
    return SimulatedRun(
        nonce="n",
        workflow_id="w",
        scenario="happy_path",
        issued_at=at,
        calls=[
            CallRecord(
                at=at,
                execution_id="1",
                block=block,
                kind=kind,  # type: ignore[arg-type]
                asked=asked,
                outcome="answered",
                status=200,
            )
            for block, kind, asked in calls
        ],
    )


def _ended(
    error: str | None = None,
    ran: dict[str, str] | None = None,
    nodes: dict[str, NodeRun] | None = None,
) -> ExecutionRecord:
    """n8n's record, with each block's last try. Unless a test gives them, each try holds no
    error."""
    ran = ran or {}
    tries = {name: NodeRun(state) for name, state in ran.items()} if nodes is None else nodes
    return ExecutionRecord(
        "1", "w", "error", "manual", None, "v1", "n", None, error, ran, None, tries
    )


def test_a_system_an_expression_picks_is_reached_but_never_named() -> None:
    """The scope check reads each block on its own. A value changed upstream that our Read reads
    as its source is found only when the run calls the gateway."""
    picked = ours("Read releases", "Read", source="={{ $json.source }}", place=GONE)
    plan = planned(release_check([picked]))
    assert "read:confluence_page" not in named(plan)
    assert not any(name.startswith("read:") for name in named(plan))
    run = _run(
        ("Read releases", "read", {"source": "confluence_page", "place": "1", "query": None})
    )
    assert reached(plan, run, _ended()) == ("read:confluence_page",)


def test_an_address_n8n_could_not_reach_counts_as_reached() -> None:
    """The simulation n8n reaches only the mocks and the gateway, so a block that tried any other
    address failed there, and n8n's record names the address."""
    plan = planned(release_check())
    for error, host in [
        ("getaddrinfo ENOTFOUND evil.example", "host:evil.example"),
        ("connect ECONNREFUSED 10.0.0.5:443", "host:10.0.0.5:443"),
        ("getaddrinfo EAI_AGAIN Evil.Example.", "host:evil.example"),
    ]:
        assert reached(plan, None, _ended(error)) == (host,)
    assert reached(plan, None, _ended("The place was not found at the source.")) == ()


def test_a_pinned_block_reaches_nothing_and_a_block_that_never_ran_reaches_nothing() -> None:
    plan = planned(release_check([github_read(), jira_read()]))
    assert reached(plan, None, _ended(ran={"Read the issue": "success"})) == ()
    assert reached(plan, None, _ended(ran={"GitHub releases": "success"})) == ("mock:github",)
    assert "mock:jira" not in named(plan), "a pinned block never runs"


# Fail closed: each of n8n's own blocks that calls out, from its own try in the run data

GITHUB = "GitHub releases"


def _github_ran(*errors: str | NodeError, state: str = "success") -> ExecutionRecord:
    """GitHub's block ran, with these errors. A text alone came with no answer."""
    tried = tuple(e if isinstance(e, NodeError) else NodeError(e) for e in errors)
    return _ended(ran={GITHUB: state}, nodes={GITHUB: NodeRun(state, tried)})


def test_a_block_that_went_on_past_its_failure_still_counts_the_address_it_tried() -> None:
    """With continueOnFail or onError, the run goes on, and the execution's own error is empty:
    the error stands in the block's own try, or in the items it passed on."""
    went_on = github_read()
    went_on["continueOnFail"] = True
    plan = planned(release_check([went_on]))
    ended = _github_ran("getaddrinfo ENOTFOUND evil.example")
    assert ended.error is None
    assert reached(plan, None, ended) == ("host:evil.example", "mock:github")


def test_a_successful_call_to_an_address_a_block_names_counts_as_reached_and_named() -> None:
    elsewhere = github_read()
    elsewhere["parameters"]["baseUrl"] = "https://evil.example/api/v3"
    plan = planned(release_check([elsewhere]))
    assert "host:evil.example" in named(plan)
    assert reached(plan, None, _github_ran()) == ("host:evil.example", "mock:github")


def test_an_address_an_expression_picks_is_unknown_so_it_widens() -> None:
    picked = github_read()
    picked["parameters"]["baseUrl"] = "={{ $json.where }}"
    plan = planned(release_check([picked]))
    assert f"unknown:{GITHUB}" in named(plan)
    assert f"unknown:{GITHUB}" in reached(plan, None, _github_ran())


def test_an_error_the_platform_can_t_read_is_unknown_so_it_widens() -> None:
    plan = planned(release_check([github_read()]))
    odd = _github_ran("Something went wrong in a way nobody wrote down", state="error")
    assert reached(plan, None, odd) == ("mock:github", f"unknown:{GITHUB}")


def test_an_error_that_came_with_an_answer_reached_the_block_s_own_mock() -> None:
    plan = planned(release_check([github_read()]))
    answered = _github_ran(NodeError("The resource you are requesting could not be found", "404"))
    assert reached(plan, None, answered) == ("mock:github",)


def test_an_answer_counts_for_its_own_error_only() -> None:
    """One error that came with an answer doesn't vouch for another of the same block's."""
    plan = planned(release_check([github_read()]))
    both = _github_ran(NodeError("Not Found", "404"), "Something nobody wrote down")
    assert reached(plan, None, both) == ("mock:github", f"unknown:{GITHUB}")


def test_a_dropped_connection_the_scenario_played_reached_the_block_s_own_mock() -> None:
    plan = planned(release_check([github_read()]))
    dropped = _github_ran("The connection was aborted", state="error")
    assert reached(plan, None, dropped, failing=frozenset({GITHUB})) == ("mock:github",)
    assert reached(plan, None, dropped) == ("mock:github", f"unknown:{GITHUB}")


def test_a_failing_block_s_error_that_isn_t_the_mock_s_is_unknown() -> None:
    """The scenario played the block as a failure, but only mock GitHub's own words for a dropped
    connection are the mock's."""
    plan = planned(release_check([github_read()]))
    other = _github_ran("Request failed for a reason nobody wrote down", state="error")
    assert reached(plan, None, other, failing=frozenset({GITHUB})) == (
        "mock:github",
        f"unknown:{GITHUB}",
    )


# Fail closed on parameters: an address under any name counts


def _with(**parameters: Any) -> dict[str, Any]:
    block = github_read()
    block["parameters"] |= parameters
    return block


def test_a_url_under_a_parameter_with_any_name_is_an_address() -> None:
    plan = planned(release_check([_with(notes="see https://evil.example:8443/x for more")]))
    assert "host:evil.example:8443" in named(plan)
    assert "host:evil.example:8443" in reached(plan, None, _github_ran())


def test_a_host_name_under_a_parameter_with_any_name_is_an_address() -> None:
    plan = planned(release_check([_with(target="Evil.Example")]))
    assert "host:evil.example" in named(plan)
    plan = planned(release_check([_with(target="10.0.0.5:443")]))
    assert "host:10.0.0.5:443" in named(plan)


def test_a_proxy_is_an_address_and_one_an_expression_picks_is_unknown() -> None:
    plan = planned(release_check([_with(options={"proxy": "evil.example:3128"})]))
    assert "host:evil.example:3128" in named(plan)
    plan = planned(release_check([_with(options={"proxy": "={{ $json.proxy }}"})]))
    assert f"unknown:{GITHUB}" in named(plan)


def test_an_expression_that_builds_an_address_is_unknown_whatever_its_name() -> None:
    plan = planned(release_check([_with(notes="={{ 'https://' + $json.host }}")]))
    assert f"unknown:{GITHUB}" in named(plan)


def test_plain_words_and_versions_are_no_address() -> None:
    plan = planned(release_check([_with(notes="Release 1.2.16 of langgraph")]))
    assert not any(word.startswith(("host:", "unknown:")) for word in named(plan))


def test_a_block_of_n8n_s_with_no_try_in_the_run_data_is_unknown() -> None:
    plan = planned(release_check([github_read()]))
    missing = _ended(ran={GITHUB: "success"}, nodes={})
    assert reached(plan, None, missing) == ("mock:github", f"unknown:{GITHUB}")


def test_each_block_of_n8n_s_that_calls_out_is_named_so_a_new_one_widens() -> None:
    plan = planned(release_check([github_read(), jira_read()]))
    assert {w for w in named(plan) if w.startswith("outbound:")} == {
        "outbound:GitHub releases@n8n-nodes-base.github",
        "outbound:Read the issue@n8n-nodes-base.jira",
    }


def test_n8n_s_run_data_gives_each_block_s_state_errors_and_whether_an_answer_came() -> None:
    run_data = {
        "Start from the Portal": [{"executionStatus": "success"}],
        GITHUB: [
            {"executionStatus": "error"},
            {
                "executionStatus": "error",
                "error": {
                    "message": "The resource you are requesting could not be found",
                    "description": "Not Found",
                    "httpCode": "404",
                },
            },
        ],
        "Went on": [
            {
                "executionStatus": "success",
                "data": {
                    "main": [
                        [
                            {"json": {"error": "getaddrinfo ENOTFOUND evil.example"}},
                            {"json": {"error": {"message": "connect ECONNREFUSED 10.0.0.5:443"}}},
                            {"json": {"tag_name": "1.2.16"}},
                        ]
                    ]
                },
            }
        ],
    }
    assert node_runs(run_data) == {
        "Start from the Portal": NodeRun("success"),
        GITHUB: NodeRun(
            "error",
            (
                NodeError("The resource you are requesting could not be found", "404"),
                NodeError("Not Found", "404"),
            ),
        ),
        "Went on": NodeRun(
            "success",
            (
                NodeError("getaddrinfo ENOTFOUND evil.example"),
                NodeError("connect ECONNREFUSED 10.0.0.5:443"),
            ),
        ),
    }
