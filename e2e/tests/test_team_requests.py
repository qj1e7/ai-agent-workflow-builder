from uuid import uuid4

from harness import Api, Json

ASK: Json = {
    "kind": "ask_the_team",
    "about": {"capability": "email.send"},
    "note": "We would like the list by email.",
}


def replied_ids(api: Api, user: str) -> list[str]:
    return [item["request_id"] for item in api.get(user, "/api/v1/home")["replied"]]


def test_a_reply_waits_in_the_askers_needs_you_until_they_open_it(api: Api) -> None:
    made = api.post(
        "alice",
        "/api/v1/team-requests",
        ASK,
        expect=(201,),
        headers={"Idempotency-Key": str(uuid4())},
    )
    request_id = made.json()["request_id"]
    base = f"/api/v1/team-requests/{request_id}"
    assert request_id not in replied_ids(api, "alice")

    sent = api.post("bob", f"{base}/replies", {"text": "Not on the plan."}, expect=(201,)).json()

    assert request_id in replied_ids(api, "alice")
    assert request_id not in replied_ids(api, "bob")
    through = sent["replies"][-1]["replied_at"]
    api.post("bob", f"{base}/seen", {"through": through}, expect=(403,))
    api.post("carol", f"{base}/seen", {"through": through}, expect=(403,))
    assert request_id in replied_ids(api, "alice")
    api.post("alice", "/api/v1/team-requests/trq_nope/seen", {"through": through}, expect=(404,))

    api.post("alice", f"{base}/seen", {"through": through}, expect=(200,))

    assert request_id not in replied_ids(api, "alice")
    home = api.get("alice", "/api/v1/home")
    assert request_id in [item["request_id"] for item in home["following_up"]]
    assert api.get("carol", base)["replies"][0]["text"] == "Not on the plan."


def test_the_askers_own_note_keeps_the_status_and_only_others_answer(api: Api) -> None:
    made = api.post(
        "alice",
        "/api/v1/team-requests",
        ASK,
        expect=(201,),
        headers={"Idempotency-Key": str(uuid4())},
    )
    base = f"/api/v1/team-requests/{made.json()['request_id']}"

    noted = api.post("alice", f"{base}/replies", {"text": "For Friday."}, expect=(201,)).json()
    claimed = api.post(
        "alice", f"{base}/replies", {"text": "Still open.", "status": "answered"}, expect=(201,)
    ).json()
    answered = api.post("bob", f"{base}/replies", {"text": "On it."}, expect=(201,)).json()
    closed = api.post(
        "alice", f"{base}/replies", {"text": "Not needed.", "status": "done"}, expect=(201,)
    ).json()

    assert [r["status"] for r in (noted, claimed, answered, closed)] == [
        "open",
        "open",
        "answered",
        "done",
    ]
