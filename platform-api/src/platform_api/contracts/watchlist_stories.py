"""Recorded answers of the watchlist routes: no watchlist yet, an emptied one, and one with a
row in every status, the schedule routes, a schedule held because its owner left, the schedule
tick, a scheduled run and the practice Jira ticket after Mark Done."""

from datetime import UTC, datetime, timedelta, timezone

from platform_api.builder.models import (
    AddSoftware,
    LastCheckView,
    ScheduleIn,
    ScheduleView,
    SourceView,
    VersionSourceView,
    WatchedSoftwareView,
    WatchlistOut,
    WatchlistView,
)
from platform_api.builder.watchlist import attention_first
from platform_api.contracts.stories import SUCCESS, TICKET_BODY, TICKET_TITLE
from platform_api.orchestration.http import MockJiraTicket, PendingView, TickOut
from platform_api.shared import ApprovalId, RunId, SoftwareId, UserId
from platform_api.wire import WireModel

ALICE = UserId("alice")
CAROL = UserId("carol")
USE_CASE_ID = "uc_01JBW"
ADDED_AT = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
FIRST_CHECK_AT = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
CHECKED_AT = datetime(2026, 11, 16, 1, 0, 12, tzinfo=UTC)
LAST_RUN = RunId("run_01JBB")
APPROVAL = ApprovalId("apr_01JBB")

ADD_SOFTWARE = AddSoftware(name="LangGraph", repo="langchain-ai/langgraph", our_version="1.2.14")


def github(ref: str) -> SourceView:
    return SourceView(kind="github", ref=ref, url=f"https://github.com/{ref}/releases")


def given(at: datetime = ADDED_AT) -> VersionSourceView:
    return VersionSourceView(kind="given", at=at, ticket=None)


def row(
    number: int,
    name: str,
    ref: str,
    our_version: str | None,
    our_version_source: VersionSourceView | None,
    newest_version: str | None,
    checked_at: datetime | None,
    status: str,
    problem: str | None = None,
    open_ticket: str | None = None,
    approval_id: ApprovalId | None = None,
    added_at: datetime = ADDED_AT,
    newest_read_at: datetime | None = None,
) -> WatchedSoftwareView:
    return WatchedSoftwareView.model_validate(
        {
            "id": SoftwareId(f"sw_01JBW{number:020d}"),
            "name": name,
            "source": github(ref),
            "our_version": our_version,
            "our_version_source": our_version_source,
            "newest_version": newest_version,
            "newest_read_at": newest_read_at or (checked_at if newest_version else None),
            "checked_at": checked_at,
            "status": status,
            "problem": problem,
            "open_ticket": open_ticket,
            "approval_id": approval_id,
            "added_by": ALICE,
            "added_at": added_at,
        }
    )


ROWS = [
    row(
        1,
        "n8n",
        "n8n-io/n8n",
        "2.42.6",
        VersionSourceView(kind="ticket_done", at=CHECKED_AT - timedelta(days=3), ticket="MOCK-140"),
        "2.42.6",
        CHECKED_AT,
        "up_to_date",
    ),
    row(
        2,
        "LangGraph",
        "langchain-ai/langgraph",
        "1.2.14",
        given(),
        "1.2.16",
        CHECKED_AT,
        "behind",
    ),
    row(
        3,
        "Redis",
        "redis/redis",
        "8.2.0",
        VersionSourceView(kind="first_check", at=FIRST_CHECK_AT, ticket=None),
        "8.2.1",
        CHECKED_AT,
        "awaiting_approval",
        approval_id=APPROVAL,
    ),
    row(
        4,
        "PostgreSQL",
        "postgres/postgres",
        "17.2.0",
        given(),
        "17.3.0",
        CHECKED_AT,
        "ticket_open",
        open_ticket="MOCK-143",
    ),
    row(
        5,
        "FastAPI",
        "fastapi/fastapi",
        "0.115.0",
        given(),
        "0.115.2",
        CHECKED_AT,
        "cant_check",
        problem="GitHub answered 404 Not Found.",
        newest_read_at=FIRST_CHECK_AT,
    ),
    row(
        6,
        "Terraform",
        "hashicorp/terraform",
        None,
        None,
        None,
        None,
        "not_checked",
        added_at=CHECKED_AT + timedelta(hours=8),
    ),
]

SINGAPORE = timezone(timedelta(hours=8))
SCHEDULE = ScheduleView(
    day="monday",
    at="09:00",
    time_zone="Asia/Singapore",
    owner=ALICE,
    owner_name="Alice",
    saved_at=ADDED_AT,
    next_at=datetime(2026, 11, 23, 9, 0, tzinfo=SINGAPORE),
)
SCHEDULE_IN = ScheduleIn(day="every_day", at="06:30")
SCHEDULE_SAVED = ScheduleView(
    day="every_day",
    at="06:30",
    time_zone="Asia/Singapore",
    owner=CAROL,
    owner_name="Carol",
    saved_at=CHECKED_AT + timedelta(hours=2),
    next_at=datetime(2026, 11, 17, 6, 30, tzinfo=SINGAPORE),
)

STATUSES = WatchlistView(
    use_case_id=USE_CASE_ID,
    version=7,
    ticket_project="MOCK",
    state="on",
    software=attention_first(ROWS),
    last_check=LastCheckView(run_id=LAST_RUN, state="awaiting_approval", started_at=CHECKED_AT),
    schedule=SCHEDULE,
)

EMPTY = WatchlistView(
    use_case_id=USE_CASE_ID,
    version=8,
    ticket_project="MOCK",
    state="on",
    software=[],
    last_check=STATUSES.last_check,
    schedule=SCHEDULE,
)
SCHEDULE_SAVED_VIEW = STATUSES.model_copy(update={"schedule": SCHEDULE_SAVED})
SCHEDULE_OFF_VIEW = STATUSES.model_copy(update={"schedule": None})
# Alice has left the People list, so her schedule starts no check until an Operator saves it.
SCHEDULE_HELD_VIEW = STATUSES.model_copy(
    update={"schedule": SCHEDULE.model_copy(update={"next_at": None, "held": "owner_removed"})}
)

SCHEDULED_RUN = PendingView(
    run_id=LAST_RUN,
    use_case_id=USE_CASE_ID,
    use_case_name="Software watchlist",
    use_case_version=7,
    started_by=ALICE,
    trigger="schedule",
    started_at=CHECKED_AT,
    updated_at=CHECKED_AT,
    last_seq=2,
    events_url=f"/api/v1/runs/{LAST_RUN}/events",
)

DONE_TICKET = MockJiraTicket(
    key="MOCK-142",
    project="MOCK",
    title=TICKET_TITLE,
    body=TICKET_BODY,
    created_at=SUCCESS.t0 + timedelta(seconds=386.344),
    run_id=SUCCESS.run_id,
    proposal_id=SUCCESS.proposal_id,
    status="Done",
    done_at=datetime(2026, 11, 5, 8, 12, tzinfo=UTC),
)


def watchlist_fixtures() -> dict[str, WireModel | list[WireModel]]:
    return {
        "watchlist/none.json": WatchlistOut(watchlist=None),
        "watchlist/empty.json": EMPTY,
        "watchlist/statuses.json": STATUSES,
        "watchlist/add-software.json": ADD_SOFTWARE,
        "watchlist/schedule.in.json": SCHEDULE_IN,
        "watchlist/schedule.saved.json": SCHEDULE_SAVED_VIEW,
        "watchlist/schedule.off.json": SCHEDULE_OFF_VIEW,
        "watchlist/schedule.held.json": SCHEDULE_HELD_VIEW,
        "internal/tick.started.json": TickOut(started=[LAST_RUN]),
        "internal/tick.nothing-due.json": TickOut(started=[]),
        "views/scheduled.pending.json": SCHEDULED_RUN,
        "stubs/mock-jira-ticket.done.json": DONE_TICKET,
    }
