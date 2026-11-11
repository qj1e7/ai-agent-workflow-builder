"""A workflow paused, held and deleted, the watchlist paused, and a set-up card draft, as the
API answers them."""

from datetime import UTC, datetime, timedelta

from platform_api.builder.lifecycle import RESTORE_WINDOW
from platform_api.builder.models import DraftIn, DraftList, DraftView, LastRunView, UseCaseDeleted
from platform_api.contracts.cards_stories import USE_CASE as AGENT_USE_CASE
from platform_api.contracts.stories import BOB, REJECTED, USE_CASE, USE_CASE_SCHEDULE
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
    }
