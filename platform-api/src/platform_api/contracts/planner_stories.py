"""Fixtures for the Planner on Home: the answer of each kind, the offline answer, a checked part
and the capabilities.

The capabilities are the agent runtime's own registry file (`agent/capabilities.json`), run
through the route's code, so the Portal reads what the route would send. Generate the runtime's
fixtures first when its registry changes.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from platform_api.builder.cards import VERSION_CHECKER, sorted_for_library
from platform_api.builder.models import CardList, UnderstoodRowView, UseCaseList
from platform_api.builder.planner import (
    AbilitiesReply,
    AnswerIn,
    CantReply,
    CantRowView,
    CheckPartIn,
    CheckWorkflowsReply,
    DecidedReply,
    DecideReply,
    EditAfter,
    EditBefore,
    EditChoice,
    EditReply,
    IdeasReply,
    ListedSoftware,
    NeedsMeReply,
    OperatorsReply,
    PartCheckCantDo,
    PartCheckFits,
    PartReply,
    PartView,
    PlannerFront,
    QuestionReply,
    RefusedReply,
    ReplyReason,
    SetupCardReply,
    SimilarWorkflow,
    WatchlistReply,
    WhichSoftwareReply,
    WhyStoppedReply,
    offline,
)
from platform_api.orchestration import (
    CapabilityList,
    CheckPartResult,
    ConnectionCheck,
    ConnectionId,
    ConnectionState,
    NoModel,
    PlannerFacts,
    PreviousTurn,
    RuntimeDown,
)
from platform_api.shared import Principal
from platform_api.wire import WireModel

CHECKED = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
FRIDAY = "Every Friday, sum up the tickets we closed this week"
ROWS = [
    UnderstoodRowView(kind="schedule", text="Every Friday", state="understood", note=None),
    UnderstoodRowView(
        kind="look_for",
        text="Tickets closed this week in MOCK",
        state="changed",
        note="You said “the tickets we closed”. I read that as MOCK, the project on your list.",
    ),
    UnderstoodRowView(
        kind="do", text="Sum them up in one new ticket", state="understood", note=None
    ),
    UnderstoodRowView(kind="where", text="In the MOCK project", state="understood", note=None),
]


def does(text: str) -> PartView:
    return PartView(text=text, mark="will_do", reason=None, note=None, choices=[])


def crossed(text: str, reason: ReplyReason, *choices: str, note: str | None = None) -> PartView:
    return PartView(text=text, mark="cant", reason=reason, note=note, choices=list(choices))


EDIT = EditReply(
    use_case_id="uc_01JB8",
    name="Morning new-ticket check",
    watchlist=False,
    missing=None,
    software=None,
    choices=[],
    before=EditBefore(day="weekdays", at="08:00"),
    after=EditAfter(day="monday", at="08:00"),
    hour=None,
    cant=None,
    holds_save=False,
    parts=[does("Make the morning new-ticket check run on Mondays only")],
)

SETUP_CARD = SetupCardReply(
    name="Weekly summary of closed tickets",
    rows=ROWS,
    similar=None,
    parts=[does("Every Friday"), does("sum up the tickets we closed this week")],
)
CROSS_ROWS = [
    UnderstoodRowView(kind="schedule", text="Every Friday at 17:00", state="understood", note=None),
    UnderstoodRowView(
        kind="look_for", text="Tickets closed this week in MOCK", state="understood", note=None
    ),
    UnderstoodRowView(
        kind="do", text="Sum them up in one new ticket", state="understood", note=None
    ),
]
CLASH_ROWS = [
    UnderstoodRowView(
        kind="schedule",
        text="",
        state="missing",
        note='Your words said "Monday" and "Friday". I can only set one day, so please choose one.',
    ),
    UnderstoodRowView(
        kind="look_for", text="Closed tickets in MOCK", state="understood", note=None
    ),
    UnderstoodRowView(
        kind="do", text="Sum them up in one new ticket", state="understood", note=None
    ),
]
EMAIL = CantRowView(
    kind="do",
    text="email it to the team",
    note="I can't email it to the team. I can only read Jira tickets, sum up what I find, "
    "check software for new releases, create a Jira ticket after a yes, and ask Approvers for a "
    "yes in Teams.",
    needs="new_system",
    system="email",
)


def check(
    id: ConnectionId,
    state: ConnectionState = "working",
    problem: str | None = None,
    fix: str | None = None,
    checked_at: datetime | None = CHECKED,
    last_ok_at: datetime | None = CHECKED,
) -> ConnectionCheck:
    return ConnectionCheck(
        id=id,
        name=id.title(),
        practice=False,
        state=state,
        checked_at=checked_at,
        last_ok_at=last_ok_at,
        problem=problem,
        key_ends_in=None,
        expires_at=None,
        fix=fix,
    )


class _Answers:
    async def answer(
        self,
        task: str,
        facts: PlannerFacts | None = None,
        previous: PreviousTurn | None = None,
        changes_workflows: bool = True,
    ) -> NoModel:
        return NoModel()

    async def check_part(self, kind: str, text: str) -> CheckPartResult | RuntimeDown:
        return RuntimeDown("not asked")


class _Registry:
    def __init__(self, listed: CapabilityList) -> None:
        self._listed = listed

    async def get(self) -> CapabilityList:
        return self._listed


class _Connections:
    def __init__(self, *checks: ConnectionCheck) -> None:
        self._checks = list(checks)

    async def view(self) -> list[ConnectionCheck]:
        return self._checks


class _Workflows:
    async def list_use_cases(self) -> UseCaseList:
        return UseCaseList(use_cases=[])

    async def get_use_case(self, use_case_id: str) -> None:
        return None

    async def list_cards(self) -> CardList:
        return CardList(cards=sorted_for_library([VERSION_CHECKER], []))


class _Facts:
    async def read(self, viewer: Principal) -> PlannerFacts:
        return PlannerFacts()


class _Watchlist:
    async def view(self) -> None:
        return None


def _capabilities(root: Path, *checks: ConnectionCheck) -> WireModel:
    listed = CapabilityList.model_validate_json(
        (root / "fixtures" / "agent" / "capabilities.json").read_text()
    )
    front = PlannerFront(
        _Answers(),
        _Workflows(),
        _Watchlist(),
        _Registry(listed),
        _Connections(*checks),
        _Facts(),
    )
    view = asyncio.run(front.capabilities())
    assert isinstance(view, WireModel)
    return view


def planner_fixtures(root: Path) -> dict[str, WireModel]:
    return {
        "planner/answer.text.json": AnswerIn(text=FRIDAY),
        "planner/answer.intent.json": AnswerIn(intent="why_stopped", use_case_id="uc_01JB8"),
        "planner/answer.setup_card.json": SETUP_CARD.model_copy(
            update={"similar": SimilarWorkflow(use_case_id="uc_01JB8", name=SETUP_CARD.name)}
        ),
        "planner/answer.setup_card.cross.json": SetupCardReply(
            name="Friday closed ticket summary",
            rows=CROSS_ROWS,
            similar=None,
            parts=[
                does("Every Friday at 5pm"),
                does("sum up the tickets we closed this week in MOCK"),
                crossed("colour them by team", "not_followed"),
            ],
        ),
        "planner/answer.setup_card.clash.json": SetupCardReply(
            name="Closed ticket summary",
            rows=CLASH_ROWS,
            similar=None,
            parts=[
                crossed("Monday and Friday", "one_day", "Monday", "Friday"),
                does("sum up the closed tickets in MOCK"),
            ],
        ),
        "planner/answer.part.json": PartReply(
            name="Weekly summary, to email",
            rows=ROWS,
            cant=[EMAIL],
            similar=None,
            parts=[
                does("Every Friday"),
                does("sum up the tickets we closed this week"),
                crossed(EMAIL.text, "cant_do", note=EMAIL.note),
            ],
        ),
        "planner/answer.cant.json": CantReply(
            cant=[EMAIL],
            alternative=SETUP_CARD.model_copy(update={"parts": []}),
            parts=[
                does("Every Friday"),
                does("sum up the tickets we closed this week"),
                crossed(EMAIL.text, "cant_do", note=EMAIL.note),
            ],
        ),
        "planner/answer.watchlist.json": WatchlistReply(
            word="releases",
            software="LangGraph",
            already_listed=ListedSoftware(software_id="sw_01JB8", name="LangGraph"),
            also=None,
        ),
        "planner/answer.watchlist.also.json": WatchlistReply(
            word="releases",
            software="Kubernetes",
            already_listed=None,
            also=SETUP_CARD.model_copy(update={"parts": []}),
        ),
        "planner/answer.watchlist.own_time.json": WatchlistReply(
            word="watch",
            software="Grafana",
            already_listed=None,
            also=None,
            parts=[does("watch Grafana"), crossed("every day at 8am", "own_time")],
        ),
        "planner/answer.which_software.json": WhichSoftwareReply(word="version"),
        "planner/answer.refused.json": RefusedReply(
            reason="skip_approval",
            said="without waiting for approval",
            rest="Create the ticket",
        ),
        "planner/answer.abilities.json": AbilitiesReply(),
        "planner/answer.ideas.json": IdeasReply(),
        "planner/answer.check_workflows.json": CheckWorkflowsReply(use_case_id=None),
        "planner/answer.check_workflows.leftover.json": CheckWorkflowsReply(
            use_case_id=None,
            parts=[
                does("How are my workflows doing"),
                crossed("every Friday sum up the closed tickets", "ask_on_its_own"),
            ],
        ),
        "planner/answer.why_stopped.json": WhyStoppedReply(use_case_id="uc_01JB8"),
        "planner/answer.needs_me.json": NeedsMeReply(),
        "planner/answer.needs_me.operators.json": NeedsMeReply(
            parts=[
                does("What is waiting for my yes"),
                crossed("pause the morning new-ticket check", "operators"),
            ]
        ),
        "planner/answer.operators.json": OperatorsReply(
            parts=[crossed("Pause the weekly closed-ticket summary", "operators")]
        ),
        "planner/answer.decided.json": DecidedReply(
            only=None, parts=[does("What did I decide before")]
        ),
        "planner/answer.decided.declines.json": DecidedReply(
            only="decline", parts=[does("did I decline anything")]
        ),
        "planner/answer.decide.json": DecideReply(parts=[does("Approve the upgrade tickets")]),
        "planner/answer.decide.question.json": DecideReply(
            parts=[
                does("Approve the upgrade"),
                crossed("is LangGraph up to date", "ask_on_its_own"),
            ]
        ),
        "planner/answer.question.json": QuestionReply(
            text="LangGraph is behind. You run 1.2.14 and the newest is 1.2.16.",
            looked_at=["watchlist"],
            about_software=["LangGraph"],
        ),
        "planner/answer.edit.json": EDIT,
        "planner/answer.edit.unclear.json": EditReply(
            use_case_id="uc_01JB8",
            name="Morning new-ticket check",
            watchlist=False,
            missing=None,
            software=None,
            choices=[],
            before=EditBefore(day="weekdays", at="08:00"),
            after=EditAfter(day="weekdays", at=None),
            hour=None,
            cant=None,
            holds_save=False,
            parts=[crossed("in the afternoon", "not_followed")],
        ),
        "planner/answer.edit.missing.json": EditReply(
            use_case_id=None,
            name=None,
            watchlist=False,
            missing="React check",
            software="React",
            choices=[],
            before=None,
            after=None,
            hour=None,
            cant=None,
            holds_save=False,
        ),
        "planner/answer.edit.cant.json": EditReply(
            use_case_id="uc_01JB8",
            name="Morning new-ticket check",
            watchlist=False,
            missing=None,
            software=None,
            choices=[],
            before=EditBefore(day="weekdays", at="08:00"),
            after=None,
            hour=None,
            cant="only_schedule",
            holds_save=False,
            parts=[
                crossed("What needs my attention", "ask_on_its_own"),
                crossed("Pause the morning check", "only_schedule"),
            ],
        ),
        "planner/answer.edit.hour.json": EDIT.model_copy(
            update={
                "after": EditAfter(day="weekdays", at=None),
                "hour": 9,
                "parts": [does("make the morning check run at 9")],
            }
        ),
        "planner/answer.edit.clash.json": EDIT.model_copy(
            update={
                "after": None,
                "holds_save": True,
                "parts": [
                    does("make the morning new-ticket check run on"),
                    crossed("Mondays and Thursdays", "one_day", "Mondays", "Thursdays"),
                ],
            }
        ),
        "planner/answer.edit.choices.json": EDIT.model_copy(
            update={
                "use_case_id": None,
                "name": None,
                "before": None,
                "after": None,
                "choices": [
                    EditChoice(
                        use_case_id="uc_01JB8",
                        name="Morning new-ticket check",
                        watchlist=False,
                        before=EditBefore(day="weekdays", at="08:00"),
                        after=EditAfter(day="every_day", at="08:00"),
                    ),
                    EditChoice(
                        use_case_id="uc_01JC2",
                        name="Weekly closed-ticket summary",
                        watchlist=False,
                        before=EditBefore(day="friday", at="16:00"),
                        after=EditAfter(day="every_day", at="16:00"),
                    ),
                ],
                "parts": [does("make it daily")],
            }
        ),
        "planner/answer.edit.watchlist.json": EDIT.model_copy(
            update={
                "use_case_id": "uc_01WL",
                "name": "Keep our software up to date",
                "watchlist": True,
                "before": EditBefore(day="monday", at="09:00"),
                "after": EditAfter(day="every_day", at="09:00"),
                "parts": [does("Run the software check every day instead of every Monday")],
            }
        ),
        "planner/answer.edit.how_often.json": EDIT.model_copy(
            update={
                "after": None,
                "cant": "how_often",
                "parts": [
                    does("make the morning check run every weekday"),
                    crossed("except Friday", "how_often"),
                ],
            }
        ),
        "planner/answer.offline.json": offline("no_model"),
        "planner/answer.offline.too_slow.json": offline("too_slow"),
        "planner/check-part.in.json": CheckPartIn(kind="do", text="Email the list to the team"),
        "planner/check-part.cant.json": PartCheckCantDo(
            note="I can't email the list to the team. I can only read Jira tickets, sum up what "
            "I find, check software for new releases, create a Jira ticket after a yes, and ask "
            "Approvers for a yes in Teams.",
            needs="new_system",
            system="email",
        ),
        "planner/check-part.fits.json": PartCheckFits(),
        "planner/capabilities.json": _capabilities(
            root, check("jira"), check("github"), check("teams"), check("model")
        ),
        "planner/capabilities.trouble.json": _capabilities(
            root,
            check(
                "jira",
                state="not_answering",
                problem="Jira is not answering.",
                fix="Try again in a minute.",
            ),
            check("github"),
            check("teams", state="not_checked", checked_at=None, last_ok_at=None),
            check(
                "model",
                state="not_set_up",
                problem="No AI model is connected.",
                fix="Connect one in Settings.",
                checked_at=None,
                last_ok_at=None,
            ),
        ),
    }
