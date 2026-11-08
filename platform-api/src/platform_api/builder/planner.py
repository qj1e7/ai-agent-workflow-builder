"""The Planner's front door on Home (ADR 0037): one answer to what a person types or taps.

The runtime reads a typed request and the builder adds what only it knows: a workflow it
already has under that name, software already on the list, and which workflow a name means. An
intent chip never asks the model. When no model is connected, or it is slow or gives an answer
that cannot be used, the person gets the plain offline answer with the starter workflows, never
a guess. Nothing here writes.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import Field, StringConstraints, model_validator

from platform_api.builder.models import (
    CardList,
    StarterView,
    UnderstoodRowView,
    UseCaseList,
    UseCaseView,
    WatchlistView,
)
from platform_api.builder.planning import FALLBACK_WORDS, STARTERS, FallbackWhy
from platform_api.orchestration import (
    AbilitiesAnswer,
    Answered,
    AnswerResult,
    CantAnswer,
    CantRow,
    CapabilityList,
    CapabilitySpec,
    CheckPartResult,
    CheckWorkflowsAnswer,
    ConnectionCheck,
    ConnectionId,
    ExampleSpec,
    FactSection,
    ModelProblem,
    NeedsMeAnswer,
    NoModel,
    PartAnswer,
    PartCantDo,
    PlannerAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    RefusedAnswer,
    RowKind,
    RuntimeDown,
    SetupCardAnswer,
    UnderstoodRow,
    WatchlistAnswer,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
)
from platform_api.shared import Principal
from platform_api.wire import WireIn, WireModel

log = logging.getLogger(__name__)

ANSWER_LIMIT_SECONDS: Final = 20.0
"""The model gets 8 seconds for each of its two calls in the runtime: the reading, and the
answer to a question about the person's data (ADR 0042). This is the platform's own limit around
the whole call, so a runtime that hangs still gives the person an answer."""

type CapabilityState = Literal["ready", "needs_setup", "down", "planned", "unsupported"]
type Intent = Literal["check_workflows", "needs_me", "abilities", "setup_ideas", "why_stopped"]


class PreviousIn(WireIn):
    request: Annotated[str, StringConstraints(max_length=2000)]
    software: Annotated[str, StringConstraints(max_length=80)] | None = Field(
        default=None, description="The software the Planner named in its answer to it."
    )
    answer: Annotated[str, StringConstraints(max_length=600)] | None = Field(
        default=None, description="The text of the Planner's answer to it, when it had one."
    )


class AnswerIn(WireIn):
    text: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = Field(
        default=None,
        description="What the person typed. The model reads it. Send this or an intent.",
    )
    intent: Intent | None = Field(
        default=None,
        description="A chip the person tapped. It never asks the model. Send this or text.",
    )
    use_case_id: str | None = Field(
        default=None,
        max_length=100,
        description="With the why_stopped intent, the workflow the person asks about.",
    )
    previous: PreviousIn | None = Field(
        default=None,
        description="With text: the turn before it. Context for the question lane only: the "
        "Planner never builds request text from it.",
    )

    @model_validator(mode="after")
    def _one_of_text_or_intent(self) -> Self:
        if (self.text is None) == (self.intent is None):
            raise ValueError("Send the text the person typed, or the intent they tapped, not both")
        if self.previous is not None and self.text is None:
            raise ValueError("The previous turn goes with typed text only")
        return self


class CheckPartIn(WireIn):
    kind: RowKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CantRowView(WireModel):
    kind: RowKind
    text: str
    note: str = Field(description="Why the platform can't do it, in plain words.")
    needs: Literal["new_tool", "new_system"] = Field(
        description="new_tool: the platform already reaches the system, so the team decides on a "
        "tool. new_system: it names a system or source the platform doesn't reach, or none."
    )
    system: str | None


class SimilarWorkflow(WireModel):
    use_case_id: str
    name: str


class ListedSoftware(WireModel):
    software_id: str
    name: str


class SetupCardReply(WireModel):
    answer: Literal["setup_card"] = "setup_card"
    name: str
    rows: list[UnderstoodRowView]
    similar: SimilarWorkflow | None = Field(
        description="A workflow of the team's with the same name, when there is one."
    )


class PartReply(WireModel):
    answer: Literal["part"] = "part"
    name: str
    rows: list[UnderstoodRowView]
    cant: list[CantRowView]
    similar: SimilarWorkflow | None


class WatchlistReply(WireModel):
    answer: Literal["watchlist"] = "watchlist"
    word: str
    software: str | None
    already_listed: ListedSoftware | None = Field(
        description="The software on the Software watchlist that has this name, when it is "
        "already there."
    )
    also: SetupCardReply | PartReply | CantReply | None = Field(
        description="The rest of a request that also asks for a workflow."
    )


class CantReply(WireModel):
    answer: Literal["cant"] = "cant"
    cant: list[CantRowView]
    alternative: Annotated[SetupCardReply | WatchlistReply, Field(discriminator="answer")] | None


class WhichSoftwareReply(WireModel):
    answer: Literal["which_software"] = "which_software"
    word: str


class RefusedReply(WireModel):
    answer: Literal["refused"] = "refused"
    reason: Literal["skip_approval"]
    said: str
    rest: str


class AbilitiesReply(WireModel):
    answer: Literal["abilities"] = "abilities"


class IdeasReply(WireModel):
    answer: Literal["ideas"] = "ideas"


class CheckWorkflowsReply(WireModel):
    answer: Literal["check_workflows"] = "check_workflows"
    use_case_id: str | None = Field(
        description="The workflow the request names, when one name matches. Null for all."
    )


class WhyStoppedReply(WireModel):
    answer: Literal["why_stopped"] = "why_stopped"
    use_case_id: str | None


class NeedsMeReply(WireModel):
    answer: Literal["needs_me"] = "needs_me"


class QuestionReply(WireModel):
    answer: Literal["question"] = "question"
    text: str = Field(
        description="The Planner's answer to a question about the person's own data, in its own "
        "words, from the facts read when the question arrived (ADR 0042)."
    )
    looked_at: list[FactSection] = Field(
        description="The sections the answer used: watchlist (the Software page), workflows "
        "(the Workflows page) and needs_you (Home). Empty for the fixed fallback."
    )
    about_software: list[str] = Field(
        default_factory=list,
        description="The watched software the answer is about, named as the Software page names "
        "them. The Portal offers its Software-page actions for these and no others.",
    )


class OfflineReply(WireModel):
    answer: Literal["offline"] = "offline"
    why: FallbackWhy = Field(
        description="no_model: none is connected. too_slow: it took too long. trouble: it "
        "failed or gave an answer the platform could not use."
    )
    message: str
    starters: list[StarterView]


WatchlistReply.model_rebuild()

type PlannerReply = Annotated[
    SetupCardReply
    | PartReply
    | CantReply
    | WatchlistReply
    | WhichSoftwareReply
    | RefusedReply
    | AbilitiesReply
    | IdeasReply
    | CheckWorkflowsReply
    | WhyStoppedReply
    | NeedsMeReply
    | QuestionReply
    | OfflineReply,
    Field(discriminator="answer"),
]


class PartCheckFits(WireModel):
    state: Literal["fits"] = "fits"


class PartCheckCantDo(WireModel):
    state: Literal["cant_do"] = "cant_do"
    note: str
    needs: Literal["new_tool", "new_system"]
    system: str | None


type PartChecked = Annotated[PartCheckFits | PartCheckCantDo, Field(discriminator="state")]


class CapabilityView(WireModel):
    id: str
    plain: str
    kind: Literal["read", "write", "notify", "none"]
    system: str | None
    state: CapabilityState = Field(
        description="ready: it works now. needs_setup: a connection it uses is not set up. "
        "down: a connection it uses is not working right now. planned: not built yet. "
        "unsupported: the team has decided against it."
    )
    cant: str | None = Field(description="What the platform can't do, when it is not ready.")
    why: str | None = Field(
        description="Why it is not ready: the registry's words for a planned or unsupported "
        "entry, the connection's problem for needs_setup and down. Null when ready."
    )
    fix: str | None = Field(
        description="What to do about a connection that needs setup or is down."
    )
    connection: ConnectionId | None
    last_ok_at: datetime | None = Field(description="When its connection last worked.")
    needs_model: bool
    platform: bool = Field(description="A duty of the platform itself, with no tool.")
    focus: bool = Field(description="True for what software versioning uses.")
    tools: list[str]
    agents: list[str] = Field(description="The ids of the agent cards that use its tools.")


class ExampleView(WireModel):
    text: str
    kind: Literal["automate", "monitor", "learn"]
    needs: list[str]


class CapabilitiesView(WireModel):
    capabilities: list[CapabilityView]
    examples: list[ExampleView]


class Answering(Protocol):
    async def answer(
        self, task: str, facts: PlannerFacts | None = None, previous: PreviousTurn | None = None
    ) -> AnswerResult | NoModel | RuntimeDown: ...

    async def check_part(self, kind: RowKind, text: str) -> CheckPartResult | RuntimeDown: ...


class FactsReading(Protocol):
    async def read(self, viewer: Principal) -> PlannerFacts: ...


class Registry(Protocol):
    async def get(self) -> CapabilityList | RuntimeDown: ...


class ConnectionStates(Protocol):
    async def view(self) -> list[ConnectionCheck]: ...


class Workflows(Protocol):
    async def list_use_cases(self) -> UseCaseList: ...

    async def get_use_case(self, use_case_id: str) -> UseCaseView | None: ...

    async def list_cards(self) -> CardList: ...


class Listed(Protocol):
    async def view(self) -> WatchlistView | None: ...


class NoSuchWorkflow:
    """The workflow an intent names does not exist."""


class RegistryUnavailable:
    """The runtime did not answer and no earlier registry is kept."""


def offline(why: FallbackWhy) -> OfflineReply:
    return OfflineReply(why=why, message=FALLBACK_WORDS[why], starters=list(STARTERS))


def _cant_row(row: CantRow) -> CantRowView:
    return CantRowView(
        kind=row.kind, text=row.text, note=row.note, needs=row.needs, system=row.system
    )


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def _rows(rows: Sequence[UnderstoodRow]) -> list[UnderstoodRowView]:
    return [UnderstoodRowView(kind=r.kind, text=r.text, state=r.state, note=r.note) for r in rows]


class PlannerFront:
    def __init__(
        self,
        answers: Answering,
        workflows: Workflows,
        watchlist: Listed,
        registry: Registry,
        connections: ConnectionStates,
        facts: FactsReading,
    ) -> None:
        self._facts = facts
        self._answers = answers
        self._workflows = workflows
        self._watchlist = watchlist
        self._registry = registry
        self._connections = connections

    async def answer(self, body: AnswerIn, viewer: Principal) -> PlannerReply | NoSuchWorkflow:
        if body.text is not None:
            return await self._typed(body.text, viewer, body.previous)
        assert body.intent is not None
        return await self._intent(body.intent, body.use_case_id)

    async def _intent(
        self, intent: Intent, use_case_id: str | None
    ) -> PlannerReply | NoSuchWorkflow:
        match intent:
            case "abilities":
                return AbilitiesReply()
            case "setup_ideas":
                return IdeasReply()
            case "needs_me":
                return NeedsMeReply()
            case "check_workflows":
                return CheckWorkflowsReply(use_case_id=None)
            case "why_stopped":
                if (
                    use_case_id is not None
                    and await self._workflows.get_use_case(use_case_id) is None
                ):
                    return NoSuchWorkflow()
                return WhyStoppedReply(use_case_id=use_case_id)

    async def _typed(
        self, text: str, viewer: Principal, previous: PreviousIn | None = None
    ) -> PlannerReply:
        earlier = None if previous is None else PreviousTurn(**previous.model_dump())
        try:
            async with asyncio.timeout(ANSWER_LIMIT_SECONDS):
                result = await self._answers.answer(text, await self._facts.read(viewer), earlier)
        except TimeoutError:
            log.warning("The Planner's answer took longer than %g seconds", ANSWER_LIMIT_SECONDS)
            return offline("too_slow")
        match result:
            case NoModel():
                return offline("no_model")
            case RuntimeDown(detail=detail):
                log.warning("The Planner's answer fell back to the starters: %s", detail)
                return offline("trouble")
            case ModelProblem(reason=reason):
                log.warning("The Planner's answer fell back to the starters: %s", reason)
                return offline("too_slow" if reason == "too_slow" else "trouble")
            case Answered(answer=answer):
                return await self._finish(answer)

    async def _finish(self, answer: PlannerAnswer) -> PlannerReply:
        match answer:
            case SetupCardAnswer(name=name, rows=rows):
                return SetupCardReply(
                    name=name, rows=_rows(rows), similar=await self._similar(name)
                )
            case PartAnswer(name=name, rows=rows, cant=cant):
                return PartReply(
                    name=name,
                    rows=_rows(rows),
                    cant=[_cant_row(c) for c in cant],
                    similar=await self._similar(name),
                )
            case CantAnswer(cant=cant, alternative=alternative):
                return CantReply(
                    cant=[_cant_row(c) for c in cant],
                    alternative=await self._alternative(alternative),
                )
            case WatchlistAnswer() as watch:
                return await self._watch(watch)
            case WhichSoftwareAnswer(word=word):
                return WhichSoftwareReply(word=word)
            case RefusedAnswer(reason=reason, said=said, rest=rest):
                return RefusedReply(reason=reason, said=said, rest=rest)
            case CheckWorkflowsAnswer(workflow_words=words):
                return CheckWorkflowsReply(use_case_id=await self._which(words))
            case WhyStoppedAnswer(workflow_words=words):
                return WhyStoppedReply(use_case_id=await self._which(words))
            case NeedsMeAnswer():
                return NeedsMeReply()
            case AbilitiesAnswer():
                return AbilitiesReply()
            case QuestionAnswer(text=text, looked_at=looked_at, about_software=software):
                return QuestionReply(text=text, looked_at=looked_at, about_software=software)

    async def _alternative(
        self, alternative: SetupCardAnswer | WatchlistAnswer | None
    ) -> SetupCardReply | WatchlistReply | None:
        match alternative:
            case None:
                return None
            case SetupCardAnswer(name=name, rows=rows):
                return SetupCardReply(
                    name=name, rows=_rows(rows), similar=await self._similar(name)
                )
            case WatchlistAnswer() as watch:
                return await self._watch(watch)

    async def _watch(self, watch: WatchlistAnswer) -> WatchlistReply:
        also = None
        if watch.also is not None:
            rest = await self._finish(watch.also)
            if isinstance(rest, SetupCardReply | PartReply | CantReply):
                also = rest
        return WatchlistReply(
            word=watch.word,
            software=watch.software,
            already_listed=await self._listed(watch.software),
            also=also,
        )

    async def _listed(self, software: str | None) -> ListedSoftware | None:
        if software is None:
            return None
        view = await self._watchlist.view()
        if view is None:
            return None
        wanted = _norm(software)
        return next(
            (
                ListedSoftware(software_id=s.id, name=s.name)
                for s in view.software
                if _norm(s.name) == wanted
            ),
            None,
        )

    async def _use_cases(self) -> list[UseCaseView]:
        return (await self._workflows.list_use_cases()).use_cases

    async def _similar(self, name: str) -> SimilarWorkflow | None:
        wanted = _norm(name)
        return next(
            (
                SimilarWorkflow(use_case_id=u.use_case_id, name=u.name)
                for u in await self._use_cases()
                if u.template != "software_watchlist" and _norm(u.name) == wanted
            ),
            None,
        )

    async def _which(self, words: str | None) -> str | None:
        """The workflow a name means: the one whose name is the words, else the only one whose
        name holds them or is held by them. Null when none or several match."""
        if words is None or not words.strip():
            return None
        wanted = _norm(words)
        cases = await self._use_cases()
        exact = [u for u in cases if _norm(u.name) == wanted]
        if len(exact) == 1:
            return exact[0].use_case_id
        near = [u for u in cases if wanted in _norm(u.name) or _norm(u.name) in wanted]
        return near[0].use_case_id if len(near) == 1 else None

    async def check_part(self, body: CheckPartIn) -> PartChecked | RegistryUnavailable:
        checked = await self._answers.check_part(body.kind, body.text)
        match checked:
            case RuntimeDown():
                return RegistryUnavailable()
            case PartCantDo(note=note, needs=needs, system=system):
                return PartCheckCantDo(note=note, needs=needs, system=system)
            case _:
                return PartCheckFits()

    async def capabilities(self) -> CapabilitiesView | RegistryUnavailable:
        registry = await self._registry.get()
        if isinstance(registry, RuntimeDown):
            return RegistryUnavailable()
        checks: dict[ConnectionId, ConnectionCheck] = {
            c.id: c for c in await self._connections.view()
        }
        uses = await self._cards_by_tool()
        return CapabilitiesView(
            capabilities=[_capability(spec, checks, uses) for spec in registry.capabilities],
            examples=[_example(e) for e in registry.examples],
        )

    async def _cards_by_tool(self) -> dict[str, list[str]]:
        uses: dict[str, list[str]] = {}
        for card in (await self._workflows.list_cards()).cards:
            for tool in card.tools:
                if card.card_id not in uses.setdefault(tool, []):
                    uses[tool].append(card.card_id)
        return uses


def _example(example: ExampleSpec) -> ExampleView:
    return ExampleView(text=example.text, kind=example.kind, needs=list(example.needs))


def _capability(
    spec: CapabilitySpec,
    checks: dict[ConnectionId, ConnectionCheck],
    uses: dict[str, list[str]],
) -> CapabilityView:
    own = checks.get(spec.connection) if spec.connection else None
    agents = list(dict.fromkeys(card for tool in spec.tools for card in uses.get(tool, [])))
    state: CapabilityState = spec.state
    why = spec.why
    fix = None
    if spec.state == "ready":
        needed = [c for c in (own, checks.get("model") if spec.needs_model else None) if c]
        broken = next((c for c in needed if c.state not in ("working", "not_checked")), None)
        if broken is not None:
            state = "needs_setup" if broken.state == "not_set_up" else "down"
            why, fix = broken.problem, broken.fix
    return CapabilityView(
        id=spec.id,
        plain=spec.plain,
        kind=spec.kind,
        system=spec.system,
        state=state,
        cant=spec.cant,
        why=why,
        fix=fix,
        connection=spec.connection,
        last_ok_at=own.last_ok_at if own else None,
        needs_model=spec.needs_model,
        platform=spec.platform,
        focus=spec.focus,
        tools=list(spec.tools),
        agents=agents,
    )
