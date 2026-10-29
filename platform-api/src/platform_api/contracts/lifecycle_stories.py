"""A workflow paused and deleted, and a New workflow draft, as the API answers them."""

from datetime import UTC, datetime, timedelta

from platform_api.builder.lifecycle import RESTORE_WINDOW
from platform_api.builder.models import DraftIn, DraftList, DraftView, UseCaseDeleted
from platform_api.contracts.cards_stories import USE_CASE as AGENT_USE_CASE
from platform_api.contracts.stories import USE_CASE
from platform_api.wire import WireModel

PAUSED = USE_CASE.model_copy(update={"state": "paused", "next_run_at": None})

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
        "builder/use-case.deleted.json": DELETED,
        "builder/draft.in.json": DRAFT_IN,
        "builder/drafts.json": DRAFTS,
    }
