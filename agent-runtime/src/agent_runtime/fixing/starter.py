"""Starting a fix (ADR 0055, PR 6): what POST /v1/fixes runs.

platform-api writes the fix's start, with who asked from their session, and mints the fix's token
only once the log took the start, with the same deadline. Then it asks for the fix here, with the
stop, the version that ran, the run's activity, the team's facts and the connected model. The
runtime runs each fix id once, in a thread of its own, and answers at once. The token goes only to
platform-api's own address, one of CALLBACK_ALLOWED_ORIGINS.

The coordinator hands work to the AI troubleshooter's model version, the Fix drafter and code's
scope check here, and to platform-api for the rest (`platform_parts.py`). Once it ends, a
hand-back the log never took, because the log stayed down through every try, is tried again
until the token's grace ends. Past the deadline the log takes only the hand-back for time, so
that is what is tried then. A fix that ends with a stored revision nobody proposed needs nothing
here: platform-api drops it."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

import httpx
from langchain_core.language_models import BaseChatModel
from pydantic import Field, StringConstraints

from agent_runtime.catalogue import Catalogue, CatalogueUnusable
from agent_runtime.contract import (
    EVENT_SUMMARY_LIMIT,
    MOST_EVENTS,
    CauseFound,
    CauseKept,
    CauseRequest,
    DrafterFacts,
    ModelAccess,
    WireModel,
)
from agent_runtime.fixing.coordinator import (
    FixOutcome,
    FixRequest,
    HandedBack,
    RefineRequest,
    coordinate,
)
from agent_runtime.fixing.drafter import ModelFixDrafter
from agent_runtime.fixing.events import FixHandBack, FixHandedBackData, FixId, FixRecorder
from agent_runtime.fixing.ledger import Unlogged
from agent_runtime.fixing.platform_parts import PlatformParts
from agent_runtime.fixing.ports import FixParts
from agent_runtime.fixing.scope import PlanScope
from agent_runtime.summary import ChatFor
from agent_runtime.troubleshooting import find_cause

log = logging.getLogger(__name__)

TOKEN_GRACE: Final = timedelta(minutes=5)
"""platform-api's FIX_TOKEN_GRACE: how long a fix's token lasts past its deadline."""
AGAIN_EVERY: Final = 15.0
"""Seconds between the tries of a hand-back the log never took."""
CAUSE_SECONDS: Final = 10.0
"""The most a cause request gives the troubleshooter's model (CauseRequest.within_seconds)."""

type RunIdText = Annotated[str, StringConstraints(pattern=r"^run_[0-9A-Za-z]{1,40}$")]
type EventSummary = Annotated[str, Field(max_length=EVENT_SUMMARY_LIMIT)]


class FixStart(WireModel):
    """A fix platform-api started on a stopped run: the log took its start, and its token is
    minted for the same deadline."""

    run_id: RunIdText
    request: FixRequest
    events: list[EventSummary] = Field(
        default_factory=list[str],
        max_length=MOST_EVENTS,
        description="The run's activity, each event's plain summary, oldest first.",
    )
    facts: DrafterFacts = Field(description="The team's facts the Fix drafter may use.")
    model: ModelAccess = Field(description="The connected model, as Settings holds it.")
    platform_url: str = Field(
        max_length=300, description="platform-api's own address, where the fix's calls go."
    )
    token: str = Field(min_length=1, max_length=200, description="The fix's own token.")


type DraftedIdText = Annotated[str, StringConstraints(pattern=r"^dw_[0-9A-Za-z]{1,40}$")]


class RefineStart(WireModel):
    """A refinement platform-api kept for a drafted workflow's Check, with its token minted for
    the same deadline (ADR 0054, section 7). There is no stopped run and no run's activity."""

    drafted_id: DraftedIdText
    request: RefineRequest
    facts: DrafterFacts = Field(description="The team's facts the Fix drafter may use.")
    model: ModelAccess = Field(description="The connected model, as Settings holds it.")
    platform_url: str = Field(
        max_length=300, description="platform-api's own address, where the refinement's calls go."
    )
    token: str = Field(min_length=1, max_length=200, description="The refinement's own token.")


class FixAccepted(WireModel):
    fix_id: FixId
    started: bool = Field(description="False when this fix was started here before.")


class ModelTroubleshooter:
    """The AI troubleshooter's model version (ADR 0032) behind the coordinator's port. It names
    the cause and the failed part from the run's facts. It can't aim at one block yet, so a look
    at one block asks the same question again."""

    def __init__(
        self,
        start: FixStart,
        chat_for: ChatFor,
        ask: Callable[[CauseRequest, ChatFor], CauseFound | CauseKept] = find_cause,
    ) -> None:
        self._start = start
        self._chat_for = chat_for
        self._ask = ask

    def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
        if seconds <= 0:
            return None
        start = self._start
        request = CauseRequest(
            model=start.model,
            stop=start.request.stop,
            events=start.events,
            blocks=[block.name for block in start.request.version.blocks],
            stopped_at=start.request.stopped_at,
            within_seconds=min(CAUSE_SECONDS, seconds),
        )
        found = self._ask(request, self._chat_for)
        return found if isinstance(found, CauseFound) else None


def _in_a_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="fix", daemon=True).start()


class Starter:
    """Runs each fix id once, in a thread of its own. The ids are kept in memory, so a restart
    forgets them, and platform-api never asks for the same fix twice but on a retried call."""

    def __init__(
        self,
        run: Callable[[FixStart], object],
        spawn: Callable[[Callable[[], None]], None] = _in_a_thread,
        refine: Callable[[RefineStart], object] | None = None,
    ) -> None:
        self._run = run
        self._refine = refine
        self._spawn = spawn
        self._started: set[str] = set()
        self._lock = threading.Lock()

    def start(self, body: FixStart | RefineStart) -> FixAccepted:
        fix_id = body.request.fix_id
        with self._lock:
            if fix_id in self._started:
                return FixAccepted(fix_id=fix_id, started=False)
            self._started.add(fix_id)
        self._spawn(lambda: self._safely(body))
        return FixAccepted(fix_id=fix_id, started=True)

    def _safely(self, body: FixStart | RefineStart) -> None:
        """Only the error's type is logged: its words can quote the run."""
        try:
            if isinstance(body, RefineStart):
                if self._refine is None:
                    raise LookupError("this runtime refines no draft")
                self._refine(body)
            else:
                self._run(body)
        except Exception as error:
            log.warning("fix %s failed: %s", body.request.fix_id, type(error).__name__)


def hand_back_again(
    outcome: FixOutcome,
    recorder: FixRecorder,
    fix_id: str,
    until: datetime,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    every: float = AGAIN_EVERY,
) -> bool:
    """True once no hand-back is left that the log never took. A hand-back the recorder gave up
    on, as the log stayed down, is tried again every `every` seconds until `until`, the end of
    the token's grace, and the log's refusal ends the tries. Past the deadline the log takes only
    the hand-back for time, so a refusal as ended turns the next try into that one."""
    if not isinstance(outcome, HandedBack) or not any(
        u.kind == "fix_handed_back" and u.why == "failed" for u in outcome.unlogged
    ):
        return True
    why: FixHandBack = outcome.why
    while now() < until:
        try:
            refused = recorder.note(FixHandedBackData(fix_id=fix_id, why=why))
        except Exception as error:
            log.warning("fix %s: the log took no hand-back yet: %s", fix_id, type(error).__name__)
            sleep(every)
            continue
        if refused == "ended" and why != "time_limit":
            why = "time_limit"
            continue
        if refused is not None:
            log.warning("fix %s: the log refused the hand-back: %s", fix_id, refused)
        return refused is None
    log.warning("fix %s: the log took no hand-back before the token's grace ended", fix_id)
    return False


def _no_model(timeout: float) -> BaseChatModel:
    raise LookupError("no model is connected")


def run_fix(
    body: FixStart,
    chats: Callable[[ModelAccess], ChatFor | None],
    drafter_model: str,
    catalogue: Callable[[], Catalogue],
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FixOutcome:
    """One fix, from platform-api's start to its hand-in or hand-back. The coordinator and the
    Fix drafter run on DRAFTER_MODEL, through the connected model's provider and key. A catalogue
    the drafter can't use hands the fix back at once, as nothing could be drafted."""
    request = body.request
    platform = PlatformParts(
        body.platform_url, body.run_id, request.fix_id, body.token, client=client, sleep=sleep
    )
    until = request.ends_by + TOKEN_GRACE
    try:
        blocks = catalogue()
    except CatalogueUnusable as unusable:
        log.error("fix %s: %s", request.fix_id, unusable)
        lost = Unlogged("fix_handed_back", None, "failed")
        outcome = HandedBack(why="gave_up", cause=None, rounds=(), unlogged=(lost,))
        hand_back_again(outcome, platform, request.fix_id, until, now, sleep)
        return outcome
    drafting = body.model.model_copy(update={"model": drafter_model})
    coordinating = chats(drafting) or _no_model
    parts = FixParts(
        troubleshooter=ModelTroubleshooter(body, chats(body.model) or _no_model),
        drafter=ModelFixDrafter(coordinating, blocks, body.facts, drafting),
        scenario_writer=platform,
        simulation=platform,
        scope=PlanScope(),
        checker=platform,
        revisions=platform,
        recorder=platform,
    )
    outcome = coordinate(request, coordinating, parts, now=now)
    hand_back_again(outcome, platform, request.fix_id, until, now, sleep)
    return outcome


class NoTroubleshooter:
    """A refinement has no stopped run, so nothing to troubleshoot. Its coordinator offers no
    find_cause, so this is never asked."""

    def find_cause(self, look_at: str | None, seconds: float) -> CauseFound | None:
        return None


def run_refinement(
    body: RefineStart,
    chats: Callable[[ModelAccess], ChatFor | None],
    drafter_model: str,
    catalogue: Callable[[], Catalogue],
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FixOutcome:
    """One refinement of a drafted workflow's Check, from platform-api's start to its hand-in or
    hand-back: the same coordinator, Fix drafter, scope check and platform parts as a fix, under
    the refinement's own routes and token."""
    request = body.request
    platform = PlatformParts.of_a_draft(
        body.platform_url, body.drafted_id, request.fix_id, body.token, client=client, sleep=sleep
    )
    until = request.ends_by + TOKEN_GRACE
    try:
        blocks = catalogue()
    except CatalogueUnusable as unusable:
        log.error("refinement %s: %s", request.fix_id, unusable)
        lost = Unlogged("fix_handed_back", None, "failed")
        outcome = HandedBack(why="gave_up", cause=None, rounds=(), unlogged=(lost,))
        hand_back_again(outcome, platform, request.fix_id, until, now, sleep)
        return outcome
    drafting = body.model.model_copy(update={"model": drafter_model})
    coordinating = chats(drafting) or _no_model
    parts = FixParts(
        troubleshooter=NoTroubleshooter(),
        drafter=ModelFixDrafter(coordinating, blocks, body.facts, drafting),
        scenario_writer=platform,
        simulation=platform,
        scope=PlanScope(),
        checker=platform,
        revisions=platform,
        recorder=platform,
    )
    outcome = coordinate(request, coordinating, parts, now=now)
    hand_back_again(outcome, platform, request.fix_id, until, now, sleep)
    return outcome
