"""A version edited and published in n8n's editor, by a member, on the real n8n (ENGINE-PLAN E6):
the sweep keeps it as a version published in n8n, graded, and the chat's Changed in n8n card says
so; nobody guesses who published it, so its runs stop; Undo puts the version before back, which
runs and writes after Bob's yes; and a request waiting when its workflow is deleted ends
cancelled, with nothing written and the workflow gone from n8n."""

import secrets
import urllib.parse
from typing import cast

import httpx
from harness import N8N_OWNER, N8N_URL, Api, Json, approval_requested, bob_decides, tickets_for
from test_n8n_engine import set_up, ticket_count


def owner_rows(method: str, path: str, body: object = None) -> list[Json]:
    """n8n's /rest answers these two calls with a list."""
    return cast(list[Json], N8N_OWNER.call(method, path, cast(Json | None, body)))


class Member:
    """A staff member's n8n account, as the platform will make one once E7 lands: invited by the
    owner and signed in to n8n's editor with their own session."""

    def __init__(self, name: str) -> None:
        email = f"{name}-{secrets.token_hex(4)}@example.com"
        [invited] = owner_rows("POST", "/invitations", [{"email": email, "role": "global:member"}])
        link = str(invited["user"]["inviteAcceptUrl"])
        token = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["token"][0]
        password = f"E6-{secrets.token_urlsafe(12)}a1A"
        self.client = httpx.Client(base_url=N8N_URL, timeout=30)
        accept = {"token": token, "firstName": name, "lastName": "Tester", "password": password}
        self.client.post("/rest/invitations/accept", json=accept).raise_for_status()
        login = {"emailOrLdapLoginId": email, "password": password}
        self.client.post("/rest/login", json=login).raise_for_status()
        projects = owner_rows("GET", "/projects")
        self.project = next(p["id"] for p in projects if email in p["name"])

    def call(self, method: str, path: str, body: Json | None = None) -> Json:
        answer = self.client.request(method, f"/rest{path}", json=body)
        answer.raise_for_status()
        data: Json = answer.json()["data"]
        return data

    def publish_without_the_yes(self, workflow_id: str) -> str:
        """Deletes Ask for a yes in the editor, saves and publishes, as P7 Q4's member did."""
        held = self.call("GET", f"/workflows/{workflow_id}")
        nodes = [node for node in held["nodes"] if node["name"] != "Ask for a yes"]
        connections = {k: v for k, v in held["connections"].items() if k != "Ask for a yes"}
        connections["Newer?"]["main"][0] = [{"node": "Create ticket", "type": "main", "index": 0}]
        body = {"nodes": nodes, "connections": connections, "versionId": held["versionId"]}
        draft = self.call("PATCH", f"/workflows/{workflow_id}", body)
        activate = {"versionId": draft["versionId"], "expectedChecksum": draft["checksum"]}
        self.call("POST", f"/workflows/{workflow_id}/activate", activate)
        published: str = draft["versionId"]
        return published


def held_by(member: Member, workflow_id: str) -> None:
    """Open in n8n, done by hand until E7: the workflow moves to the member's own project."""
    body = {"destinationProjectId": member.project}
    N8N_OWNER.call("PUT", f"/workflows/{workflow_id}/transfer", body)


def swept(api: Api, use_case_id: str, version: int) -> Json:
    def kept() -> Json | None:
        api.post("alice", f"/api/v1/n8n/sweep?use_case_id={use_case_id}", expect=(200,))
        view = api.get("alice", f"/api/v1/use-cases/{use_case_id}")
        return view if view["version"] == version else None

    found: Json = api.poll(f"the sweep to keep version {version}", kept)
    return found


def test_a_version_published_in_n8n_is_kept_graded_and_carded_and_undo_restores(
    api: Api, mock_model: None
):
    created = set_up(api, "e2e versions edited in n8n", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    first = api.get("alice", f"/api/v1/use-cases/{use_case_id}/versions")["versions"][0]
    assert (first["version"], first["grade"]) == (1, "safe")
    member = Member("dana")
    held_by(member, workflow_id)
    published = member.publish_without_the_yes(workflow_id)

    view = swept(api, use_case_id, 2)
    assert view["grade"] == "writes_refused"
    assert view["findings"] == ['"Create ticket" can run without a yes.']
    newest = api.get("alice", f"/api/v1/use-cases/{use_case_id}/versions")["versions"][0]
    assert (newest["made"], newest["by"], newest["publisher_unknown"]) == (
        "published_in_n8n",
        None,
        True,
    ), "nobody guesses who published it"
    assert "Deleted “Ask for a yes”." in newest["changes"]
    cards = [
        c
        for c in api.get("alice", "/api/v1/home")["changed_in_n8n"]
        if c["use_case_id"] == use_case_id
    ]
    assert [(c["version"], c["grade"], c["by"], c["in_use"]) for c in cards] == [
        (2, "writes_refused", None, 2)
    ]
    assert api.get("bob", "/api/v1/home")["changed_in_n8n"] == [], "the card is an Operator's"
    assert N8N_OWNER.call("GET", f"/workflows/{workflow_id}")["activeVersionId"] == published

    tickets = ticket_count(api)
    run_id, _ = api.start_run("carol", use_case_id)
    stopped = api.wait_for_state("carol", run_id, {"failed", "awaiting_approval", "succeeded"})
    assert (stopped["state"], stopped["reason"]) == ("failed", "SafetyDenied")
    assert ticket_count(api) == tickets, "a version without its yes writes nothing"

    undone = api.post(
        "alice",
        f"/api/v1/use-cases/{use_case_id}/versions/1/rollback",
        {"via": "chat", "in_use": 2},
        expect=(200,),
    ).json()
    assert (undone["version"], undone["grade"]) == (3, "safe")
    live = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")["activeVersionId"]
    assert live != published
    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", approval["digest"])
    api.wait_for_state("carol", run_id, {"succeeded"})
    assert len(tickets_for(api, run_id)) == 1, "Undo restored the yes, and one ticket follows it"
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


def test_an_open_request_survives_a_deleted_workflow_as_cancelled(api: Api, mock_model: None):
    created = set_up(api, "e2e versions deleted while waiting", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    tickets = ticket_count(api)
    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    digest = api.get("bob", f"/api/v1/approvals/{approval_id}")["digest"]

    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
    ended = api.wait_for_state("carol", run_id, {"expired"})
    assert ended["state"] == "expired"
    said = [e["summary"] for e in api.events_after("carol", run_id) if e["kind"] == "run_expired"]
    assert said == ["Deleted before an answer. Nothing was written."]
    request = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert "cancelled" in [step["status"] for step in request["steps"]]
    api.post(
        "bob",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": digest},
        expect=(403, 409, 410),
    )
    assert ticket_count(api) == tickets, "nothing was written"
    assert api.poll("n8n to archive and delete the workflow", lambda: _gone(workflow_id))


def _gone(workflow_id: str) -> bool:
    try:
        N8N_OWNER.call("GET", f"/workflows/{workflow_id}")
    except httpx.HTTPStatusError as error:
        return error.response.status_code in (403, 404)
    return False
