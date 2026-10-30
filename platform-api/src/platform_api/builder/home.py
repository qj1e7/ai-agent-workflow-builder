from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import Field

from platform_api.builder.models import DraftView, UseCaseView
from platform_api.builder.service import Builder
from platform_api.monitoring import Advice, RunFailedData, explain_failure
from platform_api.orchestration import (
    Ask,
    Because,
    Change,
    ConfirmationKind,
    ConfirmationRow,
    PersonRuns,
    Stopped,
    Waiting,
    confirmation_summary,
)
from platform_api.shared import ApprovalId, Principal, Role, RunId, UserId
from platform_api.wire import FailureReason, Trigger, WireModel

SHOWN = 10
NAME_SHOWN = 80


class ChangeLine(WireModel):
    connector: str
    operation: str
    title: str | None


class ApprovalItem(WireModel):
    run_id: RunId
    approval_id: ApprovalId
    use_case_id: str
    use_case_name: str
    started_by: UserId
    started_by_name: str | None = Field(
        description="Null when the person who started it is no longer on the list."
    )
    trigger: Trigger
    started_at: datetime
    step: int = Field(description="The step waiting for a yes, from 0.")
    steps: int
    step_label: str
    changes: int = Field(description="How many changes the run would write.")
    first_changes: list[ChangeLine] = Field(description="The first few of them.")


class ConfirmationItem(WireModel):
    confirmation_id: str
    kind: ConfirmationKind
    summary: str
    about_name: str | None = Field(description="The person a new Approver role is about.")
    asked_by_name: str
    asked_at: datetime


class StoppedItem(WireModel):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    started_at: datetime
    stopped_at: datetime
    reason: FailureReason
    retryable: bool
    advice: Advice = Field(description="The AI troubleshooter's reason and what to do.")


class WaitingItem(WireModel):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    trigger: Trigger
    started_at: datetime
    step: int
    steps: int
    because: Because = Field(
        description="Why this person cannot say yes: they started, retried or own the run, "
        "or they said yes to an earlier step."
    )


class DraftItem(WireModel):
    draft_id: str
    name: str | None = Field(description="The draft's `name`, when the Portal saved one.")
    step: int
    saved_at: datetime


class ComingUp(WireModel):
    use_case_id: str
    name: str
    template: str
    next_run_at: datetime
    more: int = Field(description="How many other workflows have a next run.")


class HomeOut(WireModel):
    approvals: list[ApprovalItem] = Field(
        description="Runs waiting for a yes this person may give, the newest first. At most 10."
    )
    approvals_total: int
    confirmations: list[ConfirmationItem] = Field(
        description="Setup changes this person may confirm, the newest first."
    )
    stopped: list[StoppedItem] = Field(
        description="Stopped runs an Operator started, owns or retried, while each is the "
        "newest run of its workflow. The newest first. At most 10."
    )
    stopped_total: int
    waiting_on_others: list[WaitingItem] = Field(
        description="Runs waiting for someone else's yes that this person is part of. At most 10."
    )
    waiting_on_others_total: int
    drafts: list[DraftItem] = Field(description="An Operator's own drafts, the last saved first.")
    coming_up: ComingUp | None = Field(description="The workflow that runs next, if any.")
    workflows: int = Field(description="How many workflows the team has.")


class RunsForPerson(Protocol):
    async def runs_for(self, viewer: Principal) -> PersonRuns: ...


class PeopleForHome(Protocol):
    async def confirmations(self, viewer: Principal) -> list[ConfirmationRow]: ...

    async def listed(self) -> list[Principal]: ...


def _change(change: Change) -> ChangeLine:
    return ChangeLine(connector=change.connector, operation=change.operation, title=change.title)


def _approval(ask: Ask, names: dict[UserId, str]) -> ApprovalItem:
    run = ask.run
    return ApprovalItem(
        run_id=run.run_id,
        approval_id=ask.approval_id,
        use_case_id=run.use_case_id,
        use_case_name=run.use_case_name,
        started_by=run.started_by,
        started_by_name=names.get(run.started_by),
        trigger=run.trigger,
        started_at=run.started_at,
        step=ask.step,
        steps=ask.steps,
        step_label=ask.step_label,
        changes=ask.changes,
        first_changes=[_change(c) for c in ask.first_changes],
    )


def _stopped(stop: Stopped) -> StoppedItem:
    run = stop.run
    failure = RunFailedData(
        stage=stop.stage, reason=stop.reason, retryable=stop.retryable, message=stop.message
    )
    return StoppedItem(
        run_id=run.run_id,
        use_case_id=run.use_case_id,
        use_case_name=run.use_case_name,
        started_at=run.started_at,
        stopped_at=stop.stopped_at,
        reason=stop.reason,
        retryable=stop.retryable,
        advice=explain_failure(failure),
    )


def _waiting(wait: Waiting) -> WaitingItem:
    run = wait.run
    return WaitingItem(
        run_id=run.run_id,
        use_case_id=run.use_case_id,
        use_case_name=run.use_case_name,
        trigger=run.trigger,
        started_at=run.started_at,
        step=wait.step,
        steps=wait.steps,
        because=wait.because,
    )


def _confirmation(row: ConfirmationRow) -> ConfirmationItem:
    c = row.confirmation
    return ConfirmationItem(
        confirmation_id=c.id,
        kind=c.kind,
        summary=confirmation_summary(c, row.about),
        about_name=row.about.display if row.about is not None else None,
        asked_by_name=row.asked_by_name,
        asked_at=c.asked_at,
    )


def _draft(draft: DraftView) -> DraftItem:
    saved = draft.content.get("name")
    name = saved.strip() if isinstance(saved, str) and saved.strip() else None
    if name is not None and len(name) > NAME_SHOWN:
        name = name[: NAME_SHOWN - 1].rstrip() + "…"
    return DraftItem(draft_id=draft.draft_id, name=name, step=draft.step, saved_at=draft.saved_at)


def _coming_up(use_cases: Sequence[UseCaseView]) -> ComingUp | None:
    scheduled = [(u.next_run_at, u) for u in use_cases if u.next_run_at is not None]
    if not scheduled:
        return None
    at, first = min(scheduled, key=lambda pair: (pair[0], pair[1].use_case_id))
    return ComingUp(
        use_case_id=first.use_case_id,
        name=first.name,
        template=first.template,
        next_run_at=at,
        more=len(scheduled) - 1,
    )


class Home:
    def __init__(self, builder: Builder, runs: RunsForPerson, people: PeopleForHome) -> None:
        self._builder = builder
        self._runs = runs
        self._people = people

    async def for_person(self, viewer: Principal) -> HomeOut:
        runs = await self._runs.runs_for(viewer)
        names = {p.user_id: p.display for p in await self._people.listed()}
        confirmations = sorted(
            (row for row in await self._people.confirmations(viewer) if row.why_not is None),
            key=lambda row: row.confirmation.asked_at,
            reverse=True,
        )
        use_cases = (await self._builder.list_use_cases()).use_cases
        live = {u.use_case_id for u in use_cases}
        stopped = [s for s in runs.stopped if s.run.use_case_id in live]
        drafts = (
            (await self._builder.list_drafts(viewer)).drafts
            if Role.OPERATOR in viewer.roles
            else []
        )
        return HomeOut(
            approvals=[_approval(a, names) for a in runs.asks[:SHOWN]],
            approvals_total=len(runs.asks),
            confirmations=[_confirmation(row) for row in confirmations],
            stopped=[_stopped(s) for s in stopped[:SHOWN]],
            stopped_total=len(stopped),
            waiting_on_others=[_waiting(w) for w in runs.waiting[:SHOWN]],
            waiting_on_others_total=len(runs.waiting),
            drafts=[_draft(d) for d in drafts],
            coming_up=_coming_up(use_cases),
            workflows=len(use_cases),
        )
