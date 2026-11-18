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
from agent_runtime.plan_settings import run_time_in
from agent_runtime.workflow_drafter import check_plan
from agent_runtime.workflow_plan import NEVER_GUESSED, USE_OURS, ProposedPlan

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


def test_a_switch_s_exits_follow_its_rules_and_a_written_count_is_held(catalogue: Catalogue):
    rules = {"values": [{"outputKey": "a"}, {"outputKey": "b"}]}
    switch = block("Route", "n8n-nodes-base.switch", 3.4, rules=rules)
    targets = [block(f"Tell {n}", "CUSTOM.wabTell", 1) for n in (1, 2)]
    wires = [wire("Route", "Tell 1", "rule 1"), wire("Route", "Tell 2", "Rule 2")]

    done = passed(catalogue, plan([switch, *targets], wires))
    assert [w.exit_index for w in done.wires] == [0, 1]
    huge = block("Route", "n8n-nodes-base.switch", 3.4, mode="expression", numberOutputs=10**9)
    out_of_range = plan([huge, targets[0]], [wire("Route", "Tell 1", "output 81")])
    assert any("has the exits" in p.text for p in problems(catalogue, out_of_range))


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
