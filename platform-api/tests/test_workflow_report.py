"""The workflow report (ADR 0051, section 6): the facts code builds of one version of any
workflow, each one checked here against the workflow it came from."""

import json
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, get_args

import pytest

from platform_api.builder.cards import VERSION_CHECKER, VERSION_CHECKER_ID
from platform_api.builder.layout import (
    LayoutPlan,
    PlannedAgent,
    lay_out,
    release_notice,
    slack_notice,
)
from platform_api.builder.models import CardApprovalView, CardView
from platform_api.builder.n8n_draft import Checked, check_draft
from platform_api.builder.workflow_report import (
    TOOL_PLACES,
    AtSetUp,
    CantRunYet,
    Drafted,
    DraftSetting,
    EachRun,
    Filled,
    Guessed,
    Needed,
    Older,
    Quoted,
    Refused,
    SetUp,
    Team,
    Words,
    WorkflowReport,
    workflow_report,
)
from platform_api.orchestration import (
    FLAG_RULES,
    ApproverMayAccept,
    CantRun,
    FixedForYou,
    KnownOptions,
    Schedule,
    ToolId,
    WorkflowPlan,
)
from tests.support import TEAM_ZONE

GOLDEN = Path(__file__).parent / "golden" / "n8n"
ERROR_WORKFLOW = "wfErrorReporter01"
LINK = "https://portal.example/workflows/uc"
PAT = "jiraSoftwareServerPatApi"
SLACK_KEY = "wab-slack-send"
JIRA_KEY = "wab-jira-read"
KNOWN = KnownOptions(
    frozenset({VERSION_CHECKER_ID}),
    {"github_releases": frozenset({"fastapi/fastapi", "facebook/react", "langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK", "WEB"})},
    {VERSION_CHECKER_ID: {"GitHub repository": None, "Jira project": frozenset({"MOCK", "WEB"})}},
    {SLACK_KEY: "slackApi", JIRA_KEY: PAT},
)
TEAM = Team(ERROR_WORKFLOW, TEAM_ZONE, KNOWN)
OVERRIDES = Team(ERROR_WORKFLOW, TEAM_ZONE, KNOWN, override_built=True)
"""Once set-up approvals of flagged workflows exist (ADR 0051, build step 10)."""
CARDS = {VERSION_CHECKER_ID: VERSION_CHECKER}
FAKE_KEY = "_".join(("ghp", "Fak3" * 9))
"""Shaped like a GitHub token, and built here so no scanner takes the file for one."""

type Doc = dict[str, Any]


def checker(repo: str, project: str) -> PlannedAgent:
    values = (("GitHub repository", repo), ("Jira project", project))
    return PlannedAgent(VERSION_CHECKER_ID, "Version checker", values, writes=True)


def saved(laid: Doc, key: str) -> Doc:
    """The layout as the platform saves it, with the checker's yes before each write."""
    checked = check_draft(laid, key, ERROR_WORKFLOW, TEAM_ZONE, KNOWN)
    assert isinstance(checked, Checked), checked
    return checked.document


def fastapi() -> Doc:
    plan = LayoutPlan(
        "uc_fastapi",
        "FastAPI release check",
        LINK,
        Schedule("every_day", "08:00", TEAM_ZONE),
        (checker("fastapi/fastapi", "MOCK"),),
        ERROR_WORKFLOW,
        TEAM_ZONE,
    )
    return saved(lay_out(plan), plan.use_case_id)


def react(text: str = "A new React release is out.") -> Doc:
    plan = LayoutPlan(
        "uc_react",
        "React release check",
        LINK,
        Schedule("monday", "09:00", TEAM_ZONE),
        (checker("facebook/react", "WEB"),),
        ERROR_WORKFLOW,
        TEAM_ZONE,
    )
    notice = slack_notice("Tell #releases", "C0RELEASES", text)
    return saved(release_notice(plan, "facebook/react", "WEB", notice), plan.use_case_id)


def made_in_n8n() -> Doc:
    """Built by hand in n8n: a read of ours first, then n8n's own Jira block creating an issue,
    a Slack post of what the read returned, and an HTTP call with a key typed into it. It has
    no error workflow."""
    return {
        "name": "Weekly FastAPI follow-up",
        "nodes": [
            {
                "name": "Every Monday",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "weeks",
                                "triggerAtDay": [1],
                                "triggerAtHour": 9,
                                "triggerAtMinute": 0,
                            }
                        ]
                    }
                },
            },
            {
                "name": "Read FastAPI",
                "type": "CUSTOM.wabRead",
                "typeVersion": 1,
                "parameters": {"source": "github_releases", "place": "fastapi/fastapi"},
            },
            {
                "name": "Open an issue",
                "type": "n8n-nodes-base.jira",
                "typeVersion": 1,
                "parameters": {"jiraVersion": "serverPat", "operation": "create"},
                "credentials": {PAT: {"id": JIRA_KEY, "name": "Jira"}},
            },
            {
                "name": "Post summary",
                "type": "n8n-nodes-base.slack",
                "typeVersion": 2.7,
                "parameters": {
                    "select": "channel",
                    "channelId": {"__rl": True, "value": "C0TEAM", "mode": "id"},
                    "text": "={{ $('Read FastAPI').item.json.summary }}",
                    "otherOptions": {},
                },
                "credentials": {"slackApi": {"id": SLACK_KEY, "name": "Slack"}},
            },
            {
                "name": "Call the hook",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "parameters": {
                    "method": "POST",
                    "url": "https://hooks.example/deploy",
                    "headerParameters": {
                        "parameters": [{"name": "Authorization", "value": f"Bearer {FAKE_KEY}"}]
                    },
                },
                "credentials": {"httpHeaderAuth": {"id": "x", "name": "x", "data": FAKE_KEY}},
            },
        ],
        "connections": {
            "Every Monday": {"main": [[{"node": "Read FastAPI", "type": "main", "index": 0}]]},
            "Read FastAPI": {
                "main": [
                    [
                        {"node": "Open an issue", "type": "main", "index": 0},
                        {"node": "Call the hook", "type": "main", "index": 0},
                    ]
                ]
            },
            "Open an issue": {"main": [[{"node": "Post summary", "type": "main", "index": 0}]]},
        },
        "settings": {
            "timezone": TEAM_ZONE,
            "saveManualExecutions": True,
            "saveExecutionProgress": True,
        },
    }


def node(document: Doc, name: str) -> dict[str, Any]:
    return next(n for n in document["nodes"] if n["name"] == name)


def text(words: Words | None) -> str:
    """Words as a person reads them, a quoted value in quotes."""
    return "".join(f"“{p.text}”" if isinstance(p, Quoted) else p for p in words or ())


def parts(value: object) -> Iterator[str | Quoted]:
    """Every string in a report, each one either code's own words or a Quoted value."""
    match value:
        case Quoted() | str():
            yield value
        case _ if is_dataclass(value) and not isinstance(value, type):
            for field in fields(value):
                yield from parts(getattr(value, field.name))
        case tuple() | list():
            for item in value:  # pyright: ignore[reportUnknownVariableType]
                yield from parts(item)  # pyright: ignore[reportUnknownArgumentType]
        case _:
            return


def report_of(document: Doc, laid_by: str = "planner", team: Team = TEAM) -> WorkflowReport:
    assert laid_by in ("planner", "n8n")
    return workflow_report(SetUp(laid_by, document, CARDS), team)  # pyright: ignore[reportArgumentType]


def test_the_fastapi_release_check_reads_github_and_writes_jira_after_a_yes() -> None:
    report = report_of(fastapi())
    assert report.name == Quoted("FastAPI release check")
    assert report.grade == "safe"
    assert [(s.name.text, s.ours, s.tag) for s in report.steps] == [
        ("Daily 8:00", False, "Starts it"),
        ("Start from the Portal", True, "Starts it"),
        ("Read release", True, "Reads GitHub"),
        ("Compare", True, "Runs an agent"),
        ("Newer?", False, "Shapes the data"),
        ("Ask for a yes", True, "Waits for a yes"),
        ("Create ticket", True, "Writes after a yes"),
        ("Nothing to change", False, "Ends the run"),
    ], "in run order, without the sticky note"
    assert [(t.action, t.system, t.place, t.block.text) for t in report.touches] == [
        ("reads", "GitHub", Quoted("fastapi/fastapi"), "Read release"),
        ("reads", "GitHub", Quoted("fastapi/fastapi"), "Compare"),
        ("reads", "Jira", Quoted("MOCK"), "Compare"),
        ("writes", "Jira", Quoted("MOCK"), "Create ticket"),
    ]
    assert text(report.in_short) == (
        "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
        "It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else."
    )
    assert [(text((a.block,)), a.decides) for a in report.approves] == [
        ("“Create ticket”", EachRun(1))
    ]
    assert report.flags == ()
    assert report.needs_an_answer == 0


def test_the_react_release_check_posts_its_written_words_in_slack_and_changes_nothing() -> None:
    report = report_of(react())
    assert report.grade == "safe"
    posts = [t for t in report.touches if t.action == "posts"]
    assert [(t.system, t.place, t.block.text) for t in posts] == [
        ("Slack", Quoted("C0RELEASES"), "Tell #releases")
    ]
    assert "“A new React release is out.”" in text(posts[0].phrase), "the words in full"
    assert ("Tell #releases", "Posts in Slack") in [(s.name.text, s.tag) for s in report.steps]
    assert text(report.in_short) == (
        "Every Monday at 9:00, it reads GitHub “facebook/react” and Jira “WEB”. "
        "It posts “A new React release is out.” in Slack “C0RELEASES”. It changes nothing."
    )
    assert report.approves == (), "a post under the Tell rule is not a write"


def test_a_made_in_n8n_workflow_flags_each_of_n8n_s_blocks_and_who_clears_it() -> None:
    report = report_of(made_in_n8n(), "n8n")
    assert report.grade == "needs_a_fix"
    assert [(f.rule, None if f.block is None else f.block.text) for f in report.flags] == [
        ("block_off", "Call the hook"),
        ("operation_off", "Open an issue"),
        ("no_error_workflow", None),
        ("notice_words_expression", "Post summary"),
        ("key_not_made", "Call the hook"),
    ], "in FLAG_RULES order"
    clears = {f.rule: f.clears for f in report.flags}
    assert clears["block_off"] == CantRun()
    assert clears["operation_off"] == CantRun(), "no set-up approval can accept it yet"
    assert clears["notice_words_expression"] == CantRun()
    assert isinstance(clears["no_error_workflow"], FixedForYou)
    assert isinstance(clears["key_not_made"], FixedForYou)
    for flag in report.flags:
        row = FLAG_RULES[flag.rule]
        assert (flag.what, flag.why) == (row.what, row.why)
    takes = {f.rule: f.takes for f in report.flags}
    assert takes["operation_off"] == "This can't run on this platform yet."
    assert takes["block_off"] == (
        "Nobody can clear it in the app. The platform itself would have to change."
    )
    assert "Approver" not in " ".join(takes.values())
    assert report.fixed == (), "code laid out none of it"


def test_once_set_up_approvals_exist_an_approver_may_accept_what_the_table_says() -> None:
    report = report_of(made_in_n8n(), "n8n", OVERRIDES)
    clears = {f.rule: f.clears for f in report.flags}
    assert clears["operation_off"] == FLAG_RULES["operation_off"].clears
    assert isinstance(clears["notice_words_expression"], ApproverMayAccept)
    assert clears["block_off"] == CantRun(), "a block our n8n doesn't load still can't run"
    takes = {f.rule: f.takes for f in report.flags}
    assert takes["operation_off"] == "An Approver may accept it at set-up."
    assert [(a.block.text, a.decides, a.words) for a in report.approves] == [
        ("Open an issue", AtSetUp(), "Runs on the set-up approval, with no yes on each run."),
        ("Post summary", AtSetUp(), "Posts on the set-up approval, with no yes on each run."),
        ("Call the hook", CantRunYet(), "Can't run on this platform yet."),
    ]
    tags = {s.name.text: s.tag for s in report.steps}
    assert (tags["Open an issue"], tags["Call the hook"]) == (
        "Writes on the set-up approval",
        "Can't run on this platform yet",
    )
    assert text(report.in_short) == (
        "Every Monday at 9:00, it reads GitHub “fastapi/fastapi”. "
        "It could change data in Jira through “Open an issue”, with no yes on each run. "
        "It posts what “Read FastAPI” returned in Slack “C0TEAM”, with no yes on each run. "
        "It could change or send data through “Call the hook”, but it can't run on this "
        "platform yet. It changes nothing else."
    )


def test_a_made_in_n8n_workflow_says_what_each_of_n8n_s_blocks_reads_writes_and_posts() -> None:
    report = report_of(made_in_n8n(), "n8n")
    assert [(t.action, t.system, t.place, t.block.text) for t in report.touches] == [
        ("reads", "GitHub", Quoted("fastapi/fastapi"), "Read FastAPI"),
        ("writes", "Jira", None, "Open an issue"),
        ("posts", "Slack", Quoted("C0TEAM"), "Post summary"),
        ("writes", None, None, "Call the hook"),
    ]
    post = next(t for t in report.touches if t.action == "posts")
    assert "“Read FastAPI”" in text(post.phrase), "which block's output the words read"
    assert [(a.block.text, a.decides) for a in report.approves] == [
        ("Open an issue", CantRunYet()),
        ("Post summary", CantRunYet()),
        ("Call the hook", CantRunYet()),
    ], "nothing runs on a set-up approval before set-up approvals exist"
    assert {a.words for a in report.approves} == {"Can't run on this platform yet."}
    assert [(s.name.text, s.ours, s.tag) for s in report.steps] == [
        ("Every Monday", False, "Starts it"),
        ("Read FastAPI", True, "Reads GitHub"),
        ("Open an issue", False, "Can't run on this platform yet"),
        ("Post summary", False, "Posts in Slack"),
        ("Call the hook", False, "Can't run on this platform yet"),
    ]


def test_an_older_version_is_graded_again_under_today_s_rules_beside_its_grade_then() -> None:
    older = react()
    node(older, "Tell #releases")["parameters"]["text"] = "A new React release is out <!channel>"
    report = workflow_report(Older(SetUp("planner", older, CARDS), 2, "safe"), TEAM)
    assert report.then is not None
    assert (report.then.number, report.then.grade) == (2, "safe")
    assert report.grade == "needs_a_fix"
    assert [(f.rule, f.block and f.block.text) for f in report.flags] == [
        ("calls_everyone", "Tell #releases")
    ]
    assert [(a.block.text, a.decides) for a in report.approves] == [
        ("Tell #releases", CantRunYet())
    ]
    later = workflow_report(Older(SetUp("planner", older, CARDS), 2, "safe"), OVERRIDES)
    assert [(a.block.text, a.decides) for a in later.approves] == [("Tell #releases", AtSetUp())], (
        "a post that breaks the Tell rule runs on the set-up approval, once there is one"
    )
    assert report_of(react()).then is None


def test_fixed_for_you_lists_what_code_made_sure_of_only_when_code_laid_it_out() -> None:
    fastapi_report = report_of(fastapi())
    fixed = {c.rule for c in fastapi_report.fixed}
    assert fixed == {
        "no_error_workflow",
        "other_time_zone",
        "test_runs_not_kept",
        "progress_not_saved",
        "no_yes_before_write",
    }, "no key and no block of n8n's to put after ours"
    react_fixed = {c.rule for c in report_of(react()).fixed}
    assert {"not_platform_key", "key_not_made", "runs_before_ours"} <= react_fixed
    assert "no_yes_before_write" not in react_fixed, "it has no write to put a yes before"
    for cleared in fastapi_report.fixed:
        added = FLAG_RULES[cleared.rule].clears
        assert isinstance(added, FixedForYou) and cleared.words == added.added
    by_hand = report_of(fastapi(), "n8n")
    assert by_hand.fixed == ()
    assert fixed <= {c.rule for c in by_hand.passed}


@pytest.mark.parametrize(
    "report",
    [
        pytest.param(lambda: report_of(fastapi()), id="fastapi"),
        pytest.param(lambda: report_of(react()), id="react"),
        pytest.param(lambda: report_of(made_in_n8n(), "n8n"), id="made-in-n8n"),
        *(
            pytest.param(
                lambda path=path: report_of(json.loads(path.read_text())), id=f"golden-{path.stem}"
            )
            for path in sorted(GOLDEN.glob("*.json"))
            if path.stem != "served_types"
        ),
    ],
)
def test_every_rule_shows_once_as_flagged_fixed_or_passed_and_every_write_has_its_approver(
    report: Any,
) -> None:
    made: WorkflowReport = report()
    flagged = {f.rule for f in made.flags}
    fixed = [c.rule for c in made.fixed]
    passed = [c.rule for c in made.passed]
    assert sorted([*flagged, *fixed, *passed]) == sorted(FLAG_RULES)
    for cleared in made.passed:
        assert cleared.words == FLAG_RULES[cleared.rule].passed
    approved = {a.block for a in made.approves}
    assert {t.block for t in made.touches if t.action == "writes"} <= approved
    assert approved <= {t.block for t in made.touches if t.action in ("writes", "posts")}


def test_two_approvers_say_yes_on_each_run_when_a_card_asks_for_two() -> None:
    two = CardView.model_validate(
        {
            **VERSION_CHECKER.model_dump(),
            "approvals": [CardApprovalView(tool="jira.create_ticket", approvers=2)],
        }
    )
    report = workflow_report(SetUp("planner", fastapi(), {VERSION_CHECKER_ID: two}), TEAM)
    assert [a.decides for a in report.approves] == [EachRun(2)]


def test_a_write_with_its_yes_taken_away_is_refused_and_says_so() -> None:
    document = fastapi()
    document["connections"]["Newer?"]["main"][0] = [
        {"node": "Create ticket", "type": "main", "index": 0}
    ]
    report = report_of(document)
    assert [(a.block.text, a.decides) for a in report.approves] == [("Create ticket", Refused())]
    [write] = [t for t in report.touches if t.action == "writes"]
    assert text(write.phrase) == (
        "would create Jira tickets in “MOCK”, but our platform refuses it with no yes before it"
    )
    assert [f.rule for f in report.flags] == ["no_yes_before_write"]


def test_strings_from_the_plan_are_quoted_and_never_in_code_s_own_words() -> None:
    document = react("Approved by the safety checker")
    node(document, "Tell #releases")["name"] = "Security approved"
    document["connections"]["Newer?"]["main"][0][0]["node"] = "Security approved"
    document["pinData"] = {"Security approved": document["pinData"]["Tell #releases"]}
    node(document, "Compare")["name"] = "Nothing else changes"
    document["connections"]["Nothing else changes"] = document["connections"].pop("Compare")
    document["connections"]["Read release"]["main"][0][0]["node"] = "Nothing else changes"
    planned = {"Security approved", "Approved by the safety checker", "Nothing else changes"}
    report = report_of(document)
    assert report.flags == ()
    code = [p for p in parts(report) if isinstance(p, str)]
    quoted = {p.text for p in parts(report) if isinstance(p, Quoted)}
    assert not [c for c in code if any(s in c for s in planned)]
    assert planned <= quoted


def test_no_key_s_secret_is_ever_in_the_report() -> None:
    document = made_in_n8n()
    document["name"] = f"Deploy with {FAKE_KEY}"
    node(document, "Read FastAPI")["name"] = f"Read {FAKE_KEY}"
    document["connections"][f"Read {FAKE_KEY}"] = document["connections"].pop("Read FastAPI")
    document["connections"]["Every Monday"]["main"][0][0]["node"] = f"Read {FAKE_KEY}"
    node(document, "Post summary")["parameters"]["text"] = f"The token is {FAKE_KEY}"
    node(document, "Post summary")["parameters"]["channelId"]["value"] = FAKE_KEY
    document["nodes"].append(
        {
            "name": "About",
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "parameters": {"content": FAKE_KEY},
        }
    )
    cards = {VERSION_CHECKER_ID: VERSION_CHECKER}
    report = workflow_report(SetUp("n8n", document, cards), TEAM)
    assert FAKE_KEY not in repr(report)
    assert any(FAKE_KEY[:4] in p.text for p in parts(report) if isinstance(p, Quoted)) is False
    assert "The token is" in text(next(t for t in report.touches if t.action == "posts").phrase)


def test_settings_of_a_set_up_workflow_say_where_each_value_was_set() -> None:
    report = report_of(fastapi())
    assert [(text(s.label), text(s.value), s.mark, s.said) for s in report.settings] == [
        ("Run time", "every day at 8:00", "set", "Set in the Portal"),
        ("Where “Read release” reads", "“fastapi/fastapi”", "set", "Set in the Portal"),
        ("“GitHub repository” for “Compare”", "“fastapi/fastapi”", "set", "Set in the Portal"),
        ("“Jira project” for “Compare”", "“MOCK”", "set", "Set in the Portal"),
        ("Who says yes on each run", "Any Approver", "set", "Set in the Portal"),
    ]
    by_hand = report_of(made_in_n8n(), "n8n")
    assert {s.said for s in by_hand.settings} == {"Set in n8n"}
    assert ("Where “Post summary” posts", "“C0TEAM”") in [
        (text(s.label), text(s.value)) for s in by_hand.settings
    ]


def drafted(*settings: DraftSetting) -> Drafted:
    return Drafted(fastapi(), CARDS, settings)


def test_a_drafted_workflow_shows_each_setting_s_mark_and_counts_what_needs_an_answer() -> None:
    report = workflow_report(
        drafted(
            DraftSetting("Run time", Needed()),
            DraftSetting("Jira project", Needed()),
            DraftSetting("GitHub repository", Filled("fastapi/fastapi")),
            DraftSetting("Slack channel", Guessed("#eng")),
        ),
        TEAM,
    )
    assert [(text(s.label), text(s.value), s.mark) for s in report.settings] == [
        ("“Run time”", "", "needed"),
        ("“Jira project”", "", "needed"),
        ("“GitHub repository”", "“fastapi/fastapi”", "filled"),
        ("“Slack channel”", "“#eng”", "guessed"),
    ]
    assert report.needs_an_answer == 2
    assert {c.rule for c in report.fixed} == {c.rule for c in report_of(fastapi()).fixed}
    assert (
        workflow_report(drafted(DraftSetting("Run time", Filled("8:00"))), TEAM).needs_an_answer
        == 0
    )


def test_a_drafted_workflow_needs_as_many_answers_as_the_questions_its_card_asks() -> None:
    """The run time a Needed setting stands for also leaves the checker with nothing that
    starts the workflow. That is one question, not two."""
    document = made_in_n8n()
    del document["connections"]["Every Monday"]
    document["nodes"] = [n for n in document["nodes"] if n["name"] != "Every Monday"]
    report = workflow_report(Drafted(document, CARDS, (DraftSetting("Run time", Needed()),)), TEAM)
    assert "nothing_starts" in {f.rule for f in report.flags}
    assert report.needs_an_answer == 1
    set_up = report_of(document, "n8n")
    assert set_up.needs_an_answer == 1, "a set-up workflow's flag that needs an answer"


def test_a_place_still_needed_is_one_question_and_not_a_flag_too() -> None:
    """A placeholder stands where a needed setting goes, and the checker can't allow a place
    nobody has named. Until it is answered, that is the question, not a flag besides."""
    from tests.test_drafted_layout import ERROR_WORKFLOW as LAID_ERROR
    from tests.test_drafted_layout import KNOWN as LAID_KNOWN
    from tests.test_drafted_layout import checked, release_check

    plan = release_check(run_time=None).model_dump()
    plan["settings"][2].update({"value": None, "mark": "needed"})
    document = checked(WorkflowPlan.model_validate(plan))
    team = Team(LAID_ERROR, TEAM_ZONE, LAID_KNOWN)
    report = workflow_report(
        Drafted(
            document,
            {},
            (
                DraftSetting("Run time", Needed()),
                DraftSetting("Jira project", Needed()),
                DraftSetting(("Write key for ", Quoted("Close it")), Needed(), "Needs a write key"),
                DraftSetting("Repository", Filled("a/b"), "From Alice's words"),
                DraftSetting("When", Filled(("every Monday at 9:00",)), "You chose"),
            ),
        ),
        team,
    )

    assert report.flags == ()
    assert report.needs_an_answer == 3
    assert text(report.in_short).startswith("At a run time still needed, it reads GitHub")
    assert [(text(s.label), text(s.value), s.said) for s in report.settings][2:] == [
        ("Write key for “Close it”", "", "Needs a write key"),
        ("“Repository”", "“a/b”", "From Alice's words"),
        ("“When”", "every Monday at 9:00", "You chose"),
    ]


def test_the_report_never_changes_the_workflow_it_is_given() -> None:
    document = made_in_n8n()
    kept = deepcopy(document)
    report_of(document, "n8n")
    assert document == kept


def test_every_tool_names_the_system_it_reaches() -> None:
    assert set(TOOL_PLACES) == set(get_args(ToolId.__value__))


def test_each_source_says_whether_its_set_up_needed_an_approval() -> None:
    assert report_of(fastapi()).approval.startswith("None needed. The Planner laid it out")
    assert report_of(made_in_n8n(), "n8n").approval == (
        "None needed. An Operator with n8n access set it up."
    )
    assert workflow_report(drafted(), TEAM).approval == (
        "It is set up only after an Approver approves it."
    )


def test_a_workflow_the_checker_can_t_read_claims_nothing_passed() -> None:
    report = report_of({"name": "Broken", "nodes": "none"})
    assert [f.rule for f in report.flags] == ["unreadable"]
    assert (report.fixed, report.passed, report.touches, report.approves) == ((), (), (), ())
    assert report.needs_an_answer == 1
    assert "can't read" in text(report.in_short)


def test_a_read_says_its_system_and_place_and_a_post_names_its_platform_key() -> None:
    report = report_of(react())
    [read, *_] = report.touches
    assert text(read.phrase) == "reads GitHub “facebook/react”"
    [post] = [t for t in report.touches if t.action == "posts"]
    assert post.key == "The platform's Slack key, posts only"
    assert read.key is None


def test_a_made_in_n8n_workflow_says_in_short_what_each_of_n8n_s_blocks_can_do() -> None:
    assert text(report_of(made_in_n8n(), "n8n").in_short) == (
        "Every Monday at 9:00, it reads GitHub “fastapi/fastapi”. "
        "It could change data in Jira through “Open an issue”, but it can't run on this "
        "platform yet. "
        "It would post what “Read FastAPI” returned in Slack “C0TEAM”, but it can't run on "
        "this platform yet. "
        "It could change or send data through “Call the hook”, but it can't run on this "
        "platform yet. It changes nothing else."
    )


@pytest.mark.parametrize(
    ("words", "said"),
    [
        ("={{ $json.summary }}", "posts what “Open an issue” returned"),
        ('={{ $node["Read FastAPI"].json.summary }}', "posts what “Read FastAPI” returned"),
        ("={{ $env.SECRET }}", "posts words the run's data picks"),
    ],
    ids=["the-block-before", "named-the-old-way", "nothing-in-this-workflow"],
)
def test_a_post_from_an_expression_names_which_block_s_output_it_reads(
    words: str, said: str
) -> None:
    document = made_in_n8n()
    node(document, "Post summary")["parameters"]["text"] = words
    [post] = [t for t in report_of(document, "n8n", OVERRIDES).touches if t.action == "posts"]
    assert text(post.phrase).startswith(said)


def test_a_post_to_a_place_the_run_s_data_picks_names_no_place() -> None:
    document = made_in_n8n()
    node(document, "Post summary")["parameters"]["channelId"]["value"] = "={{ $json.channel }}"
    report = report_of(document, "n8n")
    [post] = [t for t in report.touches if t.action == "posts"]
    assert post.place is None
    assert "in Slack, in a place the run's data picks" in text(post.phrase)
    assert "notice_place_expression" in {f.rule for f in report.flags}


def test_a_block_for_a_system_the_platform_has_no_key_for_still_says_where_it_posts() -> None:
    document = react()
    node(document, "Tell #releases").update(
        type="n8n-nodes-base.microsoftTeams",
        typeVersion=2,
        parameters={
            "resource": "channelMessage",
            "teamId": {"__rl": True, "value": "T1", "mode": "id"},
            "channelId": {"__rl": True, "value": "C1", "mode": "id"},
            "message": "A new React release is out.",
        },
        credentials={},
    )
    report = report_of(document)
    [post] = [t for t in report.touches if t.action == "posts"]
    assert (post.system, post.place, post.key) == ("Teams", Quoted("T1, C1"), None)
    assert [f.rule for f in report.flags] == ["no_platform_key"]


def test_a_write_counts_only_the_changes_proposed_before_it() -> None:
    document = fastapi()
    document["nodes"].append(
        {
            "name": "Propose for WEB",
            "type": "CUSTOM.wabProposeChange",
            "typeVersion": 1,
            "parameters": {"action": "jira.create_ticket", "place": "WEB"},
        }
    )
    document["connections"]["Create ticket"] = {
        "main": [[{"node": "Propose for WEB", "type": "main", "index": 0}]]
    }
    document["connections"]["Propose for WEB"] = {
        "main": [[{"node": "Nothing to change", "type": "main", "index": 0}]]
    }
    after = [(t.place, t.block.text) for t in report_of(document).touches if t.action == "writes"]
    assert after == [(Quoted("MOCK"), "Create ticket")], "a change proposed after the write"
    del document["connections"]["Create ticket"]
    del document["connections"]["Propose for WEB"]
    document["connections"]["Compare"]["main"][0].append(
        {"node": "Propose for WEB", "type": "main", "index": 0}
    )
    document["connections"]["Propose for WEB"] = {
        "main": [[{"node": "Newer?", "type": "main", "index": 0}]]
    }
    before = [(t.system, t.place) for t in report_of(document).touches if t.action == "writes"]
    assert before == [("Jira", Quoted("MOCK")), ("Jira", Quoted("WEB"))]


def test_a_write_whose_card_names_no_place_says_so() -> None:
    document = fastapi()
    node(document, "Compare")["parameters"]["inputs"]["input"] = [
        {"name": "GitHub repository", "value": "fastapi/fastapi"}
    ]
    [write] = [t for t in report_of(document).touches if t.action == "writes"]
    assert (write.place, text(write.phrase)) == (None, "can create Jira tickets, each after a yes")


def test_a_write_with_no_card_before_it_asks_one_approver_and_makes_what_was_approved() -> None:
    report = report_of(json.loads((GOLDEN / "watchlist.json").read_text()))
    [write] = [t for t in report.touches if t.action == "writes"]
    assert text(write.phrase) == "can make the changes approved in the run, each after a yes"
    assert [a.decides for a in report.approves] == [EachRun(1)]


def test_a_workflow_started_only_from_the_portal_that_reads_nothing_says_so() -> None:
    document: Doc = {
        "name": "Ping the team",
        "nodes": [
            {"name": "Start", "type": "CUSTOM.wabStartFromPortal", "typeVersion": 1},
            {"name": "Tell", "type": "CUSTOM.wabTell", "typeVersion": 1, "parameters": {}},
        ],
        "connections": {"Start": {"main": [[{"node": "Tell", "type": "main", "index": 0}]]}},
        "settings": {},
    }
    assert text(report_of(document).in_short) == (
        "When someone starts it, it runs. It tells the team in its Teams channel. "
        "It changes nothing."
    )


@pytest.mark.parametrize(
    "secret",
    [
        "Basic dXNlcjpwYXNzd29yZA==",
        "=".join(("https://example.com/hook?token", "9f8e7d6c" * 4)),
        "=".join(("https://example.com/hook?api_key", "Zx9-Kq2L" * 2)),
        "https://hooks.slack.com/services/T0/B0/abcDEF123456",
        "https://acme.webhook.office.com/webhookb2/abc@def/IncomingWebhook/123/456",
        "".join(("0123456789", "abcdef0123", "456789abcd", "ef01234567")),
    ],
    ids=["basic-auth", "query-token", "query-api-key", "slack-webhook", "teams-webhook", "hex-40"],
)
def test_a_value_shaped_like_a_key_in_a_post_or_a_place_shows_as_hidden(secret: str) -> None:
    document = made_in_n8n()
    node(document, "Post summary")["parameters"]["text"] = f"Post to {secret}"
    node(document, "Post summary")["parameters"]["channelId"]["value"] = secret
    document["name"] = f"see {secret}"
    report = report_of(document, "n8n")
    assert secret not in repr(report)
    [post] = [t for t in report.touches if t.action == "posts"]
    assert "(hidden, looks like a key)" in text(post.phrase)


@pytest.mark.parametrize(
    "words",
    [
        "Basic settings",
        "Basic approval",
        "monkey=12345678",
        "passkey=whatever1",
        "issuekey=PROJ-1234",
    ],
)
def test_ordinary_words_near_a_key_s_shape_stay_shown(words: str) -> None:
    document = made_in_n8n()
    node(document, "Post summary")["parameters"]["text"] = words
    [post] = [t for t in report_of(document, "n8n").touches if t.action == "posts"]
    assert f"“{words}”" in text(post.phrase)


def test_a_block_off_by_its_version_could_change_or_send_data_and_an_off_write_changes_it() -> None:
    document = react()
    node(document, "Tell #releases")["typeVersion"] = 1
    [post] = [t for t in report_of(document).touches if t.block.text == "Tell #releases"]
    assert (post.action, post.system) == ("writes", "Slack"), (
        "it is Slack's block, doing who knows what"
    )
    assert text(post.phrase).startswith("could change or send data through “Tell #releases”")
    [write] = [t for t in report_of(made_in_n8n(), "n8n").touches if t.system == "Jira"]
    assert text(write.phrase).startswith("could change data in Jira through “Open an issue”")


def test_a_place_held_in_a_collection_shows_its_value() -> None:
    document = react()
    node(document, "Tell #releases")["parameters"]["channelId"] = {"value": "C9", "mode": "id"}
    [post] = [t for t in report_of(document).touches if t.action == "posts"]
    assert post.place == Quoted("C9")


def test_a_write_with_its_yes_and_a_flag_of_another_kind_still_waits_for_its_yes() -> None:
    document = fastapi()
    node(document, "Create ticket")["credentials"] = {"jiraApi": {"id": "alices", "name": "x"}}
    report = report_of(document)
    assert [f.rule for f in report.flags] == ["key_not_made"]
    assert [(a.block.text, a.decides) for a in report.approves] == [("Create ticket", EachRun(1))]
