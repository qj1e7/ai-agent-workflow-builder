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
    EditAfter,
    EditBefore,
    EditReply,
    IdeasReply,
    ListedSoftware,
    NeedsMeReply,
    PartCheckCantDo,
    PartCheckFits,
    PartReply,
    PlannerFront,
    QuestionReply,
    RefusedReply,
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
SETUP_CARD = SetupCardReply(name="Weekly summary of closed tickets", rows=ROWS, similar=None)
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
        "planner/answer.part.json": PartReply(
            name="Weekly summary, to email", rows=ROWS, cant=[EMAIL], similar=None
        ),
        "planner/answer.cant.json": CantReply(cant=[EMAIL], alternative=SETUP_CARD),
        "planner/answer.watchlist.json": WatchlistReply(
            word="releases",
            software="LangGraph",
            already_listed=ListedSoftware(software_id="sw_01JB8", name="LangGraph"),
            also=None,
        ),
        "planner/answer.watchlist.also.json": WatchlistReply(
            word="releases", software="Kubernetes", already_listed=None, also=SETUP_CARD
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
        "planner/answer.why_stopped.json": WhyStoppedReply(use_case_id="uc_01JB8"),
        "planner/answer.needs_me.json": NeedsMeReply(),
        "planner/answer.question.json": QuestionReply(
            text="LangGraph is behind. You run 1.2.14 and the newest is 1.2.16.",
            looked_at=["watchlist"],
            about_software=["LangGraph"],
        ),
        "planner/answer.edit.json": EditReply(
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
