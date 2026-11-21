"""Code's check of a drafted plan against the catalogue of the pinned n8n image, and the marks on
its settings (ADR 0051, sections 1, 2 and 5). Each test checks a plan as the drafter would submit
it. CI mounts contracts/ into the test image, where it is /contracts."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.catalogue import Catalogue, load
from agent_runtime.contract import (
    INVENTED_CODES,
    DrafterFacts,
    ModelAccess,
    PlanProblem,
    PlanSetting,
    SettingPlace,
    WorkflowDraftRequest,
    WorkflowPlan,
)
from agent_runtime.plan_settings import day_in, run_time_in
from agent_runtime.workflow_drafter import check_plan
from agent_runtime.workflow_plan import NEVER_GUESSED, USE_OURS, ProposedPlan
from tests.day_leads import DAYS_LED_BY_AN_UNKNOWN_WORD

CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "n8n" / "catalogue.json"
WORDS = (
    "Every Monday at 9am, check langchain-ai/langgraph for new releases, open a Jira ticket in "
    "MOCK for each one, and post it in #support."
)
FACTS = DrafterFacts(
    jira_projects=["MOCK", "OPS"],
    repositories=["langchain-ai/langgraph"],
    channels=["#support", "#ops"],
    confluence_pages=["Software inventory"],
)
ACCESS = ModelAccess(style="anthropic", base_url="https://x.invalid", model="m", api_key="unused")

type Json = dict[str, Any]


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load(CATALOGUE)


def block(name: str, node_type: str, version: float, **parameters: object) -> Json:
    return {
        "name": name,
        "type": node_type,
        "version": version,
        "parameters": json.dumps(parameters),
    }


def wire(source: str, target: str, exit_name: str = "main") -> Json:
    return {"from_block": source, "exit": exit_name, "to_block": target}


def setting(id_: str, kind: str, value: str | None = None, label: str = "A setting") -> Json:
    return {"id": id_, "kind": kind, "label": label, "value": value}


SCHEDULE = block("Every Monday", "n8n-nodes-base.scheduleTrigger", 1.4, rule="<<run_time>>")
READ = block("Read releases", "CUSTOM.wabRead", 1, source="github_releases", place="<<repository>>")
PROPOSE = block(
    "Propose a ticket",
    "CUSTOM.wabProposeChange",
    1,
    action="jira.create_ticket",
    place="<<jira_project>>",
    title="={{ 'New release ' + $json.tag }}",
    subject="={{ $json.tag }}",
)
ASK = block("Ask for a yes", "CUSTOM.wabAskForYes", 1)
MAKE = block("Make the ticket", "CUSTOM.wabMakeApprovedChanges", 1)
SLACK = block(
    "Post in Slack",
    "n8n-nodes-base.slack",
    2.7,
    resource="message",
    operation="post",
    select="channel",
    channelId={"__rl": True, "mode": "name", "value": "<<channel>>"},
    text="={{ 'Ticket for ' + $json.tag }}",
)
RELEASE_WIRES = [
    wire("Every Monday", "Read releases"),
    wire("Read releases", "Propose a ticket"),
    wire("Propose a ticket", "Ask for a yes"),
    wire("Ask for a yes", "Make the ticket", "Yes"),
    wire("Make the ticket", "Post in Slack"),
]
RELEASE_SETTINGS = [
    setting("run_time", "run_time"),
    setting("repository", "repository", "langchain-ai/langgraph"),
    setting("jira_project", "jira_project", "MOCK"),
    setting("channel", "channel", "#support"),
]


def plan(
    blocks: list[Json],
    wires: list[Json] | None = None,
    settings: list[Json] | None = None,
    name: str = "Release tickets",
) -> ProposedPlan:
    return ProposedPlan.model_validate(
        {"name": name, "blocks": blocks, "wires": wires or [], "settings": settings or []}
    )


def checked(
    catalogue: Catalogue,
    proposed: ProposedPlan,
    words: str = WORDS,
    current: WorkflowPlan | None = None,
) -> WorkflowPlan | list[PlanProblem]:
    request = WorkflowDraftRequest(words=words, facts=FACTS, model=ACCESS, current=current)
    return check_plan(proposed, catalogue, request)


def passed(catalogue: Catalogue, proposed: ProposedPlan, words: str = WORDS) -> WorkflowPlan:
    result = checked(catalogue, proposed, words)
    assert isinstance(result, WorkflowPlan), [p.text for p in result]
    return result


def problems(catalogue: Catalogue, proposed: ProposedPlan, words: str = WORDS) -> list[PlanProblem]:
    result = checked(catalogue, proposed, words)
    assert isinstance(result, list), "the plan passed"
    return result


def release(catalogue: Catalogue) -> WorkflowPlan:
    return passed(
        catalogue,
        plan([SCHEDULE, READ, PROPOSE, ASK, MAKE, SLACK], RELEASE_WIRES, RELEASE_SETTINGS),
    )


def test_a_whole_plan_passes_with_its_exits_and_settings_placed(catalogue: Catalogue):
    done = release(catalogue)

    yes = next(w for w in done.wires if w.from_block == "Ask for a yes")
    assert (yes.exit, yes.exit_index, yes.input_index) == ("Yes", 1, 0)
    by_id = {s.id: s for s in done.settings}
    assert by_id["run_time"].fills == [SettingPlace(block="Every Monday", parameter="rule")]
    assert by_id["channel"].fills == [
        SettingPlace(block="Post in Slack", parameter="channelId.value")
    ]
    assert {s.id: (s.value, s.mark) for s in done.settings} == {
        "run_time": ("monday 09:00", "filled"),
        "repository": ("langchain-ai/langgraph", "filled"),
        "jira_project": ("MOCK", "filled"),
        "channel": ("#support", "filled"),
    }


@pytest.mark.parametrize(
    ("bad", "code", "said"),
    [
        (block("X", "n8n-nodes-base.nothing", 1), "no_block", "n8n has no block"),
        (block("X", "n8n-nodes-base.slack", 9, resource="message"), "no_version", "no version 9"),
        (
            block("X", "n8n-nodes-base.jira", 1, resource="ticket", operation="create"),
            "no_resource",
            "has no resource 'ticket'",
        ),
        (
            block("X", "n8n-nodes-base.jira", 1, resource="issue", operation="close"),
            "no_operation",
            "has no operation 'close'",
        ),
        (
            block(
                "X",
                "n8n-nodes-base.jira",
                1,
                resource="issue",
                operation="get",
                issueKey="A-1",
                issue="A-1",
            ),
            "no_parameter",
            "there is no parameter 'issue'",
        ),
        (
            block("X", "n8n-nodes-base.aggregate", 1, aggregate="all"),
            "bad_value",
            'aggregate must be one of "aggregateIndividualFields", "aggregateAllItemData"',
        ),
        (
            block("X", "n8n-nodes-base.jira", 1, resource="issue", operation="getAll", limit=500),
            "bad_value",
            "limit is at most 100",
        ),
        (
            block("X", "CUSTOM.wabTell", 1, where="={{ $json.where }}"),
            "bad_value",
            "where takes a value written out, not an expression",
        ),
        (
            block("X", "n8n-nodes-base.jira", 1, resource="issue"),
            "missing_value",
            "Jira Software needs an operation",
        ),
        (
            block(
                "X", "n8n-nodes-base.slack", 2.7, resource="message", operation="post", text="Hi"
            ),
            "missing_value",
            "Send Message To (select) needs a value",
        ),
        (
            block(
                "X",
                "n8n-nodes-base.jira",
                1,
                resource="issue",
                operation="getAll",
                options={"x": 1},
            ),
            "no_parameter",
            "options has no 'x'",
        ),
    ],
)
def test_what_n8n_doesn_t_have_or_won_t_take_goes_back_named(
    catalogue: Catalogue, bad: Json, code: str, said: str
):
    found = problems(catalogue, plan([bad]))

    assert [p.code for p in found] == [code]
    assert said in found[0].text
    assert found[0].block == "X"
    assert (code in INVENTED_CODES) == (code.startswith("no_"))


@pytest.mark.parametrize(
    ("bad", "code", "said"),
    [
        (block("X", "n8n-nodes-base.function", 1), "left_out", "Function never loads"),
        (block("X", "@n8n/n8n-nodes-langchain.code", 1), "left_out", "LangChain Code never"),
        (block("X", "n8n-nodes-base.git", 1.1), "left_out", "Git never loads"),
        (
            block("X", "n8n-nodes-base.executeWorkflow", 1.3),
            "held",
            "It runs another workflow, which its approval doesn't cover",
        ),
        (block("X", "n8n-nodes-base.executeCommand", 1), "left_out", "Execute Command never loads"),
        (block("X", "n8n-nodes-base.localFileTrigger", 1), "left_out", "Local File Trigger"),
        (block("X", "n8n-nodes-acme.thing", 1), "community", "Community nodes stay off"),
        (block("X", "@acme/n8n-nodes-x.thing", 1), "community", "Community nodes stay off"),
        (block("X", "n8n-nodes-base.stickyNote", 1), "platform_adds", "the Sticky Note"),
        (block("X", "CUSTOM.wabStartFromPortal", 1), "platform_adds", "Start from the Portal"),
        (block("X", "n8n-nodes-base.n8n", 1), "cant_run", "n8n's own API"),
        (block("X", "n8n-nodes-base.microsoftTeams", 2), "cant_run", "a person's own sign-in"),
    ],
)
def test_what_can_t_run_on_this_platform_goes_back_with_its_reason(
    catalogue: Catalogue, bad: Json, code: str, said: str
):
    found = problems(catalogue, plan([bad]))

    assert [p.code for p in found] == [code]
    assert said in found[0].text


@pytest.mark.parametrize(
    "runs_code",
    [
        block("Code", "n8n-nodes-base.code", 2, jsCode="return $input.all();"),
        block("Sort", "n8n-nodes-base.sort", 1, type="code", code="return a.json.n - b.json.n;"),
        block("Merge", "n8n-nodes-base.merge", 3.2, mode="combineBySql"),
    ],
    ids=["code", "sort", "merge-sql"],
)
def test_a_block_that_runs_code_in_the_external_runner_or_an_isolate_is_not_held(
    catalogue: Catalogue, runs_code: Json
):
    """Spike P9: n8n runs Code and Sort's code mode in its external task runner, and Merge's SQL
    in an isolate, so build step 12 loads them. The checker still flags them."""
    assert passed(catalogue, plan([runs_code])).blocks[0].type == runs_code["type"]


@pytest.mark.parametrize(
    "writes",
    [
        block("X", "n8n-nodes-base.jira", 1, resource="issue", operation="create"),
        block("X", "n8n-nodes-base.jira", 1, resource="issueComment", operation="add"),
        block("X", "n8n-nodes-base.confluence", 1, resource="page", operation="update"),
        block("X", "n8n-nodes-base.jiraTool", 1, resource="issue", operation="delete"),
        block(
            "X",
            "n8n-nodes-base.httpRequest",
            4.5,
            method="POST",
            url="https://acme.atlassian.net/rest/api/3/issue",
        ),
        block(
            "X",
            "n8n-nodes-base.httpRequest",
            4.5,
            method="={{ $json.how }}",
            url="https://acme.atlassian.net/wiki/rest/api/content",
        ),
    ],
)
def test_a_jira_or_confluence_write_with_n8n_s_own_block_goes_back_to_use_ours(
    catalogue: Catalogue, writes: Json
):
    found = [p for p in problems(catalogue, plan([writes])) if p.code == "native_write"]

    assert len(found) == 1
    assert USE_OURS in found[0].text


@pytest.mark.parametrize(
    "reads",
    [
        block("X", "n8n-nodes-base.jira", 1, resource="issue", operation="getAll"),
        block("X", "n8n-nodes-base.confluence", 1, resource="page", operation="get"),
        block(
            "X",
            "n8n-nodes-base.httpRequest",
            4.5,
            url="https://acme.atlassian.net/rest/api/3/myself",
        ),
    ],
)
def test_n8n_s_own_jira_and_confluence_blocks_may_read(catalogue: Catalogue, reads: Json):
    found = checked(catalogue, plan([reads]))

    assert not isinstance(found, list) or not [p for p in found if p.code == "native_write"]


def test_propose_a_change_takes_only_a_change_the_platform_offers(catalogue: Catalogue):
    """Before, any written action passed the check, so a Confluence change the platform doesn't
    offer passed too, and the run refused it later."""
    confluence = json.loads(PROPOSE["parameters"]) | {
        "action": "confluence.update_page",
        "place": "<<confluence_page>>",
    }
    proposed = plan(
        [PROPOSE | {"parameters": json.dumps(confluence)}],
        settings=[setting("confluence_page", "confluence_page", "Software inventory")],
    )

    found = problems(catalogue, proposed)
    assert [p.code for p in found] == ["bad_value"]
    assert 'action must be one of "jira.create_ticket"' in found[0].text


def test_propose_a_change_s_action_is_written_out_never_a_setting(catalogue: Catalogue):
    """Before, a placeholder stood in for the action, so a text setting could carry a change the
    platform doesn't offer past the check."""
    dodged = json.loads(PROPOSE["parameters"]) | {"action": "<<action>>"}
    proposed = plan(
        [PROPOSE | {"parameters": json.dumps(dodged)}],
        settings=[
            setting("action", "text", "confluence.update_page"),
            setting("jira_project", "jira_project", "MOCK"),
        ],
    )

    found = problems(catalogue, proposed)
    assert [p.code for p in found] == ["bad_value"]
    assert 'action takes one of "jira.create_ticket", written out, never a setting' in (
        found[0].text
    )


@pytest.mark.parametrize(
    ("guess", "kind"),
    [
        (
            block(
                "X", "n8n-nodes-base.scheduleTrigger", 1.4, rule={"interval": [{"field": "days"}]}
            ),
            "run_time",
        ),
        (
            block(
                "X",
                "n8n-nodes-base.slack",
                2.7,
                resource="message",
                operation="post",
                select="channel",
                channelId={"__rl": True, "mode": "name", "value": "#support"},
                text="Hello",
            ),
            "channel",
        ),
        (block("X", "CUSTOM.wabRead", 1, source="jira_tickets", place="MOCK"), "jira_project"),
        (
            block(
                "X", "n8n-nodes-base.jira", 1, resource="issue", operation="getAll", project="MOCK"
            ),
            None,
        ),
    ],
)
def test_a_value_the_drafter_never_writes_must_be_a_setting(
    catalogue: Catalogue, guess: Json, kind: str | None
):
    found = problems(catalogue, plan([guess]))

    if kind is None:  # Jira's getAll has no project: it goes in the JQL.
        assert [p.code for p in found] == ["no_parameter"]
        return
    assert [p.code for p in found] == ["guessed"]
    assert f"<<{kind}>>" in found[0].text


@pytest.mark.parametrize(
    ("wires", "said"),
    [
        ([wire("Every Monday", "Nowhere")], "'Nowhere', which no block in the plan is called"),
        ([wire("Ask for a yes", "Make the ticket", "Maybe")], 'has the exits "No answer", "Yes"'),
        ([wire("Make the ticket", "Every Monday")], "starts the workflow and takes no wire in"),
        ([wire("Ask for a yes", "Ask for a yes", "Yes")], "joins a block to itself"),
        ([wire("Every Monday", "Ask for a yes")] * 2, "is in the plan twice"),
    ],
)
def test_each_wire_must_join_blocks_and_exits_that_exist(
    catalogue: Catalogue, wires: list[Json], said: str
):
    found = problems(
        catalogue, plan([SCHEDULE, ASK, MAKE], wires, [setting("run_time", "run_time")])
    )

    assert [p.code for p in found] == ["wire"]
    assert said in found[0].text


def test_wires_into_merge_fill_its_inputs_in_order(catalogue: Catalogue):
    sources = [block(f"Read {n}", "CUSTOM.wabTell", 1) for n in "ABC"]
    merge = block("Merge", "n8n-nodes-base.merge", 3.2, mode="append")
    two = plan([*sources, merge], [wire("Read A", "Merge"), wire("Read B", "Merge")])

    assert [w.input_index for w in passed(catalogue, two).wires] == [0, 1]
    three = plan([*sources, merge], [wire(f"Read {n}", "Merge") for n in "ABC"])
    assert "takes 2 wires in" in problems(catalogue, three)[0].text


IF = block("Is it new", "n8n-nodes-base.if", 2.3)
ROUTE = block("Route", "n8n-nodes-base.switch", 3.4, rules={"values": [{}, {}, {}]})
MERGE = block("Merge", "n8n-nodes-base.merge", 3.2, mode="append", numberInputs=3)
TELL = block("Tell", "CUSTOM.wabTell", 1)
MODEL = block("Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.3, model="gpt-5")


def into(source: str, target: str, exit_name: str, input_index: int | None) -> Json:
    return wire(source, target, exit_name) | {"input": input_index}


def test_exits_and_inputs_are_n8n_s_own_from_the_catalogue(catalogue: Catalogue):
    """If's false exit, Switch's third output and Merge's second input, by the outputs, output
    names and inputs the pinned image serves, as the catalogue holds them."""
    wires = [
        wire("Is it new", "Route", "false"),
        into("Route", "Merge", "2", 1),
        into("Tell", "Merge", "main", 0),
    ]

    done = passed(catalogue, plan([IF, ROUTE, MERGE, TELL], wires))

    assert [(w.exit, w.exit_index, w.input_index) for w in done.wires] == [
        ("false", 1, 0),
        ("2", 2, 1),
        ("main", 0, 0),
    ]


@pytest.mark.parametrize(
    ("wires", "said"),
    [
        ([wire("Route", "Tell", "3")], '\'Route\' has the exits "0", "1", "2"'),
        ([wire("Route", "Tell", "rule 1")], '\'Route\' has the exits "0", "1", "2"'),
        ([wire("Is it new", "Tell", "main")], '\'Is it new\' has the exits "true", "false"'),
        ([into("Is it new", "Merge", "true", 3)], "joins input 3 of 'Merge', which takes 3"),
        ([into("Is it new", "Tell", "true", 1)], "joins input 1 of 'Tell', which takes 1"),
        ([into("Is it new", "Merge", "true", -1)], "joins input -1 of 'Merge'"),
        ([wire("Is it new", "Model", "true")], "'Model', which takes no main wire in"),
        ([wire("Model", "Tell", "ai_languageModel")], "'Tell', which takes no ai_languageModel"),
    ],
)
def test_a_wire_to_an_exit_or_an_input_n8n_doesn_t_give_goes_back(
    catalogue: Catalogue, wires: list[Json], said: str
):
    found = problems(catalogue, plan([IF, ROUTE, MERGE, TELL, MODEL], wires))

    assert [p.code for p in found] == ["wire"]
    assert said in found[0].text


SLACK_TOOL = block(
    "Post in Slack",
    "n8n-nodes-base.slackTool",
    2.7,
    resource="message",
    operation="post",
    select="channel",
    channelId={"__rl": True, "mode": "name", "value": "<<channel>>"},
    text="A note",
)
MCP = block("Outside callers", "@n8n/n8n-nodes-langchain.mcpTrigger", 2.1, path="tools")


def test_nothing_wires_into_a_trigger_not_even_a_tool_into_an_mcp_server_trigger(
    catalogue: Catalogue,
):
    """A tool wired into MCP Server Trigger would let any outside MCP caller post in Slack with
    no yes. main refused every wire into a trigger, and so does this check."""
    found = problems(
        catalogue,
        plan(
            [SLACK_TOOL, MCP],
            [wire("Post in Slack", "Outside callers", "ai_tool")],
            [setting("channel", "channel", "#support")],
        ),
    )

    assert [p.code for p in found] == ["wire"]
    assert "'Outside callers', which starts the workflow and takes no wire in" in found[0].text


def test_a_wire_with_no_input_skips_the_inputs_other_wires_name(catalogue: Catalogue):
    """Before, both wires joined input 0 and Merge's input 1 stayed empty."""
    merge = block("Merge", "n8n-nodes-base.merge", 3.2, mode="append")
    sources = [block(f"Tell {n}", "CUSTOM.wabTell", 1) for n in "AB"]
    wires = [into("Tell A", "Merge", "main", None), into("Tell B", "Merge", "main", 0)]

    done = passed(catalogue, plan([*sources, merge], wires))
    assert [(w.from_block, w.input_index) for w in done.wires] == [("Tell A", 1), ("Tell B", 0)]


def test_two_wires_on_one_input_of_a_block_with_more_go_back(catalogue: Catalogue):
    merge = block("Merge", "n8n-nodes-base.merge", 3.2, mode="append")
    sources = [block(f"Tell {n}", "CUSTOM.wabTell", 1) for n in "AB"]
    wires = [into("Tell A", "Merge", "main", 1), into("Tell B", "Merge", "main", 1)]

    found = problems(catalogue, plan([*sources, merge], wires))
    assert [p.code for p in found] == ["wire"]
    assert "joins input 1 of 'Merge', which another wire already joins" in found[0].text


AGENT = block("Agent", "@n8n/n8n-nodes-langchain.agent", 3.1, text="Sum up the tickets")
EMBEDDINGS = block("Embeddings", "@n8n/n8n-nodes-langchain.embeddingsOpenAi", 1.2)


def test_known_tradeoff_a_block_kept_by_hand_takes_any_ai_wire_even_embeddings_into_an_agent(
    catalogue: Catalogue,
):
    """Code keeps the AI Agent's AI inputs by hand (connections.BY_HAND), so it lets any AI wire
    join, though n8n's agent takes no embeddings. The builder can't lay out an AI wire yet."""
    wires = [wire("Embeddings", "Agent", "ai_embedding")]

    done = passed(catalogue, plan([EMBEDDINGS, AGENT], wires))
    assert [(w.exit, w.input_index) for w in done.wires] == [("ai_embedding", 0)]


@pytest.mark.parametrize(
    ("blocks", "settings", "said"),
    [
        ([SCHEDULE], [], "holds <<run_time>>, but the plan has no setting 'run_time'"),
        ([ASK], [setting("spare", "text", "x")], "The setting 'spare' stands in no parameter"),
        (
            [SCHEDULE],
            [setting("run_time", "text")],
            "so the setting 'run_time' is of kind run_time",
        ),
        ([SCHEDULE], [setting("Run Time", "run_time")], "must be lowercase letters"),
    ],
)
def test_every_placeholder_has_its_setting_and_every_setting_a_place(
    catalogue: Catalogue, blocks: list[Json], settings: list[Json], said: str
):
    found = problems(catalogue, plan(blocks, [], settings))

    assert any(said in p.text for p in found), [p.text for p in found]
    assert {p.code for p in found} == {"setting"}


@pytest.mark.parametrize(
    ("blocks", "name", "said"),
    [
        ([ASK], "Ember release check", "uses an old themed name"),
        ([ASK, ASK], "Release check", "Two blocks are named 'Ask for a yes'"),
        ([block("Scout the releases", "CUSTOM.wabTell", 1)], "Release check", "old themed name"),
        ([], "Release check", "A plan needs at least one block"),
    ],
)
def test_names_are_plain_and_unique(catalogue: Catalogue, blocks: list[Json], name: str, said: str):
    found = problems(catalogue, plan(blocks, name=name))

    assert any(said in p.text for p in found), [p.text for p in found]


# The marks on the settings: code's, never the model's.


def marks(
    catalogue: Catalogue, settings: list[Json], words: str, current: WorkflowPlan | None = None
) -> dict[str, tuple[str | None, str]]:
    blocks = [SCHEDULE, READ, PROPOSE, ASK, MAKE, SLACK]
    result = checked(catalogue, plan(blocks, RELEASE_WIRES, settings), words, current)
    assert isinstance(result, WorkflowPlan), result
    return {s.id: (s.value, s.mark) for s in result.settings}


def test_a_value_the_words_don_t_hold_is_never_filled(catalogue: Catalogue):
    words = "Check LangGraph for new releases and open a ticket for each one."

    assert marks(catalogue, RELEASE_SETTINGS, words) == {
        "run_time": (None, "needed"),
        "repository": ("langchain-ai/langgraph", "guessed"),
        "jira_project": (None, "needed"),
        "channel": (None, "needed"),
    }


def test_a_never_guessed_value_must_be_in_the_team_s_facts_too(catalogue: Catalogue):
    words = "Every day at 08:00, open a ticket in SECRET for LangGraph and post it in #random."
    settings = [
        setting("run_time", "run_time"),
        setting("repository", "repository"),
        setting("jira_project", "jira_project", "SECRET"),
        setting("channel", "channel", "#random"),
    ]

    assert marks(catalogue, settings, words) == {
        "run_time": ("every_day 08:00", "filled"),
        "repository": (None, "needed"),
        "jira_project": (None, "needed"),
        "channel": (None, "needed"),
    }


def test_code_finds_the_one_fact_the_words_name_when_the_drafter_gives_none(catalogue: Catalogue):
    words = (
        "Every Friday at 17:00 read langchain-ai/langgraph, ticket it in OPS, post in the ops "
        "channel."
    )
    settings = [
        setting("run_time", "run_time"),
        setting("repository", "repository"),
        setting("jira_project", "jira_project"),
        setting("channel", "channel"),
    ]

    assert marks(catalogue, settings, words) == {
        "run_time": ("friday 17:00", "filled"),
        "repository": ("langchain-ai/langgraph", "filled"),
        "jira_project": ("OPS", "filled"),
        "channel": ("#ops", "filled"),
    }


def test_a_project_key_counts_only_as_written(catalogue: Catalogue):
    words = "Every day at 08:00, check the mock project and the MOCK-142 ticket in #support."

    assert marks(catalogue, RELEASE_SETTINGS, words)["jira_project"] == (None, "needed")


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("every Monday at 9am", ("monday 09:00", True)),
        ("each weekday at 08:30", ("weekdays 08:30", True)),
        ("every Monday at 9", (None, True)),
        ("every Monday", (None, True)),
        ("open a ticket for each release", (None, False)),
    ],
)
def test_a_run_time_is_code_s_reading_and_never_a_guessed_hour(
    words: str, read: tuple[str | None, bool]
):
    assert run_time_in(words) == read


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("Every Monday, open a ticket for LangGraph.", "monday"),
        ("Each weekday at 9, open a ticket for LangGraph.", "weekdays"),
        ("At 9:00, open a ticket for LangGraph.", None),
    ],
)
def test_a_needed_run_time_keeps_the_day_the_words_name_so_only_the_time_is_asked(
    catalogue: Catalogue, words: str, kept: str | None
):
    assert marks(catalogue, RELEASE_SETTINGS, words)["run_time"] == (kept, "needed")


def test_an_edit_that_names_the_time_fills_a_run_time_that_kept_its_day(catalogue: Catalogue):
    current = edited(
        {
            "run_time": ("monday", "needed"),
            "repository": ("langchain-ai/langgraph", "filled"),
            "jira_project": ("MOCK", "filled"),
            "channel": ("#support", "filled"),
        }
    )

    assert marks(catalogue, RELEASE_SETTINGS, "at 17:30 please", current)["run_time"] == (
        "monday 17:30",
        "filled",
    )


def edited(settings: dict[str, tuple[str | None, str]]) -> WorkflowPlan:
    places = {
        "run_time": SettingPlace(block="Every Monday", parameter="rule"),
        "repository": SettingPlace(block="Read releases", parameter="place"),
        "jira_project": SettingPlace(block="Propose a ticket", parameter="place"),
        "channel": SettingPlace(block="Post in Slack", parameter="channelId.value"),
    }
    kinds = {"run_time": "run_time", "repository": "repository", "jira_project": "jira_project"}
    return WorkflowPlan.model_validate(
        {
            "name": "Release tickets",
            "blocks": [{"name": "X", "type": "CUSTOM.wabTell", "version": 1, "parameters": {}}],
            "wires": [],
            "settings": [
                PlanSetting(
                    id=id_,
                    kind=kinds.get(id_, "channel"),  # type: ignore[arg-type]
                    label="A setting",
                    fills=[places[id_]],
                    value=value,
                    mark=mark,  # type: ignore[arg-type]
                ).model_dump()
                for id_, (value, mark) in settings.items()
            ],
        }
    )


def test_an_edit_keeps_each_value_its_words_don_t_change(catalogue: Catalogue):
    current = edited(
        {
            "run_time": ("monday 09:00", "filled"),
            "repository": ("langchain-ai/langgraph", "filled"),
            "jira_project": ("MOCK", "filled"),
            "channel": ("#support", "filled"),
        }
    )
    # The model changes the project and the channel without the words saying so.
    settings = [
        setting("run_time", "run_time"),
        setting("repository", "repository", "langchain-ai/langgraph"),
        setting("jira_project", "jira_project", "OPS"),
        setting("channel", "channel", "#ops"),
    ]

    assert marks(catalogue, settings, "post at 17:30 instead", current) == {
        "run_time": ("monday 17:30", "filled"),
        "repository": ("langchain-ai/langgraph", "filled"),
        "jira_project": ("MOCK", "filled"),
        "channel": ("#support", "filled"),
    }
    assert marks(catalogue, settings, "post in #ops instead", current)["channel"] == (
        "#ops",
        "filled",
    )
    assert marks(catalogue, settings, "post at 9 instead", current)["run_time"] == (
        "monday",
        "needed",
    )


@pytest.mark.parametrize(
    "when",
    [
        "Every other Friday at 9am",
        "Every 2 weeks on Friday at 9am",
        "Once a month on Friday at 9am",
        "Every weekday except Friday at 9am",
        "Monday to Wednesday at 9am",
        "Every Friday at 9am, actually make it Monday",
    ],
)
def test_a_schedule_the_platform_can_t_hold_leaves_the_run_time_needed(
    catalogue: Catalogue, when: str
):
    """Before, "every other Friday at 9am" filled the run time as every Friday at 09:00, and
    "every weekday except Friday" as every weekday."""
    words = f"{when}, check langchain-ai/langgraph and open a ticket in MOCK for each release."
    settings = [setting("run_time", "run_time", "friday 09:00"), *RELEASE_SETTINGS[1:]]

    assert marks(catalogue, settings, words)["run_time"] == (None, "needed")


@pytest.mark.parametrize(
    ("when", "kept"),
    [
        ("Every Friday at 9am or so", ("friday", "needed")),
        ("Every Friday at 9am roughly", ("friday", "needed")),
        ("Every Friday by the end of the day at 5pm", ("friday", "needed")),
        ("Mon-Fri at 9am", ("weekdays 09:00", "filled")),
        ("Daily at 9am, except weekends", ("weekdays 09:00", "filled")),
        ("Every Friday. Run it at 9am", ("friday 09:00", "filled")),
    ],
)
def test_a_run_time_holds_only_what_the_words_say_whole(
    catalogue: Catalogue, when: str, kept: tuple[str, str]
):
    """A time that is not exact keeps the day and asks the time. Weekdays written another way
    are every weekday."""
    words = f"{when}, check langchain-ai/langgraph and open a ticket in MOCK for each release."

    assert marks(catalogue, RELEASE_SETTINGS, words)["run_time"] == kept


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("make it every other Friday", (None, "needed")),
        ("run it once a month instead", (None, "needed")),
        ("make it Friday, no wait, Thursday", (None, "needed")),
        ("move it to Fridays at 9am or so", ("friday", "needed")),
        ("post in #ops instead", ("monday 09:00", "filled")),
    ],
)
def test_a_change_the_run_time_can_t_take_never_keeps_the_old_one_without_a_word(
    catalogue: Catalogue, words: str, kept: tuple[str | None, str]
):
    """Code now reads no day from a schedule it can't hold. Before, words it read nothing from
    kept the old run time, so "every other Friday" stayed every Monday at 09:00 with no
    question, and a day that clashed did the same."""
    current = edited(
        {
            "run_time": ("monday 09:00", "filled"),
            "repository": ("langchain-ai/langgraph", "filled"),
            "jira_project": ("MOCK", "filled"),
            "channel": ("#support", "filled"),
        }
    )

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == kept


@pytest.mark.parametrize(
    ("words", "read"),
    [
        (
            "Find tickets created on Monday and post them in #ops every day at 9am",
            "every_day 09:00",
        ),
        ("Find tickets closed on Friday and post a summary every day at 9am", "every_day 09:00"),
        ("Find tickets due on Friday and raise one ticket every weekday at 3pm", "weekdays 15:00"),
        ("Post Monday's standup notes to #ops every day at 9am", "every_day 09:00"),
        ("Check for tickets due by Friday and remind #ops every weekday at 9am", "weekdays 09:00"),
        ("Find the Mon-Fri on-call tickets and post them every Friday at 9am", "friday 09:00"),
        ("Post the Mon-Fri rota every Sunday at 6pm", "sunday 18:00"),
        ("Every day at 9am, post tickets created on Monday", "every_day 09:00"),
    ],
)
def test_a_day_in_a_filter_or_a_label_is_never_the_run_day(words: str, read: str):
    """Before, the first day the words named counted, so the question asked "Mondays, at what
    time?" for "tickets created on Monday", and the workflow ran on the filter's day."""
    assert run_time_in(words) == (read, True)


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("Find tickets created at 9am and post them every Friday", "friday"),
        ("Every Friday at 9am, check langgraph and post at 5pm in #ops", "friday"),
    ],
)
def test_a_time_two_phrases_could_each_give_is_asked(words: str, day: str):
    assert run_time_in(words) == (None, True)
    assert day_in(words) == day


@pytest.mark.parametrize(
    "words",
    [
        "Mon-Fri at 9am, also Sat, check langgraph",
        "Mon-Fri and Sat at 9am, check langgraph",
        "Mon-Fri, Sat at 9am, check langgraph",
        "Mon-Fri at 9am and Sun at 10am, check langgraph",
        "Daily at 9am, except weekends and holidays, check langgraph",
        "Daily at 9am except weekends, holidays, check langgraph",
        "Daily at 9am except weekends, and holidays, check langgraph",
        "Every day at 9am but skip Fridays, check langgraph",
        "Every weekday at 9am, never on Mondays, check langgraph",
    ],
)
def test_weekdays_beside_another_day_or_exception_are_asked(words: str):
    """Before, "Mon-Fri at 9am, also Sat" filled every weekday at 09:00 and dropped Saturday,
    "except weekends and holidays" filled every day, and "skip Fridays" was dropped."""
    assert run_time_in(words) == (None, True)
    assert day_in(words) is None


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("skip Fridays", (None, "needed")),
        ("don't run it on Mondays any more", (None, "needed")),
        ("never on Fridays", (None, "needed")),
        ("not on Fridays any more", (None, "needed")),
        ("stop running on Mondays", (None, "needed")),
        ("run it on Tue at 10am", ("tuesday 10:00", "filled")),
        ("make it Thu", ("thursday 09:00", "filled")),
        ("make it every Thu", ("thursday 09:00", "filled")),
        ("make it Monday to Fri", ("weekdays 09:00", "filled")),
        ("move it to the afternoon", ("monday", "needed")),
        ("run it in the evening instead", ("monday", "needed")),
        ("make it half past nine", ("monday", "needed")),
        ("make it 10 o'clock", ("monday", "needed")),
        ("make it 10", ("monday", "needed")),
        ("make it every morning", (None, "needed")),
        ("make it nightly", (None, "needed")),
        ("make it Mon-Fri 9-5", (None, "needed")),
    ],
)
def test_a_change_names_a_day_it_skips_or_a_time_it_cant_read_and_is_asked(
    catalogue: Catalogue, words: str, kept: tuple[str | None, str]
):
    """Before, "skip Fridays" made it run on Fridays, "run it on Tue at 10am" ran on Monday at
    10:00, and "make it Thu", "move it to the afternoon" or "make it 10" kept every Monday at
    09:00 without a word. Short day names read as the whole name."""
    current = edited(
        {
            "run_time": ("monday 09:00", "filled"),
            "repository": ("langchain-ai/langgraph", "filled"),
            "jira_project": ("MOCK", "filled"),
            "channel": ("#support", "filled"),
        }
    )

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == kept


@pytest.mark.parametrize("when", ["Monday to Fri at 9am", "Mon–Fri at 9am", "Mon - Fri at 9am"])
def test_monday_to_friday_written_short_or_with_a_dash_is_every_weekday(when: str):
    assert run_time_in(f"{when}, check langgraph") == ("weekdays 09:00", True)


@pytest.mark.parametrize(
    ("words", "before", "read"),
    [
        ("Check tickets in project MON at 9am and raise one ticket that lists them", None, None),
        (
            "Check tickets in project MON at 9am and raise one ticket that lists them",
            "friday 10:00",
            "friday 09:00",
        ),
        ("Check tickets in WED at 4pm and raise one ticket that lists them", None, None),
        ("Check the SAT tickets at 9am and raise one ticket that lists them", None, None),
        ("Check the THU tickets every day at 9am", None, "every_day 09:00"),
    ],
)
def test_a_project_key_that_looks_like_a_short_day_is_never_the_run_day(
    words: str, before: str | None, read: str | None
):
    """Before, "project MON at 9am" filled Monday at 09:00 and "the SAT tickets" ran on
    Saturdays. A short day in capitals is a project key, never a day."""
    assert run_time_in(words, before)[0] == read


@pytest.mark.parametrize(
    ("words", "read"),
    [
        (
            "Every Friday at 9am, list tickets in MOCK that are not on Monday's board",
            "friday 09:00",
        ),
        ("Every Friday at 9am, find tickets in MOCK titled Pause on Monday", "friday 09:00"),
        ("Every Friday at 9am, list tickets in MOCK besides Monday's", "friday 09:00"),
        ("Every Friday at 9am, list tickets in MOCK we skip on Mondays", "friday 09:00"),
        ("Every Monday at 9am, find tickets in MOCK, except Friday's hotfixes", "monday 09:00"),
        ("Every Monday at 9am, find tickets in MOCK not done over the weekend", "monday 09:00"),
        ("Every Monday at 9am, find tickets not updated during the weekend", "monday 09:00"),
    ],
)
def test_a_day_left_out_in_a_filter_never_makes_the_schedule_asked(words: str, read: str):
    """Before, a negation and a day anywhere in the words, as "not on Monday's board", asked
    the run time though the schedule was whole."""
    assert run_time_in(words) == (read, True)


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("change it to 10am", ("monday 10:00", "filled")),
        ("set it to 9am", ("monday 09:00", "filled")),
        ("move it to 3pm", ("monday 15:00", "filled")),
        ("push it to 10am", ("monday 10:00", "filled")),
        ("switch the time to 16:00", ("monday 16:00", "filled")),
        ("change the run time to 10am", ("monday 10:00", "filled")),
        ("change it to 10am on Fridays", ("friday 10:00", "filled")),
    ],
)
def test_a_change_to_a_new_time_sets_it_and_keeps_the_day(
    catalogue: Catalogue, words: str, kept: tuple[str, str]
):
    """At db3cb386, "change it to 10am" asked the time again, though a schedule change reads
    it."""
    current = edited(
        {
            "run_time": ("monday 09:00", "filled"),
            "repository": ("langchain-ai/langgraph", "filled"),
            "jira_project": ("MOCK", "filled"),
            "channel": ("#support", "filled"),
        }
    )

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == kept


@pytest.mark.parametrize(
    "words",
    [
        "List tickets due Friday at 5pm",
        "Post a summary of the tickets due on Friday at 5pm",
        "Check langchain-ai/langgraph for releases published on Monday at 9am",
        "Raise one ticket for the tickets created on Monday at 9am",
    ],
)
def test_a_filter_s_day_and_time_is_never_the_run_time_even_alone(words: str):
    """Before, "tickets due Friday at 5pm" ran every Friday at 17:00."""
    assert run_time_in(words) == (None, True)
    assert day_in(words) is None


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("Find tickets created at 9am on Monday and post them every day", "every_day"),
        ("Every day, post tickets created on Monday at 9am", "every_day"),
        ("Each week on Friday, post tickets updated on Monday at 9am", "friday"),
    ],
)
def test_a_filter_s_time_beside_the_schedule_is_asked_and_the_schedule_s_day_kept(
    words: str, day: str
):
    """Before, the filter's 9am became the run time beside the schedule's day."""
    assert run_time_in(words) == (None, True)
    assert day_in(words) == day


def test_a_switch_s_exits_follow_its_rules_and_a_written_count_is_held(catalogue: Catalogue):
    """n8n names each rule's exit by its output key, else its number from 0, then Fallback."""
    rules = {"values": [{"outputKey": "a"}, {}]}
    options = {"fallbackOutput": "extra"}
    switch = block("Route", "n8n-nodes-base.switch", 3.4, rules=rules, options=options)
    targets = [block(f"Tell {n}", "CUSTOM.wabTell", 1) for n in (1, 2, 3)]
    wires = [
        wire("Route", "Tell 1", "A"),
        wire("Route", "Tell 2", "1"),
        wire("Route", "Tell 3", "fallback"),
    ]

    done = passed(catalogue, plan([switch, *targets], wires))
    assert [(w.exit, w.exit_index) for w in done.wires] == [("a", 0), ("1", 1), ("Fallback", 2)]
    huge = block("Route", "n8n-nodes-base.switch", 3.4, mode="expression", numberOutputs=10**9)
    assert passed(catalogue, plan([huge, targets[0]], [wire("Route", "Tell 1", "79")]))
    out_of_range = plan([huge, targets[0]], [wire("Route", "Tell 1", "80")])
    assert any("has the exits" in p.text for p in problems(catalogue, out_of_range))
    same = block("Route", "n8n-nodes-base.switch", 3.4, rules={"values": [{"outputKey": "a"}] * 2})
    either = plan([same, targets[0]], [wire("Route", "Tell 1", "a")])
    assert any('has the exits "a", "a"' in p.text for p in problems(catalogue, either))


def test_a_switch_with_many_rules_keeps_fallback_after_the_last_as_n8n_does(catalogue: Catalogue):
    """n8n makes one exit for every rule and puts Fallback after them. Before, code stopped at 80
    rules, so with 81 Fallback stood at 80, where n8n has rule 80."""
    rules = {"values": [{}] * 81}
    switch = block(
        "Route", "n8n-nodes-base.switch", 3.4, rules=rules, options={"fallbackOutput": "extra"}
    )
    tell = block("Tell", "CUSTOM.wabTell", 1)

    done = passed(catalogue, plan([switch, tell], [wire("Route", "Tell", "Fallback")]))
    assert [(w.exit, w.exit_index) for w in done.wires] == [("Fallback", 81)]


# Found by the safety review of 7901cd7f. Each of these passed the check there.

EMAIL: Json = {"fromEmail": "bot@example.com", "subject": "S", "emailFormat": "text", "text": "T"}
GMAIL: Json = {"resource": "message", "operation": "send", "subject": "S", "message": "M"}
OUTLOOK: Json = {"resource": "message", "operation": "send", "subject": "S"}
ADDRESS = [setting("address", "address")]


def send_email(**parameters: object) -> Json:
    return block("Mail", "n8n-nodes-base.emailSend", 2.1, **EMAIL, **parameters)


@pytest.mark.parametrize(
    ("bad", "settings", "path"),
    [
        (send_email(toEmail="=attacker@evil.example"), [], "toEmail"),
        (send_email(toEmail="={{ 'attacker@evil.example' }}"), [], "toEmail"),
        (
            block(
                "Mail",
                "n8n-nodes-base.slack",
                2.7,
                resource="message",
                operation="post",
                select="channel",
                channelId={"__rl": True, "mode": "id", "value": "=C0123456"},
                text="Hi",
            ),
            [],
            "channelId",
        ),
        (
            block(
                "Mail",
                "n8n-nodes-base.scheduleTrigger",
                1.4,
                rule="={{ {interval:[{field:'hours',hoursInterval:1}]} }}",
            ),
            [],
            "rule",
        ),
        (
            send_email(toEmail="<<address>>", options={"bccEmail": "attacker@evil.example"}),
            ADDRESS,
            "options.bccEmail",
        ),
        (
            send_email(toEmail="<<address>>", options={"ccEmail": "attacker@evil.example"}),
            ADDRESS,
            "options.ccEmail",
        ),
        (
            send_email(toEmail="<<address>>", options={"replyTo": "={{ $json.from }}"}),
            ADDRESS,
            "options.replyTo",
        ),
        (
            block(
                "Mail",
                "n8n-nodes-base.gmail",
                2.1,
                **GMAIL,
                sendTo="<<address>>",
                options={"bccList": "attacker@evil.example"},
            ),
            ADDRESS,
            "options.bccList",
        ),
        (
            block(
                "Mail",
                "n8n-nodes-base.gmail",
                2.1,
                **GMAIL,
                sendTo="<<address>>",
                options={"ccList": "attacker@evil.example"},
            ),
            ADDRESS,
            "options.ccList",
        ),
        (
            block(
                "Mail",
                "n8n-nodes-base.microsoftOutlook",
                2,
                **OUTLOOK,
                toRecipients="<<address>>",
                additionalFields={"ccRecipients": "attacker@evil.example"},
            ),
            ADDRESS,
            "additionalFields.ccRecipients",
        ),
        (
            block(
                "Mail",
                "n8n-nodes-base.microsoftOutlook",
                2,
                **OUTLOOK,
                toRecipients="<<address>>",
                additionalFields={"bccRecipients": "attacker@evil.example"},
            ),
            ADDRESS,
            "additionalFields.bccRecipients",
        ),
    ],
)
def test_a_never_guessed_place_takes_only_a_placeholder_never_a_value_or_an_expression(
    catalogue: Catalogue, bad: Json, settings: list[Json], path: str
):
    found = problems(catalogue, plan([bad], [], settings))

    assert [p.code for p in found] == ["guessed"], [p.text for p in found]
    assert f'"Mail": {path} is ' in found[0].text


@pytest.mark.parametrize(
    "empty",
    [
        send_email(toEmail=""),
        block(
            "Mail",
            "n8n-nodes-base.slack",
            2.7,
            resource="message",
            operation="post",
            select="channel",
            channelId={"__rl": True, "mode": "id", "value": ""},
            text="Hi",
        ),
    ],
)
def test_an_empty_required_never_guessed_place_goes_back_for_a_needed_setting(
    catalogue: Catalogue, empty: Json
):
    found = problems(catalogue, plan([empty], [], []))

    assert [p.code for p in found] == ["missing_value"], [p.text for p in found]
    assert "add a setting" in found[0].text
    assert "with no value" in found[0].text


def test_an_empty_optional_never_guessed_place_is_not_used(catalogue: Catalogue):
    mail = send_email(toEmail="<<address>>", options={"ccEmail": ""})

    done = passed(catalogue, plan([mail], [], ADDRESS))

    assert [s.id for s in done.settings] == ["address"]


def test_the_needed_setting_the_check_asks_for_is_marked_needed(catalogue: Catalogue):
    mail = send_email(toEmail="<<address>>")

    done = passed(catalogue, plan([mail], [], ADDRESS), "Email the team each Monday")

    assert [(s.id, s.mark, s.value) for s in done.settings] == [("address", "needed", None)]


def test_every_never_guessed_block_is_one_the_drafter_may_propose(catalogue: Catalogue):
    hidden = [t for t in NEVER_GUESSED if catalogue.block(t).get("hidden")]

    assert hidden == []


def test_a_nested_address_placeholder_is_placed_with_its_kind(catalogue: Catalogue):
    mail = send_email(toEmail="<<address>>", options={"bccEmail": "<<copy>>"})
    settings = [*ADDRESS, setting("copy", "text")]

    found = problems(catalogue, plan([mail], [], settings))

    assert [p.code for p in found] == ["setting"]
    assert "options.bccEmail holds <<copy>>, which is an address a notice posts to" in found[0].text


def http(node_type: str, version: float, **parameters: object) -> Json:
    return block("Call", node_type, version, **parameters)


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (
            http("n8n-nodes-base.httpRequest", 4.5, method="POST", url="={{ $json.url }}"),
            "address_unread",
        ),
        (
            http(
                "n8n-nodes-base.httpRequest",
                4.5,
                method="POST",
                url="={{ 'https://acme.atlas' + 'sian.net/rest/ap' + 'i/3/issue' }}",
            ),
            "address_unread",
        ),
        (
            http("n8n-nodes-base.httpRequest", 4.5, method="PUT", url="<<where>>"),
            "address_unread",
        ),
        (
            http(
                "n8n-nodes-base.httpRequest",
                4.5,
                method="POST",
                url="https://api.atlassian.com/ex/confluence/abc/wiki/api/v2/pages",
            ),
            "native_write",
        ),
        (
            http(
                "n8n-nodes-base.httpRequest",
                4.5,
                method="POST",
                url="https://jira.ncs.example/rest/agile/1.0/sprint",
            ),
            "native_write",
        ),
        (
            http(
                "n8n-nodes-base.graphql",
                1.1,
                endpoint="https://api.atlassian.com/graphql",
                query="mutation { createIssue }",
            ),
            "native_write",
        ),
        (
            http(
                "n8n-nodes-base.graphql",
                1.1,
                endpoint="={{ $json.endpoint }}",
                query="mutation { createIssue }",
            ),
            "address_unread",
        ),
        (
            http(
                "@n8n/n8n-nodes-langchain.toolHttpRequest",
                1.1,
                toolDescription="x",
                method="POST",
                url="https://acme.atlassian.net/rest/api/3/issue",
            ),
            "hidden",
        ),
        (http("n8n-nodes-base.htmlExtract", 1), "hidden"),
    ],
)
def test_an_http_write_must_name_its_address_and_never_reach_jira_or_confluence(
    catalogue: Catalogue, bad: Json, code: str
):
    found = problems(catalogue, plan([bad], [], [setting("where", "text", "x")]))

    assert code in [p.code for p in found], [p.text for p in found]
    if code == "address_unread":
        assert "Write the address out, so the check can read it" in found[0].text
    if code == "native_write":
        assert USE_OURS in found[0].text


def test_a_graphql_query_that_only_reads_may_reach_atlassian(catalogue: Catalogue):
    read = http(
        "n8n-nodes-base.graphql",
        1.1,
        endpoint="https://api.atlassian.com/graphql",
        query="query { me { name } }",
    )

    assert passed(catalogue, plan([read])).blocks[0].type == "n8n-nodes-base.graphql"


def test_a_block_s_parameters_have_a_size_limit(catalogue: Catalogue):
    huge = {
        "name": "Tell",
        "type": "CUSTOM.wabTell",
        "version": 1,
        "parameters": json.dumps({"where": "channel", "padding": "a" * 30_000}),
    }

    found = problems(catalogue, plan([huge]))

    assert [p.code for p in found] == ["too_big"]


@pytest.mark.parametrize(
    "words",
    [
        "Every day at 9am, but not holidays, check langgraph",
        "Every day at 9am, not on public holidays, check langgraph",
        "Every weekday at 9am but not on holidays, check langgraph",
        "Daily at 9am but not public holidays, check langgraph",
        "Check langgraph every day at 9am, though not on Fridays",
        "Check langgraph every day at 9am though not on Fridays",
        "Every day at 9am, though not on Friday, check langgraph",
        "Check langgraph every day at 9am, but not on holidays",
        "Every Friday at 9am, find tickets in MOCK, no holidays, and raise one ticket",
        "Every day at 9am, though not on Mondays obviously, check langgraph",
        "Every day at 9am, skip Fridays if it is quiet, check langgraph",
        "Check langgraph every day at 9am. Not on public holidays of course.",
    ],
)
def test_a_day_left_out_in_the_schedule_s_own_words_is_always_asked(words: str):
    """A holiday left out, or a day after "though", stands in the schedule's own words, so the
    run time is asked, never filled as every day."""
    assert run_time_in(words) == (None, True)


@pytest.mark.parametrize(
    "words", ["but not holidays", "make it though not on Friday", "run it daily, but not holidays"]
)
def test_a_change_that_leaves_a_day_out_never_keeps_the_run_time(words: str):
    assert run_time_in(words, "monday 09:00") == (None, True)


EVERY_DAY_SET: dict[str, tuple[str | None, str]] = {
    "run_time": ("every_day 09:00", "filled"),
    "repository": ("langchain-ai/langgraph", "filled"),
    "jira_project": ("MOCK", "filled"),
    "channel": ("#support", "filled"),
}


@pytest.mark.parametrize(
    "words",
    [
        "drop Fridays",
        "remove Fridays",
        "cut Fridays",
        "take out Fridays",
        "leave out Fridays",
        "minus Fridays",
        "Fridays excluded",
        "Fridays off",
        "Friday is off",
        "not on Friday's",
        # No list names these words: a day counts only when the words say to run on it.
        "ditch Fridays",
        "scrap Fridays",
        "lose the Fridays",
        "get rid of Fridays",
        "take Fridays out",
        "Fridays are off",
        "Fridays are cancelled",
        "Fridays not needed",
        "Fridays aside",
        "nothing on Fridays",
        "I want Fridays off",
        "please don't bother with Fridays",
        "drop every Friday",
        "remove every Friday",
        "skip Friday's",
        "except Friday's",
        "unless it's a Friday",
        "drop Fridays at 10am",
        "make the release check drop Fridays",
    ],
)
def test_a_change_that_names_a_day_but_not_to_run_on_it_never_makes_it_the_run_day(
    catalogue: Catalogue, words: str
):
    """Before, "drop Fridays", "Fridays off" or "not on Friday's" turned a daily workflow into a
    Friday one, filled, with no question."""
    current = edited(EVERY_DAY_SET)

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == (None, "needed")


@pytest.mark.parametrize(
    "when",
    [
        "Every day at 9am unless it's a Friday",
        "Every day at 9am, unless it is Friday",
        "Every day at 9am except Friday's",
        "Every day at 9am, skip Friday's",
        "Every weekday at 9am except Monday's",
        "Every weekday at 9am, but never on Monday's",
        "Every day at 9am, Friday excluded",
        "Every day at 9am, minus Friday",
        "Every day at 9am, drop Friday",
        "Every day at 9am, Fridays off",
        "Every day at 9am drop Fridays",
        "Every Friday's at 9am",
        "Every Friday at 9am, or Monday if Friday is a holiday",
    ],
)
def test_a_first_draft_that_names_a_day_but_not_to_run_on_it_is_asked(when: str):
    """Before, "unless it's a Friday" and "except Friday's" filled every day at 09:00 and
    dropped the Friday without a word."""
    words = f"{when}, check langchain-ai/langgraph"

    assert run_time_in(words) == (None, True)
    assert day_in(words) is None


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("run it on Fridays", ("friday 09:00", "filled")),
        ("make it Friday", ("friday 09:00", "filled")),
        ("change it to Friday", ("friday 09:00", "filled")),
        ("switch to Fridays", ("friday 09:00", "filled")),
        ("set it for Friday", ("friday 09:00", "filled")),
        ("move it to Fridays please", ("friday 09:00", "filled")),
        ("Fridays instead", ("friday 09:00", "filled")),
        ("only on Fridays", ("friday 09:00", "filled")),
        ("weekdays only", ("weekdays 09:00", "filled")),
        ("make it Fridays at 10am", ("friday 10:00", "filled")),
        ("make it run every Friday", ("friday 09:00", "filled")),
        ("make the release check run Fridays", ("friday 09:00", "filled")),
        ("I want it on Fridays", ("friday 09:00", "filled")),
        ("actually Monday", ("monday 09:00", "filled")),
        ("move the release check to Tuesdays", ("tuesday 09:00", "filled")),
        ("run it by itself every Monday", ("monday 09:00", "filled")),
    ],
)
def test_a_change_that_says_to_run_on_a_day_still_sets_it(
    catalogue: Catalogue, words: str, kept: tuple[str, str]
):
    current = edited(EVERY_DAY_SET)

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == kept


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Summarise Monday's tickets every Friday at 4pm", "friday 16:00"),
        ("Check langchain-ai/langgraph every Friday at 9am", "friday 09:00"),
        ("Find stale tickets in MOCK and post them every Friday at 9am", "friday 09:00"),
        ("Check every Friday at 9am for new langgraph releases", "friday 09:00"),
        ("Fridays at 9am, check langchain-ai/langgraph", "friday 09:00"),
        ("Every day at 9am except weekends, check langgraph", "weekdays 09:00"),
        ("Post deadlines every Friday at 9am", "friday 09:00"),
        ("Every Monday at 9am, raise one ticket with a 5pm deadline", "monday 09:00"),
    ],
)
def test_a_first_draft_that_says_to_run_on_a_day_still_fills_it(words: str, read: str):
    assert run_time_in(words) == (read, True)


MONDAY_SET: dict[str, tuple[str | None, str]] = {
    **EVERY_DAY_SET,
    "run_time": ("monday 09:00", "filled"),
}


@pytest.mark.parametrize(
    ("words", "kept"),
    [
        ("set the due date to Friday at 5pm", (None, "needed")),
        ("the deadline is Friday at 5pm", (None, "needed")),
        ("set the expiry to Friday at 5pm", (None, "needed")),
        ("set the start date to Monday 9am", (None, "needed")),
        ("set the end date to Friday at 5pm", (None, "needed")),
        ("move the deadlines to Fridays at 5pm", (None, "needed")),
        ("raise it with a Friday deadline", (None, "needed")),
        ("make them due by Friday 5pm", (None, "needed")),
        ("raise it for 5pm deadlines", ("monday", "needed")),
        ("make the deadline 5pm", ("monday", "needed")),
        ("give it a 5pm SLA", ("monday", "needed")),
        ("set the due date to Friday at 5pm and run it at 10am", ("monday 10:00", "filled")),
    ],
)
def test_a_ticket_s_due_date_or_deadline_is_never_the_run_time(
    catalogue: Catalogue, words: str, kept: tuple[str | None, str]
):
    """Before, "set the due date to Friday at 5pm" ran the workflow every Friday at 17:00, and
    "raise it for 5pm deadlines" ran it every Monday at 17:00."""
    current = edited(MONDAY_SET)

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == kept


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Check every Friday at 9am", "friday 09:00"),
        ("Post every Friday at 9am", "friday 09:00"),
        ("Report every Monday at 9am", "monday 09:00"),
        ("Summarise every Friday at 4pm", "friday 16:00"),
        ("Close every Friday at 9am", "friday 09:00"),
        ("Archive every Friday at 9am", "friday 09:00"),
        ("Sync every Friday at 9am", "friday 09:00"),
        ("Backup every Friday at 9am", "friday 09:00"),
        ("Clean up every Friday at 9am", "friday 09:00"),
        ("Scan every weekday at 8am", "weekdays 08:00"),
        (
            "Check every Friday at 9am, list tickets in MOCK and raise one ticket that lists them",
            "friday 09:00",
        ),
        ("Check langgraph Fridays at 9am", "friday 09:00"),
        ("post them Fridays at 9am", "friday 09:00"),
        ("Find stale tickets in MOCK Fridays at 9am", "friday 09:00"),
        ("List stale tickets weekdays at 3pm", "weekdays 15:00"),
        ("Send a summary Fridays at 9am", "friday 09:00"),
        ("Send deadline reminders Fridays at 9am", "friday 09:00"),
        ("Check releases Mondays at 9am", "monday 09:00"),
        ("Check releases Monday at 9am", "monday 09:00"),
        ("Check langchain-ai/langgraph for new releases Mondays at 9am", "monday 09:00"),
        ("Remind #ops of the deadline at 9am on Fridays", "friday 09:00"),
        ("Check SLAs on Mondays at 9am", "monday 09:00"),
    ],
)
def test_a_day_with_its_run_time_after_a_task_word_is_the_run_time(words: str, read: str):
    """At acdcef14, a day after the clause's only verb or after a task's own words asked, as
    "Check every Friday at 9am" or "Check langgraph Fridays at 9am", and "the deadline at 9am on
    Fridays" was read as the deadline's. A day whose own phrase holds the time it runs at is
    the run time, whatever task words come before it."""
    assert run_time_in(words) == (read, True)


@pytest.mark.parametrize(
    ("words", "kept", "before"),
    [
        ("check every Friday at 9am", ("friday 09:00", "filled"), EVERY_DAY_SET),
        ("post every Friday at 10am instead", ("friday 10:00", "filled"), EVERY_DAY_SET),
        ("make it Thursday, deadline Friday", ("thursday 09:00", "filled"), MONDAY_SET),
        ("run it Fridays, due date Monday", ("friday 09:00", "filled"), MONDAY_SET),
    ],
)
def test_a_change_with_a_day_and_its_time_or_beside_a_ticket_date_sets_the_right_day(
    catalogue: Catalogue,
    words: str,
    kept: tuple[str, str],
    before: dict[str, tuple[str | None, str]],
):
    """At acdcef14, each asked: a ticket's date across a comma held the schedule's day, and a
    day with its time after a verb was left out."""
    assert marks(catalogue, RELEASE_SETTINGS, words, edited(before))["run_time"] == kept


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("Check every Monday", "monday"),
        ("Check langgraph Mondays", "monday"),
        ("drop every Monday", None),
        ("cancel Mondays", None),
        ("Mondays off", None),
    ],
)
def test_an_untimed_day_after_a_task_word_keeps_the_day_unless_a_word_drops_it(
    words: str, day: str | None
):
    """ "Check every Monday" keeps Monday and asks only the time, as on main; at acdcef14 it
    asked how often too. A word that drops the day, or one after it, still asks how often."""
    assert run_time_in(words) == (None, True)
    assert day_in(words) == day


@pytest.mark.parametrize(
    "words",
    [
        "make the release check drop every Friday",
        "make the release check cancel every Friday",
        "make the release check skip every Friday",
        "make the release check stop every Friday",
        "make the release check pause every Friday",
        "make the release check skip Fridays",
        "drop every Friday at 9am",
        "cancel every Friday at 9am",
        "drop Fridays at 9am",
        "scrap every Monday at 9am",
    ],
)
def test_a_verb_that_drops_a_day_never_makes_it_the_run_day_or_keeps_the_old_one(
    catalogue: Catalogue, words: str
):
    """Before, "make the release check drop every Friday" turned a daily workflow into a Friday
    one, and "make the release check skip Fridays" kept it daily without a word."""
    current = edited(EVERY_DAY_SET)

    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == (None, "needed")


@pytest.mark.parametrize("words", DAYS_LED_BY_AN_UNKNOWN_WORD)
def test_a_day_led_by_a_word_the_reader_doesn_t_know_is_asked(catalogue: Catalogue, words: str):
    """Before, a verb that drops a day and was not on the list of such verbs, as "nix every
    Monday" or "kill Mondays", made that day the run day, in a first draft and as a change."""
    assert day_in(words) is None
    assert run_time_in(words, "every_day 09:00") == (None, True)
    current = edited(EVERY_DAY_SET)
    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == (None, "needed")


@pytest.mark.parametrize(
    "words",
    [
        "nix every Monday at 9am",
        "kill Fridays at 9am",
        "please nix every Monday",
        "I want to nix every Monday",
        "make the release check nix every Monday",
        "make the morning check axe Fridays",
        "make it nix every Friday at 9am",
        "have the check nix every Monday",
        "let the check nix every Monday",
        "get the check to nix every Monday",
        "the check should nix every Monday",
        "the check can nix Mondays",
        "drop the bug report every Monday",
        "Check langgraph and axe every Friday",
        "have the release check axe every Friday",
        "let the morning check nix Mondays",
        "get the check to kill every Monday",
        "have someone nix every Monday",
        "have it nix every Monday",
        "let it skip every Friday",
        "get rid of every Friday",
        "#ops nix every Monday",
        "#ops kill Mondays",
        "#ops axe Fridays at 9am",
    ],
)
def test_a_day_after_a_task_s_words_that_start_with_an_unknown_word_is_asked(
    catalogue: Catalogue, words: str
):
    """Before, each made the day the run day: with its time, after talk or "want to", after
    "make", "have", "let" or "get" and the workflow's name, after "should" or "can", and after
    a known word that an unknown one leads."""
    current = edited(EVERY_DAY_SET)
    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == (None, "needed")


@pytest.mark.parametrize(
    ("words", "read", "day"),
    [
        ("Check every Monday", (None, True), "monday"),
        ("Check langgraph Mondays", (None, True), "monday"),
        ("list new bugs every Monday", (None, True), "monday"),
        ("Check every Friday at 9am", ("friday 09:00", True), "friday"),
        (
            "Every Monday at 9am, list last week's new bugs in one new Jira ticket",
            ("monday 09:00", True),
            "monday",
        ),
        ("run it every weekday at 9", (None, True), "weekdays"),
        (
            "Automatically check LangGraph for new releases every Monday at 9am",
            ("monday 09:00", True),
            "monday",
        ),
        ("I want it posted every Monday", (None, True), "monday"),
        ("make the release check every Friday at 9am", ("friday 09:00", True), "friday"),
        ("Patch Redis every Monday", (None, True), "monday"),
        ("Schedule the release check every Monday at 9am", ("monday 09:00", True), "monday"),
        (
            "Pls check LangGraph for new releases every Monday at 9am",
            ("monday 09:00", True),
            "monday",
        ),
        ("Follow up on stale tickets every Monday at 9am", ("monday 09:00", True), "monday"),
        ("Flag new LangGraph releases every Monday at 9am", ("monday 09:00", True), "monday"),
        ("Escalate stale tickets every Monday at 9am", ("monday 09:00", True), "monday"),
        ("Chase stale tickets every Monday at 9am", ("monday 09:00", True), "monday"),
        (
            "Nudge owners of stale tickets every Monday at 9am",
            ("monday 09:00", True),
            "monday",
        ),
        ("Grab stale tickets in MOCK every Monday at 9am", ("monday 09:00", True), "monday"),
        ("Changelog every Monday at 9am", ("monday 09:00", True), "monday"),
        ("Get me a list of stale tickets every Monday at 9am", ("monday 09:00", True), "monday"),
        (
            "Let me know about new langgraph releases every Monday at 9am",
            ("monday 09:00", True),
            "monday",
        ),
        ("Can you list stale tickets every Monday at 9am", ("monday 09:00", True), "monday"),
    ],
)
def test_a_day_led_by_the_task_s_words_or_by_running_it_keeps_the_day(
    words: str, read: tuple[str | None, bool], day: str
):
    assert run_time_in(words) == read
    assert day_in(words) == day


MONDAY_AT_9 = ("monday 09:00", True)


@pytest.mark.parametrize(
    ("words", "read", "day"),
    [
        ("pls every Monday at 9am", MONDAY_AT_9, "monday"),
        ("plz every Monday at 9am", MONDAY_AT_9, "monday"),
        ("every Monday at 9am pls", MONDAY_AT_9, "monday"),
        ("every Monday at 9am plz", MONDAY_AT_9, "monday"),
        ("check langgraph every Monday pls", (None, True), "monday"),
        ("check langgraph every Monday plz", (None, True), "monday"),
    ],
)
def test_pls_or_plz_beside_the_day_keeps_it(words: str, read: tuple[str | None, bool], day: str):
    """At 105bae9f, "pls" beside the day left the day out, as a day the words drop."""
    assert run_time_in(words) == read
    assert day_in(words) == day


@pytest.mark.parametrize(
    ("words", "read", "day"),
    [
        ("Let me know every Monday at 9am", MONDAY_AT_9, "monday"),
        (
            "Let the team know about new LangGraph releases every Monday at 9am",
            MONDAY_AT_9,
            "monday",
        ),
        ("Let us know about LangGraph releases every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Have a summary ready every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Have it ready every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Have the report sent every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Get alerts every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Get me the stale tickets every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Let #ops know about new releases every Friday at 4pm", ("friday 16:00", True), "friday"),
        ("Have the list posted to #ops every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Have someone check langgraph every Monday", (None, True), "monday"),
        ("Let the team review stale tickets every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Get a digest of new bugs every Monday at 9am", MONDAY_AT_9, "monday"),
        ("Have it emailed to me every Friday at 4pm", ("friday 16:00", True), "friday"),
    ],
)
def test_an_everyday_have_let_or_get_keeps_the_day(
    words: str, read: tuple[str | None, bool], day: str
):
    """At 105bae9f, after "have", "let" or "get" the word right before the day had to be known,
    so "Let me know every Monday at 9am" and "Have the report sent ..." asked the day."""
    assert run_time_in(words) == read
    assert day_in(words) == day


@pytest.mark.parametrize(
    "words",
    [
        "#ops check langgraph every Monday at 9am",
        "post to #ops every Monday at 9am",
        "Have the list posted to #ops every Monday at 9am",
    ],
)
def test_a_channel_beside_a_known_task_word_keeps_the_day(words: str):
    """A channel never starts the task's words, so "#ops nix every Monday" asks, but one beside
    a word the reader knows keeps the day."""
    assert run_time_in(words) == MONDAY_AT_9
    assert day_in(words) == "monday"


@pytest.mark.parametrize(
    "words",
    [
        "Check langgraph except every Monday",
        "check langgraph except Mondays",
        "check langgraph except on Mondays",
        "check it except every Monday",
        "check redis except every Monday",
        "check the repo except every Monday",
        "post it except every Monday",
        "check releases except every Monday",
        "check langgraph excluding Fridays",
        "check langgraph skipping Fridays",
        "check langgraph except weekends",
        "check langgraph not on Fridays",
    ],
)
def test_a_day_left_out_right_after_the_task_s_words_is_asked_in_a_change(
    catalogue: Catalogue, words: str
):
    """Before, with no comma after the task's words, no reader counted the day left out, so a
    change kept the run time from before and dropped the day without a word."""
    assert run_time_in(words, "every_day 09:00") == (None, True)
    assert day_in(words, "every_day 09:00") is None
    current = edited(EVERY_DAY_SET)
    assert marks(catalogue, RELEASE_SETTINGS, words, current)["run_time"] == (None, "needed")


@pytest.mark.parametrize(
    "words",
    [
        "check langgraph, except every Monday",
        "check langgraph but not on Mondays",
        "check langgraph unless it is Friday",
        "check langgraph except the first Monday",
        "check langgraph except every Monday at 10am",
        "check langgraph every day except every Monday",
        "except every Monday",
        "skip every Monday",
    ],
)
def test_a_day_left_out_after_a_mark_or_beside_the_schedule_is_still_asked(words: str):
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "check langgraph without Fridays",
        "check langgraph never on Fridays",
        "check langgraph not Fridays",
        "check langgraph except Fri",
        "check langgraph except public holidays",
        "run it at 10am, check langgraph except Mondays",
        "run it at 10am, check langgraph Friday",
        "post the weekend summary",
        "list holiday tickets",
    ],
)
def test_a_day_when_the_words_give_no_run_day_is_asked_in_a_change(words: str):
    """Before, each kept the day from before in a change, as every_day at 09:00 or at 10:00,
    and dropped the day the words name."""
    assert run_time_in(words, "every_day 09:00") == (None, True)
    assert day_in(words, "every_day 09:00") is None


@pytest.mark.parametrize(
    "words",
    [
        "run it at 10am, summarise Monday's tickets",
        "run it at 10am, list tickets created on Friday",
        "run it at 10am, check the Friday report",
        "make it 10am, deadline Friday",
    ],
)
def test_a_filter_s_or_a_label_s_day_beside_a_new_time_keeps_the_day(words: str):
    assert run_time_in(words, "every_day 09:00") == ("every_day 10:00", True)


@pytest.mark.parametrize(
    "words",
    [
        "every day at 9am, check langgraph except Fridays",
        "every weekday at 9am check langgraph except Fridays",
        "Every Friday at 9am, check langgraph except Fridays",
    ],
)
def test_a_day_left_out_that_the_run_day_covers_is_asked(words: str):
    """Before, each filled the run day it names, in a first draft and as a change, so the
    workflow ran on the very day the person left out."""
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "Every day at 9am, find tickets in MOCK that are not weekend work",
        "Every Friday at 9am, find tickets in MOCK for staff not on holiday",
        "Find tickets labelled mon-fri and post them every Friday at 9am",
    ],
)
def test_a_filter_s_day_the_run_day_may_fall_on_is_asked(words: str):
    """Before, each filled its run day. Code can't tell "not weekend work" from "except
    weekends", and the weekend, a holiday or Monday to Friday may fall on a day it runs, so
    it asks."""
    assert run_time_in(words) == (None, True)


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Every Friday at 9am, list tickets in MOCK we skip on Mondays", "friday 09:00"),
        ("Every Monday at 9am, check langgraph except Fridays", "monday 09:00"),
        ("daily at 9am check langgraph except weekends", "weekdays 09:00"),
    ],
)
def test_a_day_the_run_day_never_falls_on_keeps_it(words: str, read: str):
    assert run_time_in(words) == (read, True)
    assert run_time_in(words, "every_day 09:00") == (read, True)


@pytest.mark.parametrize(
    "words",
    [
        "Every Friday at 9am, check langgraph except Friday's check",
        "every weekday at 9am, check langgraph except your Friday check",
        "Monday to Friday at 9am check langgraph, skip Wednesday's check",
        "every day at 9am, check langgraph but no Friday's check please",
        "run it at 10am, except Friday's check",
        "make it weekdays, but skip Friday's check",
    ],
)
def test_a_label_s_day_after_a_word_that_leaves_it_out_is_asked(words: str):
    """Before, a label held the day, as "Friday's check", even after "except" or "skip", so the
    run time filled and ran on the day left out."""
    assert run_time_in(words)[0] is None
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "Every day at 9am, check langgraph, but we are closed on Fridays",
        "Every day at 9am, check langgraph; the office is closed on Fridays",
        "Every day at 9am, check langgraph, we're done on Fridays",
        "Every day at 9am check langgraph, but only until Friday",
    ],
)
def test_a_day_after_a_filter_s_word_that_filters_nothing_is_asked(words: str):
    """Before, "closed", "done" or "until" held the day as a filter's, with no ticket or other
    thing a filter holds before it."""
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "every day at 9am check langgraph on non-Fridays",
        "every day at 9am check langgraph, non-weekend only",
        "every day at 9am check langgraph except-Fridays",
    ],
)
def test_a_day_inside_a_word_that_leaves_it_out_is_asked(words: str):
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


EVERY_DAY_CHECK = "every day at 9am, check langgraph "


@pytest.mark.parametrize(
    "words",
    [
        *(
            EVERY_DAY_CHECK + rest
            for rest in (
                "except FRI",
                "except SAT and SUN",
                "except sat and sun",
                "except Thrusdays",
                "except Firday",
                "except wkends",
                "except week-ends",
                "except PH",
                "excluding public hols",
                "except during CNY",
                "except on Christmas Day",
                "on business days only",
            )
        ),
        "Every Monday at 9am, check langgraph except SAT-MON",
        "daily at 9am check langgraph except weekends and PH",
        "daily at 9am check langgraph except weekends and Christmas",
    ],
)
def test_a_word_the_reader_doesn_t_know_after_a_word_that_leaves_it_out_is_asked(words: str):
    """Before, a day or a holiday the reader doesn't know, or one listed after the weekend left
    out, was read as nothing, so the run day filled. Code can't know every way to write a day,
    so any word it doesn't know after "except", "not", "skip" or "only" is asked."""
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "every day at 9am, check langgraph, no checks on PH",
        "every day at 9am, check langgraph, skip the check on Christmas",
        "every day at 9am, check langgraph unless it's a PH",
        "every weekday at 9am, check langgraph except PH and our Friday release",
        "Every Friday at 9am, check langgraph but not in December",
        "every day at 9am check langgraph, leave out Friday's check",
    ],
)
def test_a_word_the_reader_doesn_t_know_further_into_what_is_left_out_is_asked(words: str):
    """What a word such as "no" or "skip" leaves out runs to the end of its clause, so a day
    past another word or "on" is asked too."""
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


def test_a_week_day_written_as_two_words_is_asked_in_a_change():
    assert run_time_in("every week day at 9am, check langgraph", "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Every Monday at 9am, list open tickets in MOCK except bugs", "monday 09:00"),
        ("every day at 9am, list tickets that are not done", "every_day 09:00"),
        (
            "Every Friday at 9am, list tickets in MOCK except epics and post them to #ops",
            "friday 09:00",
        ),
        ("every day at 9am, find tickets in MOCK not assigned to me", "every_day 09:00"),
        (
            "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and "
            "create one follow-up ticket",
            "weekdays 15:00",
        ),
        (
            "Every Friday at 2pm, count the PAY bugs closed this week and file one ticket with "
            "the count; I don't want a reminder each time",
            "friday 14:00",
        ),
        ("Every Monday at 9am, list open bugs only", "monday 09:00"),
        (
            "Every Friday at 9am, list open bugs in MOCK unless they are assigned to Bob",
            "friday 09:00",
        ),
        ("Every Monday at 9am, list open bugs, no need to ping me", "monday 09:00"),
        ("Every Monday at 9am, list open bugs without asking me", "monday 09:00"),
        (
            "Every Monday at 9am, check langgraph releases and post to #ops, not Teams",
            "monday 09:00",
        ),
    ],
)
def test_a_filter_left_out_beside_a_run_day_keeps_it(words: str, read: str):
    assert run_time_in(words) == (read, True)
    assert run_time_in(words, "every_day 09:00") == (read, True)


@pytest.mark.parametrize(
    ("words", "read"),
    [
        ("Every Friday at 9am, create a ticket due this Friday", "friday 09:00"),
        ("Every weekday at 9am, list tickets due next Friday", "weekdays 09:00"),
        ("Find tickets from last Monday and post them daily at 9am", "every_day 09:00"),
    ],
)
def test_a_ticket_s_date_or_a_filter_past_next_this_or_last_keeps_the_run_day(
    words: str, read: str
):
    """#339 asked these, because "next", "this" or "last" stood between the day and what
    holds it."""
    assert run_time_in(words) == (read, True)
    assert run_time_in(words, "every_day 09:00") == (read, True)


def test_a_due_date_next_friday_keeps_the_run_day_of_the_desk_eval_case():
    words = (
        "Every Friday, list the open DESK tasks and create one ticket that lists them, due next "
        "Friday"
    )
    assert run_time_in(words, "every_day 09:00") == ("friday 09:00", True)
    assert day_in(words) == "friday"


def asked_both_ways(words: str) -> None:
    assert run_time_in(words) == (None, True)
    assert run_time_in(words, "every_day 09:00") == (None, True)


@pytest.mark.parametrize(
    "words",
    [
        "Every day at 9am, check langgraph releases until next Friday",
        "Every day at 9am, remind #ops about open tickets until next Friday",
        "Every day at 9am, post open bugs until this Friday",
        "Every day at 9am, check langgraph till the release deadline next Friday",
        "Every day at 9am check langgraph, ending at the deadline next Friday",
        "Every day at 9am, check langgraph releases from next Monday",
        "Every day at 9am, post open bugs until Friday",
        "Every day at 9am check langgraph, the deadline next Friday is a day off",
    ],
)
def test_a_day_past_next_this_or_last_is_held_only_by_a_due_date_that_ends_its_words(words: str):
    """A filter's word as "until" or "from" holds no day past "next" or "this", and "until" or
    "till" hold none at all, since they end the runs. A due date past "next" holds the day only
    when nothing follows it, as "tickets due next Friday"."""
    asked_both_ways(words)


@pytest.mark.parametrize(
    "words",
    [
        "Every day at 9am, list tickets due next Friday, then stop",
        "Every day at 9am, remind me of tickets due next Friday and stop after that",
        "Every day at 9am, check langgraph, tickets due next Friday excluded",
    ],
)
def test_a_stop_or_a_word_that_leaves_it_out_after_a_due_date_undoes_its_hold(words: str):
    asked_both_ways(words)


def test_a_due_date_alone_keeps_the_run_day_beside_the_same_words_with_a_stop():
    assert run_time_in("Every day at 9am, list tickets due next Friday") == (
        "every_day 09:00",
        True,
    )
    asked_both_ways("Every day at 9am, list tickets due next Friday, then stop")


@pytest.mark.parametrize(
    "rest",
    [
        "except when I'm off",
        "except when I'm away",
        "unless I'm off",
        "except when we are closed",
        "except during releases",
        "except during an incident",
        "unless there is a release",
        "except while patching",
        "except during my shift",
    ],
)
def test_a_stretch_of_time_left_out_with_known_words_is_asked(rest: str):
    """ "when", "while" and "during" start a stretch of time, and "off", "closed" or "release"
    name one, so what they leave out may be days the workflow runs on."""
    asked_both_ways(EVERY_DAY_CHECK + rest)


@pytest.mark.parametrize(
    "rest", ["except for 2 days", "except for 1 week", "skip 2 days after a release"]
)
def test_a_count_of_days_left_out_is_asked(rest: str):
    asked_both_ways(EVERY_DAY_CHECK + rest)


@pytest.mark.parametrize(
    "rest",
    [
        "except: PH",
        "except (PH)",
        "except... PH",
        "except; PH",
        "except, as always, Friday's check",
        "except, well, the Friday check",
    ],
)
def test_a_mark_right_after_a_word_that_leaves_something_out_never_ends_what_it_covers(
    rest: str,
):
    asked_both_ways(EVERY_DAY_CHECK + rest)


@pytest.mark.parametrize(
    "rest", ["on business days", "on workdays", "on working days", "just on business days"]
)
def test_days_the_reader_doesn_t_know_after_on_are_asked(rest: str):
    asked_both_ways(EVERY_DAY_CHECK + rest)


@pytest.mark.parametrize(
    "rest",
    [
        "don't run on PH",
        "won't run on PH",
        "pause on PH",
        "drop PH",
        "minus PH",
        "leave out PH",
        "omit PH",
        "avoid PH",
        "ignore PH",
        "stop on PH",
        "hold off on PH",
        "with the exception of PH",
        "excl. PH",
        "w/o PH",
        "PH excluded",
        "PH off",
        "PH skip",
        "PH no need",
        "PH don't run",
    ],
)
def test_other_words_that_leave_something_out_before_or_after_it_are_asked(rest: str):
    asked_both_ways(EVERY_DAY_CHECK + rest)


@pytest.mark.parametrize(
    ("words", "read"),
    [
        (
            "Every Monday at 9am, find tickets in MOCK not updated during the weekend",
            "monday 09:00",
        ),
        ("Every Monday at 9am, find tickets in MOCK not updated in 10 days", "monday 09:00"),
        ("Every Monday at 9am, list bugs older than 30 days, not done", "monday 09:00"),
        ("Every day at 9am, list tickets created on Monday", "every_day 09:00"),
        ("Every Monday at 9am, post the summary on Teams", "monday 09:00"),
        ("Every Monday at 9am, list open bugs and pause the React check", "monday 09:00"),
        ("Every Monday at 9am, list open bugs, don't ask me", "monday 09:00"),
        ("Every Monday at 9am, list open bugs and turn the alerts off", "monday 09:00"),
    ],
)
def test_known_words_beside_these_exclusion_rules_keep_the_run_day(words: str, read: str):
    """A day the run never falls on after "during", a count a filter holds, a day after "on",
    a thing a verb such as "pause" acts on, a negated verb that is not "run", and "off" after
    known words all keep the run day."""
    assert run_time_in(words) == (read, True)
    assert run_time_in(words, "every_day 09:00") == (read, True)
