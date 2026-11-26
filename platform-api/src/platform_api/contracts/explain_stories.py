import json
from pathlib import Path
from typing import Any, cast

from platform_api.builder.cards import VERSION_CHECKER, VERSION_CHECKER_ID
from platform_api.builder.explain import to_smooth
from platform_api.builder.workflow_report import SetUp, Team, workflow_report
from platform_api.orchestration import CodeWording, KnownOptions
from platform_api.shared import TEAM_TIME_ZONE
from platform_api.wire import WireModel

GOLDEN = Path(__file__).parents[3] / "tests" / "golden" / "n8n"
ERROR_WORKFLOW = "wfErrorReporter01"
ZONE = TEAM_TIME_ZONE.key
PAT = "jiraSoftwareServerPatApi"
SLACK_KEY = "wab-slack-send"
JIRA_KEY = "wab-jira-read"
CARDS = {VERSION_CHECKER_ID: VERSION_CHECKER}
KNOWN = KnownOptions(
    frozenset({VERSION_CHECKER_ID}),
    {"github_releases": frozenset({"fastapi/fastapi", "facebook/react", "langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK", "WEB"})},
    {VERSION_CHECKER_ID: {"GitHub repository": None, "Jira project": frozenset({"MOCK", "WEB"})}},
    {SLACK_KEY: "slackApi", JIRA_KEY: PAT},
)
TODAY = Team(ERROR_WORKFLOW, ZONE, KNOWN)


def explain_fixtures() -> dict[str, WireModel]:
    """What code asks the AI model to smooth for each golden n8n workflow, which the runtime's
    smoothing is tested against. The set-up approval smooths a report the same way."""
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
