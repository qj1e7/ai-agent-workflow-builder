"""Edit in n8n's read-back (ADR 0051, flow step 6): code reads the workflow a person changed in
their own n8n space back into a plan. A value they typed in n8n counts as filled by them only once
it passes the same check as in the chat, a placeholder they left is still needed, and anything
the plan can't hold comes back as words, never dropped."""

from copy import deepcopy
from typing import Any

from platform_api.builder.drafted_in_n8n import NotReadBack, ReadBack, read_back
from platform_api.builder.drafted_settings import Source
from platform_api.orchestration import DrafterFacts, WorkflowPlan
from platform_api.shared import UserId
from tests.test_drafted_layout import ZONE, checked, nodes, release_check

FACTS = DrafterFacts(
    jira_projects=["MOCK", "OPS"],
    repositories=["langchain-ai/langgraph"],
    channels=["#support"],
)
DAN = UserId("dan")
BEFORE = release_check()


def edited(change: Any = None) -> dict[str, Any]:
    document = deepcopy(checked(BEFORE))
    for node in document["nodes"]:
        node.pop("credentials", None)
    if change is not None:
        change(document)
    return document


def back(document: dict[str, Any], before: WorkflowPlan = BEFORE) -> ReadBack:
    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)
    assert isinstance(read, ReadBack), read
    return read


def settings(read: ReadBack) -> dict[str, tuple[str | None, str]]:
    return {s.id: (s.value, s.mark) for s in read.plan.settings}


def test_a_workflow_nobody_changed_reads_back_as_the_plan_it_was():
    read = back(edited())

    assert read.plan.blocks == BEFORE.blocks
    assert read.plan.wires == BEFORE.wires
    assert read.plan.settings == BEFORE.settings
    assert read.plan.name == BEFORE.name
    assert read.sources == {}


def test_a_value_typed_in_n8n_is_filled_by_them_once_it_passes_the_check():
    def to_ops(document: dict[str, Any]) -> None:
        nodes(document)["Propose a ticket"]["parameters"]["place"] = "OPS"

    read = back(edited(to_ops))

    assert settings(read)["jira_project"] == ("OPS", "filled")
    assert read.sources["jira_project"] == Source("OPS", "n8n", DAN)


def test_a_typed_value_the_check_refuses_is_still_needed():
    def to_secret(document: dict[str, Any]) -> None:
        nodes(document)["Propose a ticket"]["parameters"]["place"] = "SECRET"

    read = back(edited(to_secret))

    assert settings(read)["jira_project"] == (None, "needed")
    propose = next(b for b in read.plan.blocks if b.name == "Propose a ticket")
    assert propose.parameters["place"] == "<<jira_project>>"


def test_a_run_time_changed_in_n8n_is_read_from_its_schedule():
    def to_friday(document: dict[str, Any]) -> None:
        rule = nodes(document)["Every Monday"]["parameters"]["rule"]
        rule["interval"][0].update({"triggerAtDay": [5], "triggerAtHour": 17})

    read = back(edited(to_friday))

    assert settings(read)["run_time"] == ("friday 17:00", "filled")
    assert read.sources["run_time"] == Source("friday 17:00", "n8n", DAN)


def test_a_placeholder_left_in_n8n_is_still_needed():
    before = release_check(run_time=None)
    read = read_back(edited_from(before), before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, ReadBack)
    assert settings(read)["run_time"] == (None, "needed")


def edited_from(plan: WorkflowPlan) -> dict[str, Any]:
    document = deepcopy(checked(plan))
    for node in document["nodes"]:
        node.pop("credentials", None)
    return document


def test_a_slack_post_added_in_n8n_takes_a_channel_the_platform_can_see():
    def post(channel: str) -> Any:
        def add(document: dict[str, Any]) -> None:
            document["nodes"].append(
                {
                    "id": "n-post",
                    "name": "Tell support",
                    "type": "n8n-nodes-base.slack",
                    "typeVersion": 2.3,
                    "position": [0, 0],
                    "parameters": {
                        "resource": "message",
                        "operation": "post",
                        "select": "channel",
                        "channelId": {"__rl": True, "mode": "name", "value": channel},
                        "text": "Done.",
                    },
                }
            )
            document["connections"]["Make the ticket"] = {
                "main": [[{"node": "Tell support", "type": "main", "index": 0}]]
            }

        return add

    seen = back(edited(post("#support")))
    [channel] = [s for s in seen.plan.settings if s.kind == "channel"]
    assert (channel.value, channel.mark) == ("#support", "filled")
    assert seen.sources[channel.id] == Source("#support", "n8n", DAN)

    unseen = back(edited(post("#random")))
    [channel] = [s for s in unseen.plan.settings if s.kind == "channel"]
    assert (channel.value, channel.mark) == (None, "needed")


def test_a_block_deleted_in_n8n_takes_its_setting_with_it():
    def drop_read(document: dict[str, Any]) -> None:
        document["nodes"] = [n for n in document["nodes"] if n["name"] != "Read new releases"]
        document["connections"].pop("Read new releases", None)
        document["connections"]["Every Monday"] = {
            "main": [[{"node": "Propose a ticket", "type": "main", "index": 0}]]
        }

    read = back(edited(drop_read))

    assert "repository" not in settings(read)
    assert ("Every Monday", "Propose a ticket") in {
        (w.from_block, w.to_block) for w in read.plan.wires
    }


def test_what_the_plan_can_t_hold_comes_back_as_words_never_dropped():
    def goes_on(document: dict[str, Any]) -> None:
        nodes(document)["Read new releases"]["onError"] = "continueRegularOutput"

    def tool_link(document: dict[str, Any]) -> None:
        document["connections"]["Read new releases"]["ai_tool"] = [
            [{"node": "Propose a ticket", "type": "ai_tool", "index": 0}]
        ]

    for change, said in ((goes_on, "onError"), (tool_link, "ai_tool")):
        read = read_back(edited(change), BEFORE, checked(BEFORE), FACTS, DAN, ZONE)
        assert isinstance(read, NotReadBack)
        assert said in read.words
