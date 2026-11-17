"""n8n with every built-in block on the real n8n (ADR 0051, spike P9, build step 12). n8n loads
every built-in block but Execute Command and Local File Trigger, and refuses Function, which runs
code in n8n's own process. Code runs in n8n's external task runner, in JavaScript and in Python:
the n8n image has no Python, so a Python block that runs at all ran there. A block n8n loads that
the class file turns off, published by a member, is graded Needs a fix by the platform, so its run
stops at the first block and writes nothing."""

import json
from typing import Any, cast

from harness import N8N_OWNER, Api, Json
from test_n8n_engine import set_up, ticket_count
from test_n8n_versions import held_by, staff_member, swept

LOADED = (
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.code",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.readWriteFile",
    "n8n-nodes-base.merge",
    "CUSTOM.wabAskForYes",
)
NEVER = ("n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger")

JAVASCRIPT = "return [{ json: { ran: 'javascript', sum: 2 + 3, process: typeof process } }];"
PYTHON = "return [{'json': {'ran': 'python', 'sum': 2 + 3}}]"


def by_hand(name: str, *blocks: Json) -> Json:
    """A workflow that runs its blocks one after another from a Manual Trigger."""
    nodes: list[Json] = [
        {
            "id": "all-blocks-by-hand",
            "name": "Run by hand",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 0],
            "parameters": {},
        },
        *blocks,
    ]
    names = [n["name"] for n in nodes]
    connections = {
        before: {"main": [[{"node": after, "type": "main", "index": 0}]]}
        for before, after in zip(names, names[1:], strict=False)
    }
    return {"name": name, "nodes": nodes, "connections": connections, "settings": {}}


def code(name: str, language: str, source: str, x: int) -> Json:
    field = "jsCode" if language == "javaScript" else "pythonCode"
    return {
        "id": f"all-blocks-{language}",
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [x, 0],
        "parameters": {"language": language, "mode": "runOnceForAllItems", field: source},
    }


def unflatted(text: str) -> Any:
    """n8n's /rest gives an execution's data in `flatted`'s form: a list whose first item is the
    value, where every string inside an object or a list is the index of the item it stands for."""
    table = cast(list[Any], json.loads(text))

    def revive(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: revive(table[int(v)]) if isinstance(v, str) else revive(v)
                for key, v in cast(dict[str, Any], value).items()
            }
        if isinstance(value, list):
            return [
                revive(table[int(v)]) if isinstance(v, str) else revive(v)
                for v in cast(list[Any], value)
            ]
        return value

    return revive(table[0])


def first_item(execution: Json, node: str) -> Json:
    data = unflatted(execution["data"])
    [run] = data["resultData"]["runData"][node]
    return run["data"]["main"][0][0]["json"]


def test_n8n_loads_every_built_in_block_but_two_and_refuses_the_deprecated_ones(
    api: Api, mock_model: None
):
    served = N8N_OWNER.send("GET", "/types/nodes.json")
    loaded = {t["name"] for t in served.raise_for_status().json()}
    assert set(LOADED) <= loaded, "n8n loads every built-in block, with no allow list"
    assert not set(NEVER) & loaded, "Execute Command and Local File Trigger never load"

    old = by_hand(
        "e2e all blocks: Function",
        {
            "id": "all-blocks-function",
            "name": "Old code",
            "type": "n8n-nodes-base.function",
            "typeVersion": 1,
            "position": [220, 0],
            "parameters": {"functionCode": "return items;"},
        },
    )
    refused = N8N_OWNER.send("POST", "/rest/workflows", old)
    assert refused.status_code == 400, refused.text
    assert "deprecated" in refused.text, "Function would run code in n8n's own process"


def test_code_runs_in_the_external_task_runner_in_javascript_and_python(api: Api, mock_model: None):
    workflow = by_hand(
        "e2e all blocks: Code in the task runner",
        code("JavaScript", "javaScript", JAVASCRIPT, 220),
        code("Python", "pythonNative", PYTHON, 440),
    )
    saved = N8N_OWNER.call("POST", "/workflows", workflow)
    try:
        started = N8N_OWNER.call(
            "POST",
            f"/workflows/{saved['id']}/run",
            {"destinationNode": {"nodeName": "Python", "mode": "inclusive"}},
        )
        execution_id = str(started["executionId"])

        def ended() -> Json | None:
            found = cast(Json, N8N_OWNER.call("GET", f"/executions/{execution_id}"))
            return found if found.get("status") not in ("new", "running", "waiting") else None

        execution = cast(Json, api.poll("the Code blocks' run", ended))
        assert execution["status"] == "success", execution["status"]
        assert first_item(execution, "JavaScript") == {
            "ran": "javascript",
            "sum": 5,
            "process": "undefined",
        }, "the runner's sandbox has no process of n8n's"
        assert first_item(execution, "Python") == {"ran": "python", "sum": 5}, (
            "n8n's own image has no Python, so only the external runner could run it"
        )
    finally:
        N8N_OWNER.send("DELETE", f"/rest/workflows/{saved['id']}")


def by_sql(nodes: list[Json], connections: Json) -> None:
    """A Merge block, which n8n loads, set to its SQL mode, which the class file turns off."""
    nodes.append(
        {
            "id": "all-blocks-merge",
            "name": "Join by SQL",
            "type": "n8n-nodes-base.merge",
            "typeVersion": 3.2,
            "position": [440, 600],
            "parameters": {"mode": "combineBySql"},
        }
    )


def test_a_block_the_class_file_turns_off_stops_the_run_in_the_platform_s_project(
    api: Api, mock_model: None
):
    created = set_up(api, "e2e all blocks", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    erin = staff_member(api, "Erin")
    held_by(api, erin, use_case_id, workflow_id)
    erin.member.publish(workflow_id, by_sql)
    view = swept(api, use_case_id, 2)
    assert view["grade"] == "needs_a_fix"
    assert view["findings"] == ['"Join by SQL" does something that is off: combineBySql.']

    tickets = ticket_count(api)
    run_id, started = api.start_run("carol", use_case_id)
    assert started.status_code == 201, started.text
    stopped = api.wait_for_state("carol", run_id, {"failed", "awaiting_approval", "succeeded"})
    assert stopped["state"] == "failed", stopped
    assert ticket_count(api) == tickets, "a version that fails the check writes nothing"
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
