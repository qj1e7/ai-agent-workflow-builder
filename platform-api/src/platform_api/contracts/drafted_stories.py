"""A drafted release check (ADR 0051, build steps 6 and 7), as the draft card and the set-up
approval page read it: drafting, with a question left, ready to send, open in n8n, waiting for a
yes as Alice and as Bob see it, and set up. Built from the same layout, settings and report code
the routes use."""

from datetime import UTC, datetime, timedelta

from platform_api.builder.drafted_settings import (
    ANY_APPROVER,
    APPROVERS,
    Source,
    next_question,
    settings_of,
)
from platform_api.builder.drafted_workflows import (
    IN_N8N_NOW,
    STILL_DRAFTING,
    DraftedApprovalView,
    DraftedInN8nView,
    DraftedSetUpView,
    DraftedWorkflowView,
    SetUpApprovalView,
    answer_first,
    report_settings,
    setting_views,
)
from platform_api.builder.explain import view_of
from platform_api.builder.layout import DraftedLayout, lay_out_drafted
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.workflow_report import Drafted, Team, workflow_report
from platform_api.orchestration import (
    DECLINE_REASONS,
    DrafterFacts,
    KnownOptions,
    WorkflowPlan,
    add_yes,
    attach_keys,
    set_up_link,
    workflow_digest,
)
from platform_api.shared import TEAM_TIME_ZONE, ApprovalId, UserId
from platform_api.wire import WireModel

ZONE = TEAM_TIME_ZONE.key
ERROR_WORKFLOW = "wfErrorReporter01"
DRAFTED_ID = "dw_01JDRAFTRELEASE"
USE_CASE_ID = "uc_01JDRAFTRELEASE"
APPROVAL_ID = "apr_01JDRAFTRELEASE"
WORDS = (
    "Draft an n8n workflow that every Monday at 9:00 checks langchain-ai/langgraph for a new "
    "release and raises a ticket in MOCK"
)
STARTED = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)
SENT = STARTED + timedelta(minutes=3)
KNOWN = KnownOptions(
    frozenset(),
    {"github_releases": frozenset({"langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK"})},
    {},
    {},
)
OPTIONS = DrafterFacts(
    jira_projects=["MOCK"],
    repositories=["langchain-ai/langgraph"],
    channels=["#support", "#eng-housekeeping"],
)
CAROL = UserId("carol")
NAMES = {CAROL: "Carol"}


def _block(name: str, node_type: str, **parameters: object) -> dict[str, object]:
    return {"name": name, "type": node_type, "version": 1, "parameters": parameters}


def _setting(id_: str, kind: str, label: str, value: str | None, block: str, path: str) -> object:
    return {
        "id": id_,
        "kind": kind,
        "label": label,
        "fills": [{"block": block, "parameter": path}],
        "value": value,
        "mark": _mark(kind, value),
    }


def _mark(kind: str, value: str | None) -> str:
    """A run time that holds only its day, as "monday", still needs its time."""
    if value is None or (kind == "run_time" and " " not in value):
        return "needed"
    return "filled"


def release_check(run_time: str | None) -> WorkflowPlan:
    return WorkflowPlan.model_validate(
        {
            "name": "Release check",
            "blocks": [
                {
                    **_block("Every Monday", "n8n-nodes-base.scheduleTrigger", rule="<<run_time>>"),
                    "version": 1.2,
                },
                _block(
                    "Read new releases",
                    "CUSTOM.wabRead",
                    source="github_releases",
                    place="<<repository>>",
                ),
                _block(
                    "Propose a ticket",
                    "CUSTOM.wabProposeChange",
                    action="jira.create_ticket",
                    place="<<jira_project>>",
                    title="={{ 'New release ' + $json.tag }}",
                    subject="={{ $json.tag }}",
                ),
                _block("Ask for a yes", "CUSTOM.wabAskForYes"),
                _block("Make the ticket", "CUSTOM.wabMakeApprovedChanges"),
            ],
            "wires": [
                {"from_block": a, "exit": e, "to_block": b, "exit_index": i, "input_index": 0}
                for a, e, b, i in (
                    ("Every Monday", "main", "Read new releases", 0),
                    ("Read new releases", "main", "Propose a ticket", 0),
                    ("Propose a ticket", "main", "Ask for a yes", 0),
                    ("Ask for a yes", "Yes", "Make the ticket", 1),
                )
            ],
            "settings": [
                _setting("run_time", "run_time", "When it runs", run_time, "Every Monday", "rule"),
                _setting(
                    "repository",
                    "repository",
                    "The repository",
                    "langchain-ai/langgraph",
                    "Read new releases",
                    "place",
                ),
                _setting(
                    "jira_project",
                    "jira_project",
                    "The Jira project",
                    "MOCK",
                    "Propose a ticket",
                    "place",
                ),
            ],
        }
    )


def _drafted(run_time: str | None) -> tuple[WorkflowPlan, dict[str, object]]:
    plan = release_check(run_time)
    laid = lay_out_drafted(
        DraftedLayout(
            USE_CASE_ID,
            f"https://portal.example/workflows/{USE_CASE_ID}",
            plan,
            ERROR_WORKFLOW,
            ZONE,
        ),
        {s.id: s.value for s in plan.settings if s.value is not None},
    )
    return plan, attach_keys(add_yes(laid, USE_CASE_ID).document, KNOWN.keys)


def _view(run_time: str | None, answered: bool = True, **changes: object) -> DraftedWorkflowView:
    """Carol's drafted release check. Her words named the run time, or only its day, and she
    chose who says yes on each run, or hasn't yet."""
    plan, document = _drafted(run_time)
    sources = {
        s.id: Source(str(s.value), "words", CAROL) for s in plan.settings if s.mark == "filled"
    }
    if answered:
        sources[APPROVERS] = Source(ANY_APPROVER, "chose", CAROL)
    settings = settings_of(plan, sources)
    report = workflow_report(
        Drafted(document, {}, report_settings(settings, CAROL, NAMES)),
        Team(ERROR_WORKFLOW, ZONE, KNOWN),
    )
    needed = report.needs_an_answer
    question = next_question(settings, OPTIONS)
    view = DraftedWorkflowView(
        drafted_id=DRAFTED_ID,
        revision=2 if answered else 1,
        card_revision=1,
        made_by="answer" if answered else "drafter",
        name=plan.name,
        state="draft",
        words=WORDS,
        said=None,
        started_at=STARTED,
        blocks=blocks_of(document),
        report=view_of(report, USE_CASE_ID, plan.name, None, False),
        needed=needed,
        flags=len(report.flags),
        settings=setting_views(settings, OPTIONS, CAROL, NAMES),
        question=None if question is None else question.id,
        in_n8n=None,
        can_edit_in_n8n=True,
        can_send=needed == 0 and not report.flags,
        why_not_send=answer_first(needed) if needed else None,
        replaced_waiting=False,
        approval=None,
        set_up=None,
    )
    return view.model_copy(update=changes)


def _approval(status: str, posted: str = "sent") -> DraftedApprovalView:
    decided = status in ("approved", "declined")
    return DraftedApprovalView.model_validate(
        {
            "approval_id": APPROVAL_ID,
            "link": set_up_link(ApprovalId(APPROVAL_ID)),
            "status": status,
            "sent_by": "Carol",
            "sent_at": SENT,
            "expires_at": SENT + timedelta(days=2),
            "decided_by": "Bob" if decided else None,
            "decided_at": SENT + timedelta(minutes=9) if decided else None,
            "reason": "Not needed" if status == "declined" else None,
            "posted": posted,
        }
    )


def drafted_fixtures() -> dict[str, WireModel]:
    ready = _view("monday 09:00")
    _, document = _drafted("monday 09:00")
    assert ready.report is not None
    waiting = ready.model_copy(
        update={
            "state": "waiting",
            "can_send": False,
            "can_edit_in_n8n": False,
            "why_not_send": "Waiting for an Approver. You can't approve your own draft.",
            "approval": _approval("waiting"),
        }
    )
    set_up = ready.model_copy(
        update={
            "state": "approved",
            "can_send": False,
            "can_edit_in_n8n": False,
            "why_not_send": "Approved.",
            "approval": _approval("approved"),
            "set_up": DraftedSetUpView(state="set_up", use_case_id=USE_CASE_ID, words=None),
        }
    )
    page = SetUpApprovalView(
        approval_id=APPROVAL_ID,
        drafted_id=DRAFTED_ID,
        revision=2,
        name="Release check",
        digest=workflow_digest(document),
        approval=_approval("waiting"),
        report=ready.report,
        you_can_decide=True,
        why_not=None,
        decline_reasons=list(DECLINE_REASONS),
        set_up=None,
    )
    return {
        "builder/drafted.drafting.json": ready.model_copy(
            update={
                "name": None,
                "state": "drafting",
                "blocks": [],
                "report": None,
                "needed": 0,
                "flags": 0,
                "settings": [],
                "question": None,
                "can_edit_in_n8n": False,
                "can_send": False,
                "why_not_send": STILL_DRAFTING,
                "revision": 1,
                "made_by": "drafter",
            }
        ),
        "builder/drafted.ready.json": ready,
        "builder/drafted.question.json": _view("monday", answered=False),
        "builder/drafted.in-n8n.json": ready.model_copy(
            update={
                "in_n8n": DraftedInN8nView(
                    by=CAROL,
                    by_name="Carol",
                    since=SENT,
                    revision=2,
                    editor_url="https://n8n.example/workflow/wfDraftEdit01",
                ),
                "can_edit_in_n8n": False,
                "can_send": False,
                "why_not_send": IN_N8N_NOW,
            }
        ),
        "builder/drafted.not-drafted.json": ready.model_copy(
            update={
                "name": None,
                "state": "not_drafted",
                "said": "I couldn't draft that.",
                "blocks": [],
                "report": None,
                "settings": [],
                "question": None,
                "can_edit_in_n8n": False,
                "can_send": False,
                "why_not_send": None,
                "revision": 1,
                "made_by": "drafter",
            }
        ),
        "builder/drafted.waiting.json": waiting,
        "builder/drafted.set-up.json": set_up,
        "builder/setup-approval.bob.json": page,
        "builder/setup-approval.carol.json": page.model_copy(
            update={
                "you_can_decide": False,
                "why_not": (
                    "You can't approve it. You asked for it, changed it, answered its questions "
                    "or sent it."
                ),
            }
        ),
    }
