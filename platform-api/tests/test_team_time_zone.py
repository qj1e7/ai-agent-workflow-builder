"""The TEAM_TIME_ZONE setting reaches every place a time zone is set: the Portal's times through
/api/v1/me, and the zone of a new schedule (issue #165)."""

from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.builder import Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.orchestration import ScheduleBook
from tests import test_builder_lifecycle
from tests.conftest import PostgresUrls, truncate_all
from tests.test_builder_http import NothingLearned
from tests.test_builder_lifecycle import LANGGRAPH, VALUES, Lab
from tests.test_ready import env_for

lab = test_builder_lifecycle.lab
ALICE = {"X-Dev-User": "alice"}
SCHEDULED: dict[str, Any] = {
    "name": "Watch LangGraph",
    "instruction": "Check LangGraph for new releases.",
    "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
    "schedule": {"day": "monday", "at": "09:00"},
}


@pytest.mark.parametrize(
    ("setting", "zone"), [(None, "Asia/Singapore"), ("Europe/London", "Europe/London")]
)
def test_the_portal_and_a_new_schedule_take_the_team_time_zone(
    postgres: PostgresUrls, setting: str | None, zone: str
):
    truncate_all(postgres.owner)
    env = env_for(postgres) | ({} if setting is None else {"TEAM_TIME_ZONE": setting})
    with TestClient(create_app(env)) as client:
        me = client.get("/api/v1/me", headers=ALICE)
        made = client.post("/api/v1/agent-use-cases", json=SCHEDULED, headers=ALICE)
        assert made.status_code == 201, made.text
        use_case_id = made.json()["use_case_id"]
        view = client.get(f"/api/v1/use-cases/{use_case_id}", headers=ALICE)

    assert (me.status_code, me.json()["time_zone"]) == (200, zone)
    schedule = view.json()["schedule"]
    assert (schedule["day"], schedule["at"], schedule["time_zone"]) == ("monday", "09:00", zone)


@pytest.mark.anyio
async def test_a_new_watchlist_is_checked_on_mondays_at_9_in_the_team_time_zone(lab: Lab):
    london = ZoneInfo("Europe/London")
    db = lab.h.db
    lab.app.state.watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db), time_zone=london)

    added = await lab.call("alice", "POST", "/api/v1/watchlist/software", LANGGRAPH)

    assert added.status_code == 201, added.text
    schedule = added.json()["schedule"]
    assert (schedule["day"], schedule["at"], schedule["time_zone"]) == (
        "monday",
        "09:00",
        "Europe/London",
    )
