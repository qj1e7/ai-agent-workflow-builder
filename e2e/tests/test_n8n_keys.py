"""n8n's own read and notice blocks with the platform's keys, on the real n8n (ENGINE-PLAN E16,
E17, ADR 0045 as amended): the platform makes its Jira, GitHub and Slack keys in its own project;
a member sees none of them; a workflow of Read release, n8n's Jira search and n8n's Slack post,
made in n8n and set up, posts nothing in its test run and once in a real run; a key a member adds
is gone within a minute, a hand run with it included; and each answer spike P8 needs is printed
as it is observed."""

import copy
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from harness import N8N_OWNER, Api, Json, SeededTicket, fail, seed_tickets
from test_n8n_engine import set_up
from test_n8n_versions import Member, staff_member

MOCK_SLACK = os.environ.get("MOCK_SLACK_URL", "http://mock-slack:8500")
PLATFORM_KEYS = {"wab-jira-read", "wab-github-read", "wab-slack-send"}
CHANNEL = "C0E2E16"


def observed(question: str, answer: object) -> None:
    """One line of spike P8's evidence, as the e2e log shows it."""
    print(f"P8 OBSERVED {question}: {json.dumps(answer, default=str)}")


def keys_in_n8n() -> dict[str, Json]:
    """Every key n8n holds, as its owner lists them, by id."""
    listed: list[Json] = N8N_OWNER.call("GET", "/credentials")
    return {str(key["id"]): key for key in listed}


def platform_keys(api: Api) -> dict[str, Json]:
    def made() -> dict[str, Json] | None:
        held = keys_in_n8n()
        return held if set(held) >= PLATFORM_KEYS else None

    return api.poll("the platform to make its Jira, GitHub and Slack keys in n8n", made)


def sent_to_slack() -> list[Json]:
    answer = httpx.get(f"{MOCK_SLACK}/_sent", timeout=10)
    answer.raise_for_status()
    return list(answer.json()["sent"])


def posts_to(channel: str) -> list[Json]:
    return [
        m for m in sent_to_slack() if m["method"] == "chat.postMessage" and m["channel"] == channel
    ]


def to(target: str) -> Json:
    return {"main": [[{"node": target, "type": "main", "index": 0}]]}


def reads_then_tells(source_id: str, name: str) -> Json:
    """The release check's triggers and Read release, as the Planner laid them out, then n8n's own
    Jira search and n8n's own Slack post, naming the platform's keys by id, with the Slack post's
    output pinned so a test run posts nothing. The search runs once, not once for each release
    Read release finds, so a real run posts once."""
    laid = N8N_OWNER.call("GET", f"/workflows/{source_id}")
    kept = {"Start from the Portal", "Read release"}
    nodes: list[Json] = []
    for node in copy.deepcopy(laid["nodes"]):
        if node["type"] == "n8n-nodes-base.scheduleTrigger" or node["name"] in kept:
            node["id"] = str(uuid.uuid4())
            if "webhookId" in node:
                node["webhookId"] = str(uuid.uuid4())
            nodes.append(node)
    schedule = next(n["name"] for n in nodes if n["type"] == "n8n-nodes-base.scheduleTrigger")
    nodes.append(
        {
            "id": str(uuid.uuid4()),
            "name": "Read tickets",
            "type": "n8n-nodes-base.jira",
            "typeVersion": 1,
            "position": [440, 0],
            "executeOnce": True,
            "parameters": {
                "jiraVersion": "serverPat",
                "operation": "getAll",
                "limit": 1,
                "options": {"jql": "project = MOCK"},
            },
            "credentials": {"jiraSoftwareServerPatApi": {"id": "wab-jira-read", "name": "Jira"}},
        }
    )
    nodes.append(
        {
            "id": str(uuid.uuid4()),
            "name": "Tell Slack",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2.7,
            "position": [660, 0],
            "parameters": {
                "select": "channel",
                "channelId": {"__rl": True, "value": CHANNEL, "mode": "id"},
                "text": "A ticket was read",
                "otherOptions": {"includeLinkToWorkflow": False},
            },
            "credentials": {"slackApi": {"id": "wab-slack-send", "name": "Slack"}},
        }
    )
    return {
        "name": name,
        "nodes": nodes,
        "connections": {
            schedule: to("Read release"),
            "Start from the Portal": to("Read release"),
            "Read release": to("Read tickets"),
            "Read tickets": to("Tell Slack"),
        },
        "settings": laid["settings"],
        "pinData": {"Tell Slack": [{"json": {"skipped": "Slack notice skipped in the test run."}}]},
    }


def test_builtin_read_and_notice(api: Api, mock_model: None):
    held = platform_keys(api)
    home = str(N8N_OWNER.call("GET", "/projects/personal")["id"])
    observed("the platform's keys, as its owner lists them", {k: held[k] for k in PLATFORM_KEYS})
    source = set_up(api, "e2e n8n blocks, the blocks it copies", on=False)
    frank = staff_member(api, "Frank")
    document = reads_then_tells(
        source["n8n_workflow_id"], f"e2e read and notice {uuid.uuid4().hex[:6]}"
    )
    saved = frank.member.call("POST", "/workflows", document)
    workflow_id = str(saved["id"])
    kept = frank.member.call("GET", f"/workflows/{workflow_id}")
    named = {n["name"]: n.get("credentials") for n in kept["nodes"] if n.get("credentials")}
    observed("a member's save keeps the platform's key it cannot use", named)
    if named.get("Tell Slack", {}).get("slackApi", {}).get("id") != "wab-slack-send":
        fail(f"n8n did not keep the platform's key on the member's workflow: {named}")
    waiting = {
        w["workflow_id"]: w for w in api.get(frank.person, "/api/v1/n8n/workflows")["workflows"]
    }
    found = waiting[workflow_id]
    assert (found["grade"], found["can_set_up"]) == ("safe", True), found["findings"]

    created = api.post(
        frank.person, "/api/v1/use-cases/from-n8n", {"workflow_id": workflow_id}, expect=(201,)
    ).json()
    use_case_id = created["use_case_id"]
    blocks = {b["name"]: b for b in created["blocks"]}
    assert (blocks["Tell Slack"]["badge"], blocks["Tell Slack"]["tag"]) == ("n8n", "Posts in Slack")
    assert (blocks["Read tickets"]["badge"], blocks["Read tickets"]["tag"]) == ("n8n", "Reads Jira")
    view = api.get(frank.person, f"/api/v1/use-cases/{use_case_id}/n8n")
    tags = {n["name"]: (n["badge"], n["tag"]) for n in view["nodes"]}
    assert tags["Tell Slack"] == ("n8n", "Posts in Slack")
    assert tags["Read release"][0] == "ours"

    seed_tickets("MOCK", [SeededTicket("e2e ticket n8n's Jira block reads", "Task", 1)])
    before = len(posts_to(CHANNEL))
    runs = f"/api/v1/use-cases/{use_case_id}/runs"
    test_run = api.post(
        "carol",
        runs,
        {"test": True},
        expect=(201,),
        headers={"Idempotency-Key": f"t-{use_case_id}"},
    ).json()
    finished = api.wait_for_state("carol", test_run["run_id"], {"succeeded"})
    assert (finished["outcome"], finished["written"]) == ("nothing_to_write", [])
    observed("posts to Slack after a test run", len(posts_to(CHANNEL)) - before)
    assert len(posts_to(CHANNEL)) == before, "a test run posts nothing"

    api.post("alice", f"/api/v1/use-cases/{use_case_id}/turn-on", expect=(200,))
    run_id, _ = api.start_run("carol", use_case_id)
    api.wait_for_state("carol", run_id, {"succeeded"})
    posted = api.poll("n8n's Slack block to post once", lambda: posts_to(CHANNEL)[before:] or None)
    observed("posts to Slack after a real run", posted)
    assert len(posted) == 1 and posted[0]["token"] == "mock-slack-token"
    assert posted[0]["text"] == "A ticket was read"
    assert home, "the platform's own project"
    for made in (use_case_id, source["use_case_id"]):
        api.delete("alice", f"/api/v1/use-cases/{made}", expect=(200,))


def test_member_cannot_select_platform_credential(api: Api):
    platform_keys(api)
    gina = staff_member(api, "Gina")
    listed: list[Json] = gina.member.call("GET", "/credentials")
    offered = {str(key["id"]) for key in listed}
    observed("what a member's editor lists", sorted(offered))
    assert not offered & PLATFORM_KEYS, "none of the platform's keys is offered in a member's space"
    for key in PLATFORM_KEYS:
        status = gina.member.client.get(f"/rest/credentials/{key}").status_code
        observed(f"a member reads the platform's key {key}", status)
        assert status in (403, 404)


def test_type_availability_policies_are_licensed_only(api: Api):
    """Spike P8: n8n's credential and node type policies would replace the sweep, if the free
    edition had them."""
    for path in ("/credential-type-policies/instance", "/node-type-policies/instance"):
        answer = N8N_OWNER.send("GET", f"/rest{path}")
        observed(f"GET /rest{path} on the free edition", (answer.status_code, answer.text[:200]))
        assert answer.status_code in (403, 404), "a licensed feature, off on the free edition"


def test_foreign_credential_is_removed(api: Api):
    platform_keys(api)
    hana = staff_member(api, "Hana")
    hers = hana.member.call(
        "POST", "/credentials", {"name": "Mine", "type": "slackApi", "data": {"accessToken": "x"}}
    )
    hers_id = str(hers["id"])
    assert hers_id in keys_in_n8n()
    api.poll(
        "the credential sweep to remove a key a member added", lambda: hers_id not in keys_in_n8n()
    )
    observed("a member's key is removed", True)
    still = keys_in_n8n()
    assert set(still) >= PLATFORM_KEYS, "the platform's own keys stay"


def test_member_hand_run_with_own_key_is_swept(api: Api, mock_model: None):
    """n8n loads every built-in block, so a holder can set n8n's Slack block to delete and run it by
    hand with a key of their own. The sweep removes that key within a minute, and the platform's
    keys never come to the holder's space."""
    platform_keys(api)
    created = set_up(api, "e2e hand run with a member's own key", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    ivan = staff_member(api, "Ivan")
    api.post(ivan.person, f"/api/v1/use-cases/{use_case_id}/open-in-n8n", expect=(200,))
    home = str(N8N_OWNER.call("GET", "/projects/personal")["id"])
    homes = {
        k: (v["homeProject"]["id"] == home, v["sharedWithProjects"])
        for k, v in keys_in_n8n().items()
        if k in PLATFORM_KEYS
    }
    observed("each platform key in the platform's project, and who it is shared with", homes)
    assert homes == {k: (True, []) for k in PLATFORM_KEYS}, "no key comes to the holder"
    hers = ivan.member.call(
        "POST",
        "/credentials",
        {"name": "Mine", "type": "slackApi", "data": {"accessToken": "hers"}},
    )
    hers_id = str(hers["id"])

    def with_a_delete(nodes: list[Json], connections: Json) -> None:
        nodes.append(
            {
                "id": str(uuid.uuid4()),
                "name": "Delete in Slack",
                "type": "n8n-nodes-base.slack",
                "typeVersion": 2.7,
                "position": [900, 300],
                "parameters": {
                    "operation": "delete",
                    "channelId": {"__rl": True, "value": CHANNEL, "mode": "id"},
                    "timestamp": "1",
                },
                "credentials": {"slackApi": {"id": hers_id, "name": "Mine"}},
            }
        )

    held = ivan.member.call("GET", f"/workflows/{workflow_id}")
    with_a_delete(held["nodes"], held["connections"])
    body = {k: held[k] for k in ("nodes", "connections", "settings", "versionId")}
    ivan.member.call("PATCH", f"/workflows/{workflow_id}", body)
    api.poll(
        "the credential sweep to remove the member's key", lambda: hers_id not in keys_in_n8n()
    )
    view = api.poll(
        "the workflow to say a key was added in n8n",
        lambda: (
            (v := api.get("alice", f"/api/v1/use-cases/{use_case_id}"))["grade"] == "needs_a_fix"
            and v
        ),
    )
    assert any("key was added in n8n" in finding for finding in view["findings"])
    deletes = [m for m in sent_to_slack() if m["method"] == "chat.delete" and m["token"] == "hers"]
    observed("deletes Slack saw with the member's key", len(deletes))
    api.post(ivan.person, f"/api/v1/use-cases/{use_case_id}/take-back", expect=(200,))
    back = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")
    named: dict[str, Any] = {n["name"]: n.get("credentials") for n in back["nodes"]}
    observed("the keys the draft names once taken back", named)
    assert named["Delete in Slack"] is None, "a Slack delete gets no key, not the platform's"
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


def deletes_in_slack(after: str, key: str = "wab-slack-send") -> Callable[[list[Json], Json], None]:
    """n8n's Slack block set to delete, naming a key, right after a trigger, so it would run
    before any of our blocks."""

    def change(nodes: list[Json], connections: Json) -> None:
        nodes.append(
            {
                "id": str(uuid.uuid4()),
                "name": "Delete in Slack",
                "type": "n8n-nodes-base.slack",
                "typeVersion": 2.7,
                "position": [900, 400],
                "parameters": {
                    "operation": "delete",
                    "select": "channel",
                    "channelId": {"__rl": True, "value": CHANNEL, "mode": "id"},
                    "timestamp": 1,
                },
                "credentials": {"slackApi": {"id": key, "name": "Slack"}},
            }
        )
        trigger = next(n["name"] for n in nodes if n["type"].endswith(after))
        exits = connections.setdefault(trigger, {"main": [[]]})["main"][0]
        exits.append({"node": "Delete in Slack", "type": "main", "index": 0})

    return change


def published_with_her_own_key(member: Member, workflow_id: str) -> str:
    """The sweep removes a member's key within a minute, so one it took before the publish is
    made again."""
    for _ in range(3):
        mine = member.call(
            "POST",
            "/credentials",
            {"name": "Mine", "type": "slackApi", "data": {"accessToken": "mine"}},
        )

        def uses_mine(nodes: list[Json], _: Json, key: str = str(mine["id"])) -> None:
            [block] = [n for n in nodes if n["name"] == "Delete in Slack"]
            block["credentials"] = {"slackApi": {"id": key, "name": "Mine"}}

        try:
            return member.publish(workflow_id, uses_mine)
        except httpx.HTTPStatusError as refused:
            observed("n8n refused a publish with the member's key", refused.response.text[:200])
    fail("n8n did not publish the member's own key three times running")


def chat_deletes() -> int:
    return len([m for m in sent_to_slack() if m["method"] == "chat.delete"])


def test_a_version_published_in_n8n_that_runs_a_block_unchecked_comes_back_off(
    api: Api, mock_model: None
):
    """The E16 safety review's first must-fix. The free edition lets the holder publish a block
    naming the platform's key (spike P8, Q12). n8n won't run it in their space, but back in the
    platform's project it would, on every tick of its schedule. So the take-back takes it off
    before it moves, and it stays off, marked Needs a fix."""
    platform_keys(api)
    created = set_up(api, "e2e a published delete comes back off", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    jo = staff_member(api, "Jo")
    api.post(jo.person, f"/api/v1/use-cases/{use_case_id}/open-in-n8n", expect=(200,))
    deletes = chat_deletes()
    draft = jo.member.call("GET", f"/workflows/{workflow_id}")
    deletes_in_slack("scheduleTrigger")(draft["nodes"], draft["connections"])
    body = {key: draft[key] for key in ("nodes", "connections", "settings", "versionId")}
    jo.member.call("PATCH", f"/workflows/{workflow_id}", body)
    saved = jo.member.call("GET", f"/workflows/{workflow_id}")
    publish = {"versionId": saved["versionId"], "expectedChecksum": saved["checksum"]}
    answer = jo.member.client.post(f"/rest/workflows/{workflow_id}/activate", json=publish)
    live = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")["activeVersionId"]
    observed("a member publishes a block naming the platform's key", (answer.status_code, live))
    if live != saved["versionId"]:
        published = published_with_her_own_key(jo.member, workflow_id)
        observed("a member publishes the same block with a key of their own", published)
    api.post(jo.person, f"/api/v1/use-cases/{use_case_id}/take-back", expect=(200,))
    back = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")
    observed("the version n8n runs once it is back", back["activeVersionId"])
    assert back["activeVersionId"] is None, "taken off before it came back"
    view = api.get("alice", f"/api/v1/use-cases/{use_case_id}")
    assert view["grade"] == "needs_a_fix", view
    assert any("took it off in n8n" in finding for finding in view["findings"]), view
    assert chat_deletes() == deletes, "nothing was deleted in Slack"
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


def test_no_test_run_starts_while_held_or_on_a_draft_n8n_would_run_unchecked(
    api: Api, mock_model: None
):
    """The E16 safety review's second must-fix: a test run runs the draft by hand in the
    platform's project, where n8n lets it use every key there is."""
    platform_keys(api)
    created = set_up(api, "e2e an unsafe draft is never test run", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    runs = f"/api/v1/use-cases/{use_case_id}/runs"
    kim = staff_member(api, "Kim")
    api.post(kim.person, f"/api/v1/use-cases/{use_case_id}/open-in-n8n", expect=(200,))
    held = api.post(
        "carol",
        runs,
        {"test": True},
        expect=(409,),
        headers={"Idempotency-Key": f"h-{use_case_id}"},
    ).json()
    observed("a test run while a member holds it", held["detail"])
    draft = kim.member.call("GET", f"/workflows/{workflow_id}")
    deletes_in_slack("wabStartFromPortal")(draft["nodes"], draft["connections"])
    body = {key: draft[key] for key in ("nodes", "connections", "settings", "versionId")}
    kim.member.call("PATCH", f"/workflows/{workflow_id}", body)
    api.post(kim.person, f"/api/v1/use-cases/{use_case_id}/take-back", expect=(200,))
    deletes = chat_deletes()
    refused = api.post(
        "carol",
        runs,
        {"test": True},
        expect=(409,),
        headers={"Idempotency-Key": f"u-{use_case_id}"},
    ).json()
    observed("a test run of a draft n8n would run unchecked", refused["detail"])
    assert "can't check" in refused["detail"], refused
    assert chat_deletes() == deletes
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
