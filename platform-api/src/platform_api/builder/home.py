from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from pydantic import Field

from platform_api.builder.models import DraftView, UseCaseView, WatchedSoftwareView
from platform_api.builder.paging import Cursor, Place, cursor_text, page_of
from platform_api.builder.planner import ChangedInN8nReply
from platform_api.builder.service import Builder
from platform_api.builder.team_requests import (
    FOLLOWING_UP,
    FollowingUpItem,
    FollowingUpPage,
    TeamRequests,
)
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
    QuestionForYou,
    SetUpState,
    Stopped,
    Waiting,
    confirmation_summary,
    set_up_link,
)
from platform_api.shared import ApprovalId, Principal, Role, RunId, UserId
from platform_api.wire import FailureReason, RepoName, Trigger, WireModel

SHOWN = 10
"""Each part of Needs you sends this many rows a page."""
LISTED = 50
"""Waiting on others sends this many rows a page."""
NAME_SHOWN = 80
NEEDS_LISTS = ("approvals", "stopped", "declined", "questions_for_me")
WAITING_LIST = "waiting_on_others"
NEXT = "Pass it as `after` to read the next page. Null when every row has been sent."


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


class QuestionItem(WireModel):
    question_id: str
    approval_id: ApprovalId
    run_id: RunId
    use_case_id: str
    use_case_name: str
    asked_by: UserId
    asked_by_name: str | None = Field(
        description="Null when the Approver who asked is no longer on the list."
    )
    asked_at: datetime
    text: str


class SetUpApprovalItem(WireModel):
    """A drafted workflow's set-up approval that this person may decide now (ADR 0051)."""

    approval_id: str
    drafted_id: str
    name: str
    sent_by_name: str
    sent_at: datetime
    link: str = Field(description="Its approval page, as the Teams card opens it.")


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


class NeedsPage(WireModel):
    """One page of the parts of Needs you that can run long. Each total counts every row."""

    approvals: list[ApprovalItem] = Field(
        description="Runs waiting for a yes this person may give, the newest first, 10 a page."
    )
    approvals_total: int
    stopped: list[StoppedItem] = Field(
        description="Stopped runs an Operator started, owns or retried, while each is the "
        "newest run of its workflow. The newest first, 10 a page."
    )
    stopped_total: int
    declined: list[DeclinedItem] = Field(
        description="An Operator's own test runs that an Approver declined, while each is the "
        "newest run of its workflow, the newest decline first. One leaves when the workflow "
        "runs again. 10 a page."
    )
    declined_total: int
    questions_for_me: list[QuestionItem] = Field(
        description="Questions Approvers asked this person on requests they started, or whose "
        "schedule they own, while each request waits for a yes and the question has no answer. "
        "The newest first, 10 a page."
    )
    questions_for_me_total: int
    next: str | None = Field(description=NEXT)


class WaitingPage(WireModel):
    waiting_on_others: list[WaitingItem] = Field(
        description="Runs waiting for someone else's yes that this person is part of, the newest "
        "first, 50 a page."
    )
    waiting_on_others_total: int
    next: str | None = Field(description=NEXT)


class HomeOut(WireModel):
    """The first page of each list that can run long, with its total, and the cursor that reads
    the rest, so every row a total counts can be reached."""

    approvals: list[ApprovalItem] = Field(
        description="Runs waiting for a yes this person may give, the newest first. The first 10."
    )
    approvals_total: int
    confirmations: list[ConfirmationItem] = Field(
        description="Setup changes this person may confirm, the newest first."
    )
    stopped: list[StoppedItem] = Field(
        description="Stopped runs an Operator started, owns or retried, while each is the "
        "newest run of its workflow. The newest first. The first 10."
    )
    stopped_total: int
    waiting_on_others: list[WaitingItem] = Field(
        description="Runs waiting for someone else's yes that this person is part of. The first 50."
    )
    waiting_on_others_total: int
    waiting_on_others_next: str | None = Field(
        description="Pass it as `after` to `/api/v1/home/waiting-on-others` for the rest. Null "
        "when all are here."
    )
    declined: list[DeclinedItem] = Field(
        description="An Operator's own test runs that an Approver declined, while each is the "
        "newest run of its workflow, the newest decline first. They are part of Needs you, and "
        "one leaves when the workflow runs again. The first 10."
    )
    declined_total: int
    questions_for_me: list[QuestionItem] = Field(
        description="Questions Approvers asked this person on requests they started, or whose "
        "schedule they own, while each request waits for a yes and the question has no answer. "
        "The newest first. They are part of Needs you. The first 10."
    )
    questions_for_me_total: int
    needs_next: str | None = Field(
        description="Pass it as `after` to `/api/v1/home/needs` for the rest of approvals, "
        "stopped, declined and questions_for_me. Null when all are here."
    )
    setup_approvals: list[SetUpApprovalItem] = Field(
        description="Drafted workflows' set-up approvals this person may decide now, the newest "
        "first. They are part of Needs you, and the Teams button counts them with the runs."
    )
    drafts: list[DraftItem] = Field(description="An Operator's own drafts, the last saved first.")
    following_up: list[FollowingUpItem] = Field(
        description="This person's own requests to the team, Ask the team and Report to "
        "support, the newest first, with the status and the latest reply. The first 50. A "
        "request marked Done leaves after 30 days."
    )
    following_up_total: int
    following_up_next: str | None = Field(
        description="Pass it as `after` to `/api/v1/home/following-up` for the rest. Null when "
        "all are here."
    )
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
    changed_in_n8n: list[ChangedInN8nReply] = Field(
        description="For an Operator, the versions published in n8n's editor in the last day, "
        "the newest first, at most 10, each as the chat's Changed in n8n card shows it."
    )


class RunsForPerson(Protocol):
    async def runs_for(self, viewer: Principal) -> PersonRuns: ...


class SetUpsForHome(Protocol):
    async def waiting_for(self, principal: Principal) -> list[SetUpState]: ...


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


def _question(asked: QuestionForYou, names: dict[UserId, str]) -> QuestionItem:
    run, question = asked.run, asked.question
    return QuestionItem(
        question_id=question.id,
        approval_id=question.approval_id,
        run_id=run.run_id,
        use_case_id=run.use_case_id,
        use_case_name=run.use_case_name,
        asked_by=question.asked_by,
        asked_by_name=names.get(question.asked_by),
        asked_at=question.asked_at,
        text=question.text,
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


def _set_up(state: SetUpState) -> SetUpApprovalItem:
    request = state.request
    return SetUpApprovalItem(
        approval_id=request.id,
        drafted_id=request.drafted_id,
        name=request.name,
        sent_by_name=state.names.get(request.sent_by, "Someone"),
        sent_at=request.created_at,
        link=set_up_link(request.id),
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


def _run_place(row: Ask | Stopped | Waiting) -> Place:
    """Where the run sits among runs started, the newest first, as the runs are read."""
    return Place(row.run.started_at, row.run.run_id)


def _part[R](
    rows: Sequence[R],
    place: Callable[[R], Place],
    name: str,
    after: Cursor | None,
    left: dict[str, Place],
    size: int = SHOWN,
) -> list[R]:
    """One list's rows on this page. A list the cursor leaves out has sent all its rows."""
    if after is not None and name not in after:
        return []
    page, rest = page_of(rows, place, None if after is None else after[name], size)
    if rest is not None:
        left[name] = rest
    return page


def _needs_page(
    runs: PersonRuns, live: set[str], names: dict[UserId, str], after: Cursor | None
) -> NeedsPage:
    stopped = [s for s in runs.stopped if s.run.use_case_id in live]
    declined = [d for d in runs.declined if d.run.use_case_id in live]
    left: dict[str, Place] = {}
    return NeedsPage(
        approvals=[
            _approval(a, names) for a in _part(runs.asks, _run_place, "approvals", after, left)
        ],
        approvals_total=len(runs.asks),
        stopped=[_stopped(s) for s in _part(stopped, _run_place, "stopped", after, left)],
        stopped_total=len(stopped),
        declined=[
            _declined(d, names)
            for d in _part(
                declined, lambda d: Place(d.declined_at, d.run.run_id), "declined", after, left
            )
        ],
        declined_total=len(declined),
        questions_for_me=[
            _question(q, names)
            for q in _part(
                runs.questions,
                lambda q: Place(q.question.asked_at, q.question.id),
                "questions_for_me",
                after,
                left,
            )
        ],
        questions_for_me_total=len(runs.questions),
        next=cursor_text(left),
    )


def _waiting_page(runs: PersonRuns, after: Cursor | None) -> WaitingPage:
    left: dict[str, Place] = {}
    waiting = _part(runs.waiting, _run_place, WAITING_LIST, after, left, LISTED)
    return WaitingPage(
        waiting_on_others=[_waiting(w) for w in waiting],
        waiting_on_others_total=len(runs.waiting),
        next=cursor_text(left),
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
        setups: SetUpsForHome | None = None,
    ) -> None:
        self._builder = builder
        self._runs = runs
        self._people = people
        self._requests = requests
        self._connections = connections
        self._addresses = addresses
        self._setups = setups

    async def _names(self) -> dict[UserId, str]:
        return {p.user_id: p.display for p in await self._people.listed()}

    async def needs(self, viewer: Principal, after: Cursor | None) -> NeedsPage:
        """The page of Needs you after the cursor `needs_next` or an earlier page gave out, or
        the first page, as Home has it."""
        use_cases = (await self._builder.list_use_cases()).use_cases
        live = {u.use_case_id for u in use_cases}
        return _needs_page(await self._runs.runs_for(viewer), live, await self._names(), after)

    async def waiting_on_others(self, viewer: Principal, after: Cursor | None) -> WaitingPage:
        return _waiting_page(await self._runs.runs_for(viewer), after)

    async def following_up(self, viewer: Principal, after: Cursor | None) -> FollowingUpPage:
        place = None if after is None else after[FOLLOWING_UP]
        return await self._requests.following_up(viewer, place)

    async def for_person(self, viewer: Principal) -> HomeOut:
        runs = await self._runs.runs_for(viewer)
        names = await self._names()
        confirmations = sorted(
            (row for row in await self._people.confirmations(viewer) if row.why_not is None),
            key=lambda row: row.confirmation.asked_at,
            reverse=True,
        )
        use_cases = (await self._builder.list_use_cases()).use_cases
        needs = _needs_page(runs, {u.use_case_id for u in use_cases}, names, None)
        waiting = _waiting_page(runs, None)
        operator = Role.OPERATOR in viewer.roles
        drafts = (await self._builder.list_drafts(viewer)).drafts if operator else []
        following = await self._requests.following_up(viewer, None)
        connections = await self._connections.needing_attention() if operator else []
        addresses = await self._addresses.needing_attention() if operator else []
        replied = await self._requests.replied(viewer)
        changed = [
            card.model_copy(update={"by_name": None if card.by is None else names.get(card.by)})
            for card in (await self._builder.changed_in_n8n(SHOWN) if operator else [])
        ]
        return HomeOut(
            approvals=needs.approvals,
            approvals_total=needs.approvals_total,
            confirmations=[_confirmation(row) for row in confirmations],
            stopped=needs.stopped,
            stopped_total=needs.stopped_total,
            declined=needs.declined,
            declined_total=needs.declined_total,
            questions_for_me=needs.questions_for_me,
            questions_for_me_total=needs.questions_for_me_total,
            needs_next=needs.next,
            waiting_on_others=waiting.waiting_on_others,
            waiting_on_others_total=waiting.waiting_on_others_total,
            waiting_on_others_next=waiting.next,
            setup_approvals=[
                _set_up(state)
                for state in (
                    [] if self._setups is None else await self._setups.waiting_for(viewer)
                )
            ],
            drafts=[_draft(d) for d in drafts],
            following_up=following.following_up,
            following_up_total=following.following_up_total,
            following_up_next=following.next,
            replied=replied,
            coming_up=_coming_up(use_cases),
            workflows=len(use_cases),
            addresses=[_address(a) for a in addresses],
            connections=[_connection(c) for c in connections],
            changed_in_n8n=changed,
        )
