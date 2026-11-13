"""The Planner's layouts, as the drafts the platform saves in n8n (ENGINE-PLAN 2.5).

Each draft must match its golden document in tests/golden/n8n/. After a deliberate change, run
`UPDATE_GOLDEN=1 uv run pytest tests/test_layout.py` and read the diff before committing it."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.layout import (
    CREATE_TICKET,
    NEWER,
    LayoutPlan,
    PlannedAgent,
    agent_cards,
    lay_out,
    watchlist,
)
from platform_api.builder.n8n_draft import (
    CHECKING,
    EVERY_WRITE,
    FIT,
    Checked,
    DraftRefused,
    check_draft,
)
from platform_api.orchestration import ASK_EXITS, Schedule, grade

GOLDEN = Path(__file__).parent / "golden" / "n8n"
ERROR_WORKFLOW = "wfErrorReporter01"
LINK = "https://portal.example/workflows/uc_01JB8RELEASE"
CHECKER = PlannedAgent(
    VERSION_CHECKER_ID,
    "Version checker",
    (("GitHub repository", "langchain-ai/langgraph"), ("Jira project", "MOCK")),
    writes=True,
)
DIGEST = PlannedAgent(
    "crd_sprint_digest", "Sprint digest", (("Jira project", "MOCK"),), writes=False
)
RELEASE_CHECK = LayoutPlan(
    "uc_01JB8RELEASE",
    "LangGraph release check",
    LINK,
    Schedule("every_day", "08:00"),
    (CHECKER,),
    ERROR_WORKFLOW,
)
AGENT_CARDS = LayoutPlan(
    "uc_01JB9CARDS",
    "Weekly release and sprint check",
    LINK,
    Schedule("monday", "09:00"),
    (DIGEST, CHECKER),
    ERROR_WORKFLOW,
)
WATCHLIST = LayoutPlan(
    "uc_01JC2WATCH", "Software watchlist", LINK, Schedule("monday", "09:00"), (), ERROR_WORKFLOW
)


def drafted(laid: dict[str, Any], plan: LayoutPlan) -> Checked:
    checked = check_draft(laid, plan.use_case_id, ERROR_WORKFLOW)
    assert isinstance(checked, Checked), checked
    return checked


def matches_golden(name: str, document: dict[str, Any]) -> None:
    path = GOLDEN / f"{name}.json"
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(text)
    assert json.loads(path.read_text()) == document, f"{path.name} differs from the layout"


def edges(document: dict[str, Any]) -> set[tuple[str, int, str]]:
    return {
        (source, index, target["node"])
        for source, outputs in document["connections"].items()
        for index, targets in enumerate(outputs["main"])
        for target in targets
    }


def test_the_release_check_is_the_sketch_s_blocks_with_the_yes_the_checker_added() -> None:
    checked = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK)
    matches_golden("release_check", checked.document)
    names = [node["name"] for node in checked.document["nodes"]]
    assert names == [
        "About this workflow",
        "Daily 8:00",
        "Start from the Portal",
        "Read release",
        "Compare",
        "Newer?",
        "Ask for a yes",
        "Create ticket",
        "Nothing to change",
    ]
    yes = ASK_EXITS.index("Yes")
    quiet = ASK_EXITS.index("Nothing to change")
    assert {
        (NEWER, 0, "Ask for a yes"),
        (NEWER, 1, "Nothing to change"),
        ("Ask for a yes", yes, CREATE_TICKET),
        ("Ask for a yes", quiet, "Nothing to change"),
    } <= edges(checked.document)
    assert checked.graded.grade == "safe"


def test_the_build_log_reads_as_the_sketch_s_set_up_card() -> None:
    checked = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK)
    assert checked.lines == (
        ("check", FIT),
        ("status", CHECKING),
        ("note", "Added a yes before the ticket."),
        ("check", EVERY_WRITE),
    )


def test_agent_cards_run_in_order_and_end_with_the_yes_and_the_write() -> None:
    laid = agent_cards(AGENT_CARDS)
    checked = drafted(laid, AGENT_CARDS)
    matches_golden("agent_cards", checked.document)
    assert ("Sprint digest", 0, "Version checker") in edges(checked.document)
    assert ("Version checker", 0, "Ask for a yes") in edges(checked.document)


def test_agent_cards_that_only_read_have_no_yes_and_no_write() -> None:
    plan = LayoutPlan("uc_reads", "Sprint digest", LINK, None, (DIGEST,), ERROR_WORKFLOW)
    checked = drafted(lay_out(plan), plan)
    kinds = {node["type"] for node in checked.document["nodes"]}
    assert "CUSTOM.wabAskForYes" not in kinds
    assert "CUSTOM.wabMakeApprovedChanges" not in kinds
    assert "n8n-nodes-base.scheduleTrigger" not in kinds, "it runs only by hand"
    assert checked.lines == (("check", FIT),)


def test_the_watchlist_reads_every_watched_software_then_checks_them_at_once() -> None:
    checked = drafted(watchlist(WATCHLIST, "MOCK"), WATCHLIST)
    matches_golden("watchlist", checked.document)
    assert checked.graded.grade == "safe"


def test_the_schedule_always_names_its_hour_and_minute_in_singapore_time() -> None:
    document = lay_out(RELEASE_CHECK)
    [when] = [n for n in document["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    assert when["parameters"] == {
        "rule": {"interval": [{"field": "days", "triggerAtHour": 8, "triggerAtMinute": 0}]}
    }
    assert document["settings"]["timezone"] == "Asia/Singapore"


def test_the_same_use_case_always_gets_the_same_document() -> None:
    assert lay_out(RELEASE_CHECK) == lay_out(RELEASE_CHECK)
    other = LayoutPlan("uc_other", *list(RELEASE_CHECK.__dict__.values())[1:])
    assert lay_out(other)["nodes"][0]["id"] != lay_out(RELEASE_CHECK)["nodes"][0]["id"]


@pytest.mark.parametrize("plan", [RELEASE_CHECK, AGENT_CARDS])
def test_a_layout_on_its_own_would_be_refused_its_writes(plan: LayoutPlan) -> None:
    """The yes is the checker's: without it the layout grades writes_refused."""
    assert grade(lay_out(plan), ERROR_WORKFLOW).grade == "writes_refused"


def test_a_layout_with_a_block_that_is_not_on_is_never_saved() -> None:
    laid = lay_out(RELEASE_CHECK)
    laid["nodes"].append({"id": "h", "name": "Post it", "type": "n8n-nodes-base.httpRequest"})
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW)
    assert isinstance(refused, DraftRefused)
    assert [f.block for f in refused.findings] == ["Post it"]


def test_a_write_the_checker_cannot_put_behind_one_yes_is_never_saved() -> None:
    """A write after an Ask for a yes's No exit gets a second yes in front of it, and two yeses on
    one path need a fix."""
    laid = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK).document
    no = ASK_EXITS.index("No")
    laid["connections"]["Ask for a yes"]["main"][no] = [
        {"node": CREATE_TICKET, "type": "main", "index": 0}
    ]
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW)
    assert isinstance(refused, DraftRefused)
    assert {f.grade for f in refused.findings} == {"needs_a_fix"}
