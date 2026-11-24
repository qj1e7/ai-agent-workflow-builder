"""The stopped version as the plan the Fix drafter takes as its current one (ADR 0055, PR 4).
`read_back_any` reads any workflow in n8n: one from our blocks, one made in n8n, and a drafted one
as it was laid out. A drafted workflow's own revision goes through `keys_kept_out` alone. Either
way no key leaves platform-api: a value counts as a key by its name as well as by its shape."""

import json
from copy import deepcopy
from typing import Any

import pytest

from platform_api.builder.drafted_in_n8n import NotReadBack, ReadBack, read_back_any
from platform_api.builder.kept_keys import (
    KEPT,
    SECRET_NAME_ENDS,
    KeptPlace,
    keys_kept_out,
)
from platform_api.orchestration import DrafterFacts, WorkflowPlan
from tests.support import FIXTURES
from tests.test_drafted_layout import ZONE, laid, release_check
from tests.test_layout import GOLDEN

FACTS = DrafterFacts(
    jira_projects=["MOCK"], repositories=["langchain-ai/langgraph"], channels=["#support"]
)
# Each built at run time, so no secret scanner reads one as leaked. None is a real key.
PASSWORD = "plain" + "words" + "42"
TOKEN = "ghp_" + "Ab3dEf9h" * 5
API_KEY = "ak" + "Zq7xYw" * 4


def golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / f"{name}.json").read_text())


def read(document: dict[str, Any]) -> ReadBack:
    found = read_back_any(document, FACTS, ZONE)
    assert isinstance(found, ReadBack), found
    return found


def node(name: str, node_type: str, version: float = 1, **parameters: Any) -> dict[str, Any]:
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "position": [0, 0],
        "parameters": parameters,
    }


def link(*names: str) -> dict[str, Any]:
    return {
        source: {"main": [[{"node": target, "type": "main", "index": 0}]]}
        for source, target in zip(names, names[1:], strict=False)
    }


def made_in_n8n() -> dict[str, Any]:
    """A workflow a person built in n8n: a schedule, two requests with keys typed in, a post."""
    return {
        "name": "Release digest",
        "nodes": [
            node(
                "Every Monday",
                "n8n-nodes-base.scheduleTrigger",
                1.2,
                rule={"interval": [{"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9}]},
            ),
            node(
                "Read releases",
                "n8n-nodes-base.httpRequest",
                4.2,
                method="GET",
                url="https://api.github.com/repos/langchain-ai/langgraph/releases",
                sendHeaders=True,
                headerParameters={
                    "parameters": [
                        {"name": "Authorization", "value": f"token {TOKEN}"},
                        {"name": "Accept", "value": "application/json"},
                    ]
                },
                sendQuery=True,
                queryParameters={"parameters": [{"name": "per_page", "value": "5"}]},
            ),
            node(
                "Read the tracker",
                "n8n-nodes-base.httpRequest",
                4.2,
                method="GET",
                url=f"https://tracker.example.net/api/items?api_key={API_KEY}",
                options={"password": PASSWORD},
                jsonHeaders=json.dumps({"X-Session-Id": API_KEY}),
                sendBody=True,
                body="short note",
            ),
            node(
                "Tell the team",
                "n8n-nodes-base.slack",
                2.3,
                resource="message",
                operation="post",
                select="channel",
                channelId={"__rl": True, "mode": "name", "value": "#support"},
                text="New releases are out",
            ),
        ],
        "connections": link("Every Monday", "Read releases", "Read the tracker", "Tell the team"),
        "settings": {"executionOrder": "v1"},
    }


@pytest.mark.parametrize("name", ["release_check", "release_notice", "agent_cards"])
def test_a_workflow_from_our_blocks_reads_back_without_what_every_layout_adds(name: str):
    document = golden(name)
    found = read(document)
    kept = {b.name for b in found.plan.blocks}
    assert "Start from the Portal" not in kept and "About this workflow" not in kept
    laid_out = {n["name"] for n in document["nodes"]} - {"Start from the Portal"}
    assert kept == laid_out - {"About this workflow"}
    assert found.kept == ()
    assert "run_time" in {s.kind for s in found.plan.settings}


def test_each_place_in_a_workflow_from_our_blocks_is_a_setting_the_drafter_keeps():
    found = read(golden("release_check"))
    read_block = next(b for b in found.plan.blocks if b.type == "CUSTOM.wabRead")
    [repository] = [s for s in found.plan.settings if s.kind == "repository"]
    assert read_block.parameters["place"] == f"<<{repository.id}>>"
    assert (repository.value, repository.mark) == ("langchain-ai/langgraph", "filled")


def test_a_workflow_made_in_n8n_reads_back_with_every_key_kept_out():
    found = read(made_in_n8n())
    text = found.plan.model_dump_json()
    for secret in (TOKEN, PASSWORD, API_KEY):
        assert secret not in text
    assert set(found.kept) == {
        KeptPlace("Read releases", "headerParameters.parameters[0].value"),
        KeptPlace("Read the tracker", "url"),
        KeptPlace("Read the tracker", "options.password"),
        KeptPlace("Read the tracker", "jsonHeaders"),
        KeptPlace("Read the tracker", "body"),
    }
    blocks = {b.name: b.parameters for b in found.plan.blocks}
    headers = blocks["Read releases"]["headerParameters"]["parameters"]
    assert headers == [
        {"name": "Authorization", "value": KEPT},
        {"name": "Accept", "value": "application/json"},
    ]
    assert blocks["Read releases"]["url"].startswith("https://api.github.com/")
    [channel] = [s for s in found.plan.settings if s.kind == "channel"]
    assert (channel.value, channel.mark) == ("#support", "filled")


def test_a_password_with_no_key_s_shape_is_kept_out_by_its_name():
    plan = release_check()
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "password": PASSWORD}})
        if b.name == "Read new releases"
        else b
        for b in plan.blocks
    ]
    out = keys_kept_out(plan.model_copy(update={"blocks": blocks}))
    assert PASSWORD not in out.plan.model_dump_json()
    assert out.kept == (KeptPlace("Read new releases", "password"),)


def test_a_setting_that_fills_a_key_s_place_keeps_its_value_out():
    plan = release_check()
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "apiKey": "<<repository>>"}})
        if b.name == "Read new releases"
        else b
        for b in plan.blocks
    ]
    out = keys_kept_out(plan.model_copy(update={"blocks": blocks}))
    settings = {s.id: s.value for s in out.plan.settings}
    assert settings["repository"] == KEPT
    assert settings["jira_project"] == "MOCK"
    assert out.kept == (KeptPlace(None, "settings.repository"),)


def with_parameters(**parameters: Any) -> WorkflowPlan:
    """The release check with these parameters on Read new releases."""
    plan = release_check()
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, **parameters}})
        if b.name == "Read new releases"
        else b
        for b in plan.blocks
    ]
    return plan.model_copy(update={"blocks": blocks})


def settings_of(plan: WorkflowPlan) -> dict[str, str | None]:
    return {s.id: s.value for s in plan.settings}


@pytest.mark.parametrize(
    "parameters",
    [
        {"url": "https://tracker.example.net/api?api_key=<<repository>>&page=1"},
        {"extra": "Bearer <<repository>>"},
        {"extra": "sent as token=<<repository>> each time"},
        {"extra": "X-Api-Key: <<repository>>"},
        {"jsonHeaders": '{"X-Api-Key": "<<repository>>"}'},
        {"jsonHeaders": '={{ {"x-api-key": "<<repository>>"} }}'},
        {"login": "https://bot:<<repository>>@tracker.example.net/"},
    ],
    ids=[
        "in an address's query",
        "after Bearer",
        "as name=value",
        "as name: value",
        "under a key's name in JSON",
        "in JSON inside an expression",
        "as an address's password",
    ],
)
def test_a_setting_whose_placeholder_stands_where_a_key_goes_keeps_its_value_out(
    parameters: dict[str, Any],
):
    out = keys_kept_out(with_parameters(**parameters))
    assert settings_of(out.plan)["repository"] == KEPT
    assert settings_of(out.plan)["jira_project"] == "MOCK"
    assert "langchain-ai/langgraph" not in out.plan.model_dump_json()


def test_a_setting_that_fills_a_parameter_named_as_a_key_keeps_its_value_out():
    plan = release_check()
    settings = [
        s.model_copy(
            update={"fills": [*s.fills, s.fills[0].model_copy(update={"parameter": "x.token"})]}
        )
        if s.id == "repository"
        else s
        for s in plan.settings
    ]
    out = keys_kept_out(plan.model_copy(update={"settings": settings}))
    assert settings_of(out.plan)["repository"] == KEPT


@pytest.mark.parametrize(
    ("parameters", "path"),
    [
        ({"auth": {"apiKey": {"value": PASSWORD}}}, "auth.apiKey.value"),
        ({"apiKey": [PASSWORD, API_KEY]}, "apiKey[0]"),
        ({"jsonHeaders": '={{ {"Authorization": "' + PASSWORD + '"} }}'}, "jsonHeaders"),
        ({"jsonHeaders": '={"x-session-id": "' + PASSWORD + '"}'}, "jsonHeaders"),
        ({"notes": f"login with password: {PASSWORD}"}, "notes"),
        ({"notes": f"secret={PASSWORD}"}, "notes"),
        ({"jsCode": "return $input.all();"}, "jsCode"),
        ({"pythonCode": "return _input.all()"}, "pythonCode"),
        ({"functionCode": "return items;"}, "functionCode"),
        ({"body": "Any words at all"}, "body"),
        ({"jsonBody": '{"a": 1}'}, "jsonBody"),
    ],
    ids=[
        "under a parent named as a key",
        "in a list under a key's name",
        "in JSON inside an expression",
        "in JSON after the expression mark",
        "as name: value",
        "as name=value",
        "JavaScript code",
        "Python code",
        "Function code",
        "a free-text body",
        "a JSON body",
    ],
)
def test_keys_are_kept_out_wherever_they_hide_and_code_and_bodies_always(
    parameters: dict[str, Any], path: str
):
    out = keys_kept_out(with_parameters(**parameters))
    assert KeptPlace("Read new releases", path) in out.kept
    for secret in (PASSWORD, API_KEY, "return"):
        assert secret not in out.plan.model_dump_json()


def test_a_drafted_plan_with_no_key_is_sent_as_it_is():
    plan = release_check()
    assert keys_kept_out(plan).plan == plan
    assert keys_kept_out(plan).kept == ()


def test_a_drafted_workflow_as_it_was_laid_out_reads_back_too():
    document = deepcopy(laid(release_check()))
    found = read(document)
    names = {b.name for b in found.plan.blocks}
    assert {"Every Monday", "Read new releases", "Propose a ticket", "Ask for a yes"} <= names
    assert {s.kind for s in found.plan.settings} >= {"run_time", "repository", "jira_project"}


def test_what_a_plan_can_t_hold_comes_back_as_words():
    document = made_in_n8n()
    document["nodes"][1]["onError"] = "continueRegularOutput"
    found = read_back_any(document, FACTS, ZONE)
    assert isinstance(found, NotReadBack)
    assert "“Read releases” has onError set in n8n" in found.words


def test_two_blocks_with_one_name_are_never_read_as_one():
    document = made_in_n8n()
    document["nodes"][2]["name"] = "Read releases"
    found = read_back_any(document, FACTS, ZONE)
    assert found == NotReadBack("Two blocks in n8n are named “Read releases”, so nothing was read.")


def test_a_block_named_with_a_key_is_never_read():
    document = made_in_n8n()
    document["nodes"][3]["name"] = f"Tell {TOKEN}"
    document["connections"] = link("Every Monday", "Read releases", "Read the tracker")
    found = read_back_any(document, FACTS, ZONE)
    assert isinstance(found, NotReadBack) and TOKEN not in found.words


def test_the_stand_in_and_the_names_are_the_runtime_s_own():
    shapes = json.loads((FIXTURES / "agent" / "key-shapes.json").read_text())
    assert shapes["kept"] == KEPT
    assert tuple(shapes["secret_name_ends"]) == SECRET_NAME_ENDS


def test_the_plan_read_back_is_one_the_runtime_takes():
    found = read(made_in_n8n())
    assert WorkflowPlan.model_validate_json(found.plan.model_dump_json()) == found.plan
