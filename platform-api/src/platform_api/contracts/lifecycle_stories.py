"""A workflow paused, held, deleted and changed, the watchlist paused, and a set-up card draft,
as the API answers them."""

from datetime import UTC, datetime, timedelta

from platform_api.builder.lifecycle import RESTORE_WINDOW
from platform_api.builder.models import (
    DraftIn,
    DraftList,
    DraftView,
    LastRunView,
    ScheduleChangeView,
    UndoIn,
    UseCaseDeleted,
    UseCaseScheduleIn,
    VersionChange,
    VersionList,
    VersionSchedule,
    VersionView,
)
from platform_api.contracts.cards_stories import USE_CASE as AGENT_USE_CASE
from platform_api.contracts.stories import ALICE, BOB, REJECTED, USE_CASE, USE_CASE_SCHEDULE
from platform_api.contracts.watchlist_stories import SCHEDULE, STATUSES
from platform_api.wire import WireModel

PAUSED = USE_CASE.model_copy(update={"state": "paused", "next_run_at": None})
LAST_RUN = LastRunView(
    run_id=REJECTED.run_id,
    state="rejected",
    at=REJECTED.t0,
    test=False,
    declined_by=BOB,
    proposed=1,
    written=0,
    tickets=True,
    you_can_decide=False,
    retryable=False,
    reason=None,
)
# Bob declined the last check. Nothing was written. The decline reason is not part of the
# record yet.
DECLINED = USE_CASE.model_copy(update={"last_run": LAST_RUN})
# The last check waits for a yes that Bob may give.
WAITING = USE_CASE.model_copy(
    update={
        "last_run": LAST_RUN.model_copy(
            update={"state": "awaiting_approval", "declined_by": None, "you_can_decide": True}
        )
    }
)
# The last run of a workflow a person started by hand stopped, and a retry may start it again.
STOPPED = AGENT_USE_CASE.model_copy(
    update={
        "last_run": LAST_RUN.model_copy(
            update={
                "state": "failed",
                "test": True,
                "declined_by": None,
                "proposed": 0,
                "tickets": False,
                "retryable": True,
                "reason": "AgentError",
            }
        )
    }
)
# Alice has left the People list, so the watchlist's schedule starts no run until an Operator
# saves it.
HELD = USE_CASE.model_copy(
    update={
        "next_run_at": None,
        "schedule": USE_CASE_SCHEDULE.model_copy(update={"held": "owner_removed"}),
    }
)
PAUSED_WATCHLIST = STATUSES.model_copy(
    update={"state": "paused", "schedule": SCHEDULE.model_copy(update={"next_at": None})}
)

DELETED_AT = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
DELETED = UseCaseDeleted(
    use_case_id=AGENT_USE_CASE.use_case_id,
    deleted_at=DELETED_AT,
    restore_until=DELETED_AT + RESTORE_WINDOW,
)

DRAFT_IN = DraftIn(
    step=2,
    content={
        "intent": "Every Wednesday, find tickets in MOCK with no update for 14 days and send "
        "each owner a short message in Teams.",
        "name": "Nudge stale tickets",
        "schedule": {"day": "wednesday", "at": "10:00"},
    },
)
STARTED_AT = datetime(2026, 11, 4, 6, 20, tzinfo=UTC)
DRAFTS = DraftList(
    drafts=[
        DraftView(
            draft_id="drf-7f3a2c",
            step=DRAFT_IN.step,
            content=DRAFT_IN.content,
            created_at=STARTED_AT,
            saved_at=STARTED_AT + timedelta(minutes=4),
        )
    ]
)


# Alice changed the agent workflow from every weekday at 8:00 to every Monday at 8:00 from the
# chat, then undid it on its page, as in the prototype's scenario ANS-edit-save.
WEEKDAYS = VersionSchedule(day="weekdays", at="08:00", time_zone="Asia/Singapore")
MONDAYS = VersionSchedule(day="monday", at="08:00", time_zone="Asia/Singapore")
CHANGED_AT = datetime(2026, 11, 4, 1, 10, tzinfo=UTC)
FIRST = VersionView(
    version=1,
    at=AGENT_USE_CASE.created_at,
    by=None,
    via=None,
    change=None,
    undid=None,
    running=False,
)
CHANGED = VersionView(
    version=2,
    at=CHANGED_AT,
    by=ALICE,
    via="chat",
    change=VersionChange(schedule=ScheduleChangeView(before=WEEKDAYS, after=MONDAYS)),
    undid=None,
    running=True,
)
UNDONE = VersionView(
    version=3,
    at=CHANGED_AT + timedelta(minutes=2),
    by=ALICE,
    via="page",
    change=VersionChange(schedule=ScheduleChangeView(before=MONDAYS, after=WEEKDAYS)),
    undid=2,
    running=True,
)
VERSIONS = VersionList(versions=[CHANGED, FIRST])
VERSIONS_UNDONE = VersionList(
    versions=[UNDONE, CHANGED.model_copy(update={"running": False}), FIRST]
)
SCHEDULED_BY_ALICE = USE_CASE_SCHEDULE.model_copy(
    update={"day": "monday", "at": "08:00", "owner_name": "Alice", "held": None}
)
VERSIONED = AGENT_USE_CASE.model_copy(
    update={
        "version": 2,
        "schedule": SCHEDULED_BY_ALICE,
        "next_run_at": datetime(2026, 11, 9, 0, 0, tzinfo=UTC),
    }
)
UNDONE_USE_CASE = AGENT_USE_CASE.model_copy(
    update={
        "version": 3,
        "schedule": SCHEDULED_BY_ALICE.model_copy(update={"day": "weekdays"}),
        "next_run_at": datetime(2026, 11, 5, 0, 0, tzinfo=UTC),
    }
)


def lifecycle_fixtures() -> dict[str, WireModel | list[WireModel]]:
    return {
        "builder/use-case.paused.json": PAUSED,
        "builder/use-case.held.json": HELD,
        "builder/use-case.declined.json": DECLINED,
        "builder/use-case.waiting.json": WAITING,
        "builder/use-case.stopped.json": STOPPED,
        "watchlist/paused.json": PAUSED_WATCHLIST,
        "builder/use-case.deleted.json": DELETED,
        "builder/draft.in.json": DRAFT_IN,
        "builder/drafts.json": DRAFTS,
        "builder/schedule.in.json": UseCaseScheduleIn(day="monday", at="08:00", via="chat"),
        "builder/undo.in.json": UndoIn(via="page"),
        "builder/use-case.versioned.json": VERSIONED,
        "builder/use-case.undone.json": UNDONE_USE_CASE,
        "builder/versions.json": VERSIONS,
        "builder/versions.undone.json": VERSIONS_UNDONE,
    }
