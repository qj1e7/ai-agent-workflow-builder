from harness import Api, Json, approval_requested, assert_gapless, bob_decides, tickets_for

LANGGRAPH_TITLE = "Upgrade LangGraph from 1.2.14 to 1.2.16"


def row(watchlist: Json, name: str) -> Json:
    return next(r for r in watchlist["software"] if r["name"] == name)


def watchlist_of(api: Api, user: str) -> Json:
    watchlist = api.watchlist(user)
    assert watchlist is not None, "the watchlist exists once software was added"
    return watchlist


def test_one_check_raises_one_ticket_per_software_behind_and_done_moves_our_version(
    api: Api,
) -> None:
    api.clear_watchlist("alice")

    first = api.add_software("alice", "LangGraph", "langchain-ai/langgraph", "1.2.14").json()
    assert first["ticket_project"] == "MOCK"
    api.add_software("alice", "Redis", "redis/redis", "8.2.1")
    added = api.add_software("alice", "Ghost", "nobody/ghost", "1.0.0").json()
    use_case_id = added["use_case_id"]
    assert use_case_id == first["use_case_id"]
    assert [r["status"] for r in added["software"]] == ["not_checked"] * 3
    assert all(r["our_version_source"]["kind"] == "given" for r in added["software"])
    assert row(added, "Redis")["our_version"] == "8.2.1"

    duplicate = api.add_software(
        "alice", "LangGraph again", "LangChain-AI/LangGraph", None, expect=(409,)
    )
    assert "already watched" in duplicate.json()["detail"]
    api.add_software("bob", "Nope", "nobody/nope", None, expect=(403,))
    api.add_software("alice", "Bad version", "nobody/bad", "v1", expect=(422,))

    run_id, started = api.start_run("alice", use_case_id)
    assert started.status_code == 201
    events = api.stream_until("alice", run_id, {"approval_requested"})
    assert_gapless(events, run_id)
    approval_id = approval_requested(events)["approval_id"]

    bob_view = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert [a["fields"]["title"] for a in bob_view["actions"]] == [LANGGRAPH_TITLE], (
        "exactly one ticket, for the one software that is behind"
    )
    message = api.poll(
        "the Teams stub message for this check",
        lambda: next(
            (
                m
                for m in api.get("alice", "/api/v1/teams-stub/messages")["messages"]
                if m["run_id"] == run_id
            ),
            None,
        ),
    )
    assert LANGGRAPH_TITLE in message["text"]

    waiting = watchlist_of(api, "bob")
    langgraph = row(waiting, "LangGraph")
    assert (langgraph["status"], langgraph["approval_id"]) == ("awaiting_approval", approval_id)
    assert (langgraph["newest_version"], langgraph["our_version"]) == ("1.2.16", "1.2.14")
    redis = row(waiting, "Redis")
    assert (redis["status"], redis["newest_version"]) == ("up_to_date", "8.2.1")
    assert redis["checked_at"] is not None
    ghost = row(waiting, "Ghost")
    assert ghost["status"] == "cant_check"
    assert "404" in ghost["problem"]
    assert ghost["newest_version"] is None
    assert [r["name"] for r in waiting["software"]][:2] == ["Ghost", "LangGraph"], (
        "rows that need a person come first"
    )
    assert waiting["last_check"]["run_id"] == run_id

    bob_decides(api, approval_id, "approve", bob_view["digest"])
    final = api.wait_for_state("alice", run_id, {"succeeded"})
    assert final["outcome"] == "written"
    [ticket] = tickets_for(api, run_id)
    assert (ticket["title"], ticket["status"], ticket["done_at"]) == (
        LANGGRAPH_TITLE,
        "To Do",
        None,
    )
    key = ticket["key"]
    assert final["written"][0]["external_reference"] == key

    open_view = watchlist_of(api, "alice")
    langgraph = row(open_view, "LangGraph")
    assert (langgraph["status"], langgraph["open_ticket"]) == ("ticket_open", key)
    assert langgraph["our_version"] == "1.2.14"
    assert open_view["last_check"]["state"] == "succeeded"

    api.mark_done("bob", key, expect=(403,))
    done = api.mark_done("alice", key).json()
    assert done["status"] == "Done" and done["done_at"] is not None
    assert api.mark_done("alice", key).json() == done, "marking Done again changes nothing"
    api.mark_done("alice", "MOCK-404", expect=(404,))

    moved = watchlist_of(api, "alice")
    langgraph = row(moved, "LangGraph")
    assert (langgraph["our_version"], langgraph["status"]) == ("1.2.16", "up_to_date")
    assert langgraph["our_version_source"] == {
        "kind": "ticket_done",
        "at": done["done_at"],
        "ticket": key,
    }
    assert (langgraph["open_ticket"], langgraph["approval_id"]) == (None, None)

    left = api.remove_software("alice", ghost["id"]).json()
    assert [r["name"] for r in left["software"]] == ["LangGraph", "Redis"]
    api.remove_software("alice", ghost["id"], expect=(404,))
