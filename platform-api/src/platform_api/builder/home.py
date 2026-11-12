from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import Field

from platform_api.builder.models import DraftView, UseCaseView, WatchedSoftwareView
from platform_api.builder.service import Builder
from platform_api.builder.team_requests import FollowingUpItem, TeamRequests
from platform_api.monitoring import Advice, RunFailedData, explain_failure
from platform_api.orchestration import (
    Ask,
    Because,
    Change,
    ConfirmationKind,
    ConfirmationRow,
    ConnectionCheck,
    ConnectionId,
    ConnectionState,
    DeclinedTest,
    PersonRuns,
    Stopped,
    Waiting,
    confirmation_summary,
)
from platform_api.shared import ApprovalId, Principal, Role, RunId, UserId
from platform_api.wire import FailureReason, RepoName, Trigger, WireModel

SHOWN = 10
LISTED = 50
"""Waiting on others and Following up list every row they have, up to this many, so nobody meets
an "And more" with no way to see the rest. Past it the section says how many it shows."""
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


class DeclinedItem(WireModel):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    started_at: datetime
    declined_at: datetime
    declined_by: UserId
    declined_by_name: str | None = Field(
        description="Null when the Approver who declined is no longer on the list."
    )
    decline_reason: str | None = Field(
        description="Why the Approver declined, when they gave a reason."
    )


class DraftItem(WireModel):
    draft_id: str
    name: str | None = Field(description="The draft's `name`, when the Portal saved one.")
    step: int | None
    saved_at: datetime


class ComingUp(WireModel):
    use_case_id: str
    name: str
    template: str
    next_run_at: datetime
    time_zone: str = Field(
        description="The time zone of its schedule, as on the workflow, so every page shows "
        "the next run at the same hour."
    )
    more: int = Field(description="How many other workflows have a next run.")


class ConnectionItem(WireModel):
    id: ConnectionId
    name: str
    state: ConnectionState
    problem: str | None
    fix: str | None
    checked_at: datetime | None = Field(
        description="When the result shown was found. Null while nothing has been tried with "
        "the address and key in use now."
    )
    last_ok_at: datetime | None
    expires_at: datetime | None = Field(
        description="When the system says the key runs out. A working connection is here only "
        "when that is soon."
    )


class AddressItem(WireModel):
    software_id: str
    name: str
    repo: RepoName = Field(description="The repository saved for it.")
    moved_to: RepoName | None = Field(
        description="The repository GitHub now calls it, when it was renamed. The Operator may "
        "switch the list to it."
    )
    not_found: bool = Field(
        description="GitHub said the saved repository does not exist and named no new home."
    )
    checked_at: datetime | None


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
        description="Runs waiting for someone else's yes that this person is part of. At most 50."
    )
    waiting_on_others_total: int
    declined: list[DeclinedItem] = Field(
        description="This person's own test runs that an Approver declined, while each is the "
        "newest run of its workflow, the newest decline first. They are part of Needs you, and "
        "one leaves when the workflow runs again. At most 10."
    )
    declined_total: int
    drafts: list[DraftItem] = Field(description="An Operator's own drafts, the last saved first.")
    following_up: list[FollowingUpItem] = Field(
        description="This person's own requests to the team, Ask the team and Report to "
        "support, the newest first, with the status and the latest reply. At most 50. A request "
        "marked Done leaves after 30 days."
    )
    following_up_total: int
    replied: list[FollowingUpItem] = Field(
        description="This person's own requests that someone on the team has replied to since "
        "they last opened them, the newest reply first, each with that reply. They are part of "
        "Needs you, and a request leaves this list when its asker opens it. Done requests "
        "leave after 30 days."
    )
    coming_up: ComingUp | None = Field(description="The workflow that runs next, if any.")
    workflows: int = Field(description="How many workflows the team has.")
    addresses: list[AddressItem] = Field(
        description="For an Operator, the watched software whose repository GitHub moved or "
        "cannot find, as the latest check left it, in the order of the Software page. The same "
        "rows the Software page lists under Needs attention."
    )
    connections: list[ConnectionItem] = Field(
        description="For an Operator, the connections that do not work and the keys that run "
        "out soon, as the last check left them, and the AI model while none is set up, as its "
        "settings say now. Home never starts a check."
    )


class RunsForPerson(Protocol):
    async def runs_for(self, viewer: Principal) -> PersonRuns: ...


class ConnectionsForHome(Protocol):
    async def needing_attention(self) -> list[ConnectionCheck]: ...


class AddressesForHome(Protocol):
    async def needing_attention(self) -> list[WatchedSoftwareView]: ...


class PeopleForHome(Protocol):
    async def confirmations(self, viewer: Principal) -> list[ConfirmationRow]: ...

    async def listed(self) -> list[Principal]: ...


def _connection(check: ConnectionCheck) -> ConnectionItem:
    return ConnectionItem(
        id=check.id,
        name=check.name,
        state=check.state,
        problem=check.problem,
        fix=check.fix,
        checked_at=check.checked_at,
        last_ok_at=check.last_ok_at,
        expires_at=check.expires_at,
    )


def _address(row: WatchedSoftwareView) -> AddressItem:
    return AddressItem(
        software_id=row.id,
        name=row.name,
        repo=row.source.ref,
        moved_to=row.moved_to,
        not_found=row.not_found,
        checked_at=row.checked_at,
    )


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


def _declined(test: DeclinedTest, names: dict[UserId, str]) -> DeclinedItem:
    run = test.run
    return DeclinedItem(
        run_id=run.run_id,
        use_case_id=run.use_case_id,
        use_case_name=run.use_case_name,
        started_at=run.started_at,
        declined_at=test.declined_at,
        declined_by=test.declined_by,
        declined_by_name=names.get(test.declined_by),
        decline_reason=test.reason,
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
    scheduled = [
        (u.next_run_at, u.schedule, u)
        for u in use_cases
        if u.next_run_at is not None and u.schedule is not None
    ]
    if not scheduled:
        return None
    at, schedule, first = min(scheduled, key=lambda row: (row[0], row[2].use_case_id))
    return ComingUp(
        use_case_id=first.use_case_id,
        name=first.name,
        template=first.template,
        next_run_at=at,
        time_zone=schedule.time_zone,
        more=len(scheduled) - 1,
    )


class Home:
    def __init__(
        self,
        builder: Builder,
        runs: RunsForPerson,
        people: PeopleForHome,
        requests: TeamRequests,
        connections: ConnectionsForHome,
        addresses: AddressesForHome,
    ) -> None:
        self._builder = builder
        self._runs = runs
        self._people = people
        self._requests = requests
        self._connections = connections
        self._addresses = addresses

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
        declined = sorted(
            (d for d in runs.declined if d.run.use_case_id in live),
            key=lambda d: d.declined_at,
            reverse=True,
        )
        drafts = (
            (await self._builder.list_drafts(viewer)).drafts
            if Role.OPERATOR in viewer.roles
            else []
        )
        following_up, following_up_total = await self._requests.following_up(viewer)
        operator = Role.OPERATOR in viewer.roles
        connections = await self._connections.needing_attention() if operator else []
        addresses = await self._addresses.needing_attention() if operator else []
        replied = await self._requests.replied(viewer)
        return HomeOut(
            approvals=[_approval(a, names) for a in runs.asks[:SHOWN]],
            approvals_total=len(runs.asks),
            confirmations=[_confirmation(row) for row in confirmations],
            stopped=[_stopped(s) for s in stopped[:SHOWN]],
            stopped_total=len(stopped),
            declined=[_declined(d, names) for d in declined[:SHOWN]],
            declined_total=len(declined),
            waiting_on_others=[_waiting(w) for w in runs.waiting[:LISTED]],
            waiting_on_others_total=len(runs.waiting),
            drafts=[_draft(d) for d in drafts],
            following_up=following_up,
            following_up_total=following_up_total,
            replied=replied,
            coming_up=_coming_up(use_cases),
            workflows=len(use_cases),
            addresses=[_address(a) for a in addresses],
            connections=[_connection(c) for c in connections],
        )
