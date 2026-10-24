from harness import STEP_KEY, Api, fail


def test_bootstrap_loaded_and_activated_the_schedule_workflow(api: Api) -> None:
    ready = api.get(None, "/healthz/ready")
    checks = {c["name"]: c for c in ready["checks"]}
    detail = checks["workflows"]["detail"]
    if "schedule_tick active" not in detail:
        fail(f"bootstrap did not report schedule_tick as loaded and active: {detail!r}")
    assert ready["ready"] is True


def test_a_tick_with_nothing_due_answers_200_and_starts_no_runs(api: Api) -> None:
    if not STEP_KEY:
        fail("STEP_KEY is not set for the e2e container")
    api.tick("wrong-key", expect=(401,))
    before = len(api.get("alice", "/api/v1/runs")["runs"])
    watchlist = api.watchlist("alice")
    if watchlist is not None and watchlist["schedule"] is not None:
        # A stack that kept state may hold a schedule that came due. Turn it off so the answer
        # does not depend on the clock. Slot timing is covered by the unit tests.
        previous = watchlist["schedule"]
        api.delete("alice", "/api/v1/watchlist/schedule", expect=(200,))
        try:
            ticked = api.tick(STEP_KEY).json()
        finally:
            api.request(
                "alice",
                "PUT",
                "/api/v1/watchlist/schedule",
                expect=(200,),
                json_body={"day": previous["day"], "at": previous["at"]},
            )
    else:
        ticked = api.tick(STEP_KEY).json()
    assert ticked == {"started": []}
    assert len(api.get("alice", "/api/v1/runs")["runs"]) == before
