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
from tests.test_drafted_layout import ZONE, block, checked, nodes, release_check, setting, wire

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
    assert (read.sources, read.notes) == ({}, ())


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
    assert read.notes == (
        "You typed “SECRET” in n8n for “jira project”, but that isn't one of the team's Jira "
        "projects. So it's asked again.",
    )


def test_an_expression_where_a_setting_goes_is_asked_again_with_words():
    def expression(document: dict[str, Any]) -> None:
        nodes(document)["Read new releases"]["parameters"]["place"] = "={{ $json.repo }}"

    read = back(edited(expression))

    assert settings(read)["repository"] == (None, "needed")
    assert read.notes == (
        "You put an expression in n8n where “repository” goes. A setting takes a value written "
        "out, so it's asked again.",
    )


def test_two_places_of_one_setting_typed_differently_keep_the_first_and_say_so():
    plan = release_check().model_dump()
    plan["blocks"].append(
        block("Read again", "CUSTOM.wabRead", 1, source="github_releases", place="<<repository>>")
    )
    plan["wires"].append(wire("Every Monday", "Read again"))
    plan["settings"][1]["fills"].append({"block": "Read again", "parameter": "place"})
    before = WorkflowPlan.model_validate(plan)
    document = edited_from(before)
    nodes(document)["Read new releases"]["parameters"]["place"] = "fastapi/fastapi"
    nodes(document)["Read again"]["parameters"]["place"] = "pydantic/pydantic"

    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, ReadBack)
    assert settings(read)["repository"] == ("fastapi/fastapi", "filled")
    assert read.notes == (
        "You typed “fastapi/fastapi” and “pydantic/pydantic” in n8n for “repository”. It holds "
        "one value, so “fastapi/fastapi” is kept.",
    )


def test_a_key_picked_on_a_block_in_n8n_is_not_kept_and_says_so():
    def pick(document: dict[str, Any]) -> None:
        nodes(document)["Propose a ticket"]["credentials"] = {
            "jiraSoftwareCloudApi": {"id": "my-own", "name": "Mine"}
        }

    read = back(edited(pick))

    assert read.notes == (
        "The key picked on “Propose a ticket” in n8n isn't kept. The platform puts on only the "
        "keys it may use.",
    )


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
    assert unseen.notes == (
        "You typed “#random” in n8n for “Slack channel”, but that isn't a Slack channel the "
        "platform's key can see. So it's asked again.",
    )


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

    def no_name(document: dict[str, Any]) -> None:
        del nodes(document)["Read new releases"]["name"]

    for change, said in ((goes_on, "onError"), (tool_link, "ai_tool"), (no_name, "no name")):
        read = read_back(edited(change), BEFORE, checked(BEFORE), FACTS, DAN, ZONE)
        assert isinstance(read, NotReadBack)
        assert said in read.words


def with_slack(channel: str | None) -> WorkflowPlan:
    """The release check with a Slack post whose channel is a setting, needed when None."""
    plan = release_check().model_dump()
    plan["blocks"].append(
        block(
            "Tell support",
            "n8n-nodes-base.slack",
            2.3,
            resource="message",
            operation="post",
            select="channel",
            channelId={"__rl": True, "mode": "name", "value": "<<channel_1>>"},
            text="Done.",
        )
    )
    plan["wires"].append(wire("Make the ticket", "Tell support"))
    plan["settings"].append(
        setting("channel_1", "channel", channel, "Tell support", "channelId.value")
    )
    return WorkflowPlan.model_validate(plan)


def renamed(old: str, new: str) -> Any:
    """n8n's editor renames a block in place: its id stays, and every link follows the name."""

    def rename(document: dict[str, Any]) -> None:
        for node in document["nodes"]:
            if node["name"] == old:
                node["name"] = new
        if old in document["connections"]:
            document["connections"][new] = document["connections"].pop(old)
        for outputs in document["connections"].values():
            for targets in outputs.get("main", []):
                for target in targets:
                    if target["node"] == old:
                        target["node"] = new

    return rename


def test_a_block_renamed_in_n8n_keeps_its_settings_needed_or_filled():
    before = with_slack(None)
    document = edited_from(before)
    renamed("Tell support", "Post to Slack")(document)
    renamed("Propose a ticket", "Propose it")(document)

    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, ReadBack), read
    marks = {s.id: (s.value, s.mark, [f.block for f in s.fills]) for s in read.plan.settings}
    assert marks["channel_1"] == (None, "needed", ["Post to Slack"])
    assert marks["jira_project"] == ("MOCK", "filled", ["Propose it"])
    propose = next(b for b in read.plan.blocks if b.name == "Propose it")
    assert propose.parameters["place"] == "<<jira_project>>"


def added(
    document: dict[str, Any], name: str, node_type: str, version: float, **parameters: Any
) -> None:
    document["nodes"].append(
        {
            "id": f"n-{name}",
            "name": name,
            "type": node_type,
            "typeVersion": version,
            "position": [0, 0],
            "parameters": parameters,
        }
    )
    document["connections"].setdefault("Make the ticket", {"main": [[]]})["main"][0].append(
        {"node": name, "type": "main", "index": 0}
    )


SLACK_POST = {
    "resource": "message",
    "operation": "post",
    "select": "channel",
    "text": "Again.",
}


def test_a_placeholder_moved_to_another_place_of_its_kind_takes_its_setting_along():
    before = with_slack(None)
    document = edited_from(before)
    channel_id = {"__rl": True, "mode": "name", "value": "<<channel_1>>"}
    added(document, "Tell again", "n8n-nodes-base.slack", 2.3, channelId=channel_id, **SLACK_POST)

    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, ReadBack), read
    [channel] = [s for s in read.plan.settings if s.id == "channel_1"]
    assert {(f.block, f.parameter) for f in channel.fills} == {
        ("Tell support", "channelId.value"),
        ("Tell again", "channelId.value"),
    }


def test_a_repository_s_placeholder_moved_to_where_a_channel_goes_is_refused():
    before = with_slack(None)
    document = edited_from(before)
    nodes(document)["Tell support"]["parameters"]["channelId"]["value"] = "<<repository>>"

    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, NotReadBack), read
    assert read.words == (
        "<<repository>> moved to a place that takes a Slack channel, in “Tell support”. Put it "
        "back, or type the Slack channel in n8n, then press Done in n8n again."
    )


def test_a_channel_s_placeholder_moved_to_where_an_address_goes_is_refused():
    before = with_slack(None)
    document = edited_from(before)
    gmail = {"resource": "message", "operation": "send", "subject": "S", "message": "M"}
    added(document, "Mail it", "n8n-nodes-base.gmail", 2.1, sendTo="<<channel_1>>", **gmail)

    read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

    assert isinstance(read, NotReadBack), read
    assert read.words.startswith("<<channel_1>> moved to a place that takes an address")


def test_a_placeholder_moved_to_a_place_no_setting_fills_is_refused():
    before = with_slack(None)
    for move in ("http", "text"):
        document = edited_from(before)
        if move == "http":
            added(document, "Call it", "n8n-nodes-base.httpRequest", 4.2, url="<<channel_1>>")
        else:
            nodes(document)["Tell support"]["parameters"]["text"] = "<<channel_1>>"

        read = read_back(document, before, checked(before), FACTS, DAN, ZONE)

        assert isinstance(read, NotReadBack), (move, read)
        assert "moved to a place no setting fills" in read.words


def test_a_placeholder_nothing_fills_comes_back_as_words():
    def stray(document: dict[str, Any]) -> None:
        nodes(document)["Read new releases"]["parameters"]["place"] = "<<nobody_fills_this>>"

    read = read_back(edited(stray), BEFORE, checked(BEFORE), FACTS, DAN, ZONE)

    assert isinstance(read, NotReadBack)
    assert "“Read new releases”" in read.words and "nothing fills" in read.words
