import json
from pathlib import Path
from typing import Any, cast

from platform_api.builder.cards import VERSION_CHECKER, VERSION_CHECKER_ID
from platform_api.builder.explain import to_smooth, view_of
from platform_api.builder.layout import LayoutPlan, PlannedAgent, lay_out
from platform_api.builder.n8n_draft import Checked, check_draft
from platform_api.builder.workflow_report import Older, SetUp, Team, workflow_report
from platform_api.orchestration import CodeWording, KnownOptions, Schedule
from platform_api.shared import TEAM_TIME_ZONE
from platform_api.wire import WireModel

GOLDEN = Path(__file__).parents[3] / "tests" / "golden" / "n8n"
ERROR_WORKFLOW = "wfErrorReporter01"
ZONE = TEAM_TIME_ZONE.key
USE_CASE_ID = "uc_01JFASTAPI"
NAME = "FastAPI release check"
CARDS = {VERSION_CHECKER_ID: VERSION_CHECKER}
KNOWN = KnownOptions(
    frozenset({VERSION_CHECKER_ID}),
    {"github_releases": frozenset({"fastapi/fastapi", "facebook/react", "langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK", "WEB"})},
    {VERSION_CHECKER_ID: {"GitHub repository": None, "Jira project": frozenset({"MOCK", "WEB"})}},
    {"wab-slack-send": "slackApi", "wab-jira-read": "jiraSoftwareServerPatApi"},
)
TODAY = Team(ERROR_WORKFLOW, ZONE, KNOWN)
LAID = check_draft(
    lay_out(
        LayoutPlan(
            USE_CASE_ID,
            NAME,
            f"https://portal.example/workflows/{USE_CASE_ID}",
            Schedule("every_day", "08:00", ZONE),
            (
                PlannedAgent(
                    VERSION_CHECKER_ID,
                    "Version checker",
                    (("GitHub repository", "fastapi/fastapi"), ("Jira project", "MOCK")),
                    True,
                ),
            ),
            ERROR_WORKFLOW,
            ZONE,
        )
    ),
    USE_CASE_ID,
    ERROR_WORKFLOW,
    ZONE,
    KNOWN,
)
assert isinstance(LAID, Checked)
FASTAPI = SetUp("planner", LAID.document, CARDS)
REWORDED = (
    "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can create Jira "
    "tickets in “MOCK”, each after a yes, and changes nothing else."
)


def explain_fixtures() -> dict[str, WireModel]:
    in_use = workflow_report(FASTAPI, TODAY)
    moved_on = Team("wfNewErrorReporter", ZONE, KNOWN)
    older = workflow_report(Older(FASTAPI, 1, "safe"), moved_on)
    return {
        "builder/explain.json": view_of(in_use, USE_CASE_ID, NAME, 1, n8n_access=False),
        "builder/explain.older.json": view_of(older, USE_CASE_ID, NAME, 1, n8n_access=True),
        "builder/explain.reworded.json": view_of(
            in_use, USE_CASE_ID, NAME, 1, n8n_access=False, reworded=REWORDED
        ),
        **smoothing_requests_without_the_model(),
    }


def smoothing_requests_without_the_model() -> dict[str, WireModel]:
    asked: dict[str, WireModel] = {}
    for path in sorted(GOLDEN.glob("*.json")):
        document: object = json.loads(path.read_text())
        if not isinstance(document, dict):
            continue
        laid = SetUp("planner", cast(dict[str, Any], document), CARDS)
        smoothing = to_smooth(workflow_report(laid, TODAY))
        assert isinstance(smoothing, CodeWording), path
        asked[f"builder/explain-wording.{path.stem}.json"] = smoothing
    return asked
