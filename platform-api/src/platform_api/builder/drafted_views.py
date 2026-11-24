"""What the draft card, its questions and the set-up approval page read of a drafted workflow
(ADR 0051): the wire models, and each setting in code's words for whoever reads it. Pure."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final, Literal

from pydantic import Field

from platform_api.builder.drafted_settings import Asking, How, SettingNow, asking, shown
from platform_api.builder.explain import Segment, WorkflowExplained, segments
from platform_api.builder.models import N8nBlockView
from platform_api.builder.simulation_views import SimulationView
from platform_api.builder.workflow_report import (
    HIDDEN,
    KEY_SHAPE,
    DraftSetting,
    Filled,
    Guessed,
    Needed,
    Words,
    quoted,
)
from platform_api.orchestration import DrafterFacts, SetUpDeclineReason
from platform_api.shared import UserId
from platform_api.wire import WireIn, WireModel

type DraftedState = Literal["drafting", "not_drafted", "draft", "waiting", "approved", "declined"]


class DraftedApprovalView(WireModel):
    approval_id: str
    link: str = Field(description="The set-up approval page, as the Teams card opens it.")
    status: Literal["waiting", "approved", "declined", "expired", "replaced"]
    sent_by: str
    sent_at: datetime
    expires_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    reason: str | None = Field(description="Why it was declined, from the short list.")
    posted: Literal["waiting", "sent", "failed"] = Field(
        description="Whether the request is in the Teams channel yet."
    )


class DraftedSetUpView(WireModel):
    state: Literal["setting_up", "set_up", "failed", "refused"] = Field(
        description="setting_up until n8n holds it. set_up once it is a Draft on Workflows. "
        "failed when n8n didn't take it, which an Operator can try again. refused when it "
        "changed since it was approved, or no longer passes the check, which only a new approval "
        "fixes."
    )
    use_case_id: str | None = Field(description="The workflow it is now. Null until set up.")
    words: str | None = Field(description="Why not, in words to show.")


class DraftChoiceView(WireModel):
    value: str = Field(description="Send it back as the answer's choice.")
    label: str


class DraftSettingView(WireModel):
    """One setting of the newest revision, with the question that fills it. Code writes every
    word, and a string from the plan, such as its label, is a quoted segment."""

    id: str
    kind: Literal[
        "run_time",
        "jira_project",
        "channel",
        "address",
        "repository",
        "confluence_page",
        "text",
        "approvers",
        "key",
    ]
    key: str = Field(description="The short words before its question, as When or Jira.")
    label: list[Segment]
    value: str | None = Field(description="As a person reads it. Null while it is needed.")
    mark: Literal["filled", "guessed", "needed"]
    said: str = Field(
        description="Where the value came from, as You chose or From Alice's words, or I guessed "
        "or Needed."
    )
    question: str = Field(description="Its question, which a guessed one's Change asks too.")
    choices: list[DraftChoiceView] = Field(description="2 to 4 from the team's own data.")
    typed: str | None = Field(
        description="The words on the button that opens a box to type an answer in. Null when "
        "typing isn't read."
    )
    waits: str | None = Field(
        description="Why it can't be answered now, as for a write key, which comes in a later "
        "step. It then has no choices."
    )


class DraftedInN8nView(WireModel):
    by: UserId
    by_name: str
    since: datetime
    revision: int = Field(description="The revision that was opened in n8n.")
    editor_url: str | None = Field(
        description="Where it is in n8n's editor, for the person who has it open. Null for "
        "anyone else, or when the editor's address isn't set."
    )


class DraftedWorkflowView(WireModel):
    drafted_id: str
    revision: int = Field(description="The newest revision.")
    card_revision: int = Field(
        description="The newest revision that started a card: the first, a change asked for in "
        "the chat, or a read-back from n8n. An answer makes a revision on the same card. A card "
        "for an older revision settles."
    )
    made_by: Literal["drafter", "answer", "n8n"] = Field(
        description="How the newest revision was made: by the drafter, by code from an answer, "
        "or read back from n8n."
    )
    name: str | None = Field(description="The plan's name. Null until the first plan.")
    state: DraftedState = Field(
        description="drafting while the drafter works; not_drafted with said; draft until it is "
        "sent; waiting for a yes; approved; declined. An approval that expired or was replaced "
        "leaves it a draft."
    )
    words: str = Field(description="The words this revision was drafted from.")
    said: str | None = Field(description="Why it wasn't drafted, in words to show.")
    started_at: datetime
    blocks: list[N8nBlockView] = Field(description="Its blocks in the order a run meets them.")
    report: WorkflowExplained | None = Field(
        description="Code's workflow report of this revision. Null while drafting or when not "
        "drafted."
    )
    needed: int = Field(description="The settings still needed, write keys included.")
    flags: int = Field(
        description="The flags the check found, leaving out what a setting still needed causes, "
        "which its question covers."
    )
    settings: list[DraftSettingView] = Field(
        description="Every setting, in the plan's order, then the write keys and the Approvers."
    )
    question: str | None = Field(
        description="The id of the one setting the card asks for now, in the ADR's order. Null "
        "when nothing can be asked now, or it isn't a draft."
    )
    notes: list[str] = Field(
        description="What came back from n8n with this revision that didn't count, such as a "
        "channel typed there that the platform can't post in, in words to show on the card."
    )
    in_n8n: DraftedInN8nView | None = Field(
        description="Who has it open in their own n8n space, without its keys. Done in n8n reads "
        "it back as a new revision."
    )
    can_edit_in_n8n: bool = Field(
        description="Whether Edit in n8n works for this person now: an Operator with n8n access, "
        "on a draft nobody has open in n8n."
    )
    can_send: bool
    why_not_send: str | None = Field(
        description="Why Turn on can't ask for the one-time check now, in words shown in its place."
    )
    replaced_waiting: bool = Field(
        description="This revision replaced a set-up approval that was still waiting."
    )
    approval: DraftedApprovalView | None = Field(
        description="This revision's set-up approval, once sent."
    )
    set_up: DraftedSetUpView | None = Field(description="Its set-up, once approved.")
    simulation: SimulationView | None = Field(
        description="The newest revision tried on practice systems. Null while drafting or when "
        "not drafted. Waiting while a setting is still needed."
    )


class FixChangeView(WireModel):
    """One value the fix changed, from the stopped version to the fixed one, as data."""

    block: str
    parameter: str = Field(description="The parameter's path in the block, as a.b.")
    before: str | None
    after: str | None


class FixScenarioView(WireModel):
    """One scenario's grade on practice systems, as platform-api's own simulation gave it."""

    name: str
    kind: str | None
    verdict: Literal["passed", "failed", "not_tried"]
    step: str | None = Field(description="The block where it stopped, if one did.")
    why: str | None = Field(description="How a failed run ended, as code read it.")


type FixCheck = Literal[
    "inside_the_failed_part", "every_scenario_passed", "safety_check", "settings_unchanged"
]


class FixCheckView(WireModel):
    check: FixCheck
    passed: bool
    words: str = Field(description="What code checked, in code's own words.")


class FixEvidenceView(WireModel):
    """What the approval page shows of a fix (ADR 0055, section 7), all of it code's: the cause
    as code confirmed it, the change, each scenario's grade and code's checks. The report's
    reworded text is the AI's help for the reader, never the check."""

    fix_id: str
    run_id: str
    use_case_id: str
    asked_by: str = Field(description="The name of the person who asked for the fix.")
    made_by: Literal["fix_drafter", "person"] = Field(
        description="Who made the change: the Fix drafter, or a person who answered the question "
        "a hand-back asked."
    )
    answered_by: str | None = Field(description="The person who answered, by name.")
    cause: str | None = Field(description="The cause, in code's own words.")
    failed_part: list[str]
    changes: list[FixChangeView]
    read_list: str | None = Field(
        description="The repositories the fixed version reads that join the team's read list "
        "once it is turned back on, in code's words. Null when it adds none."
    )
    scenarios: list[FixScenarioView]
    checks: list[FixCheckView]


class SetUpApprovalView(WireModel):
    """A set-up approval as the approval page shows it: code's report of the exact revision the
    digest binds, and whether this person may decide it now, by the run gate's own rule."""

    approval_id: str
    drafted_id: str
    revision: int
    name: str
    digest: str = Field(description="Send it back with the decision.")
    approval: DraftedApprovalView
    report: WorkflowExplained
    you_can_decide: bool
    why_not: str | None = Field(description="Why this person can't decide it now.")
    decline_reasons: list[str]
    set_up: DraftedSetUpView | None
    fix: FixEvidenceView | None = Field(
        default=None,
        description="For a fix to a workflow (ADR 0055): its cause, change, scenarios and code's "
        "checks. Null for a drafted workflow's set-up.",
    )


class DraftWorkflowIn(WireIn):
    words: str = Field(min_length=1, max_length=2000)


class DraftChangeIn(WireIn):
    words: str = Field(min_length=1, max_length=2000)
    revision: int = Field(ge=1, description="The revision the person asks to change.")


class DraftSendIn(WireIn):
    revision: int = Field(ge=1)


class DraftAnswerIn(WireIn):
    revision: int = Field(ge=1, description="The revision the question was asked on.")
    setting: str = Field(min_length=1, max_length=120)
    choice: str | None = Field(
        default=None, max_length=200, description="One of the question's choices, as its value."
    )
    typed: str | None = Field(
        default=None, min_length=1, max_length=200, description="What the person typed."
    )


class DraftInN8nIn(WireIn):
    revision: int = Field(ge=1)


class DraftSimulationIn(WireIn):
    revision: int = Field(ge=1, description="The newest revision, to try on practice systems.")


class SetUpDecisionIn(WireIn):
    verdict: Literal["approve", "decline"]
    digest: str
    reason: SetUpDeclineReason | None = Field(
        default=None, description="Needed to decline, from the short list. None to approve."
    )


def report_settings(
    settings: Sequence[SettingNow], viewer: UserId | None, names: Mapping[UserId, str]
) -> tuple[DraftSetting, ...]:
    """Each setting as the workflow report shows it, with where its value came from in words
    for this viewer."""
    return tuple(_draft_setting(s, _said(s, viewer, names)) for s in settings)


def setting_views(
    settings: Sequence[SettingNow],
    options: DrafterFacts,
    viewer: UserId | None,
    names: Mapping[UserId, str],
    listed_at: str | None = None,
) -> list[DraftSettingView]:
    """Each setting as the draft card shows it, with its question and choices. `listed_at` is when
    Slack last listed its channels, once it stopped answering."""
    return [
        _setting_view(s, asking(s, options, listed_at), _said(s, viewer, names)) for s in settings
    ]


def _setting_view(setting: SettingNow, question: Asking, said: str) -> DraftSettingView:
    label = _label(setting)
    return DraftSettingView(
        id=setting.id,
        kind=setting.kind,
        key=question.key,
        label=segments((quoted(label),) if isinstance(label, str) else label),
        value=None if (value := shown(setting)) is None else KEY_SHAPE.sub(HIDDEN, value),
        mark=setting.mark,
        said=said,
        question=question.words,
        choices=[DraftChoiceView(value=c.value, label=c.label) for c in question.choices],
        typed=question.typed,
        waits=question.waits,
    )


SAID_BY: Final[Mapping[How, tuple[str, str]]] = {
    "words": ("From your words", "From {name}'s words"),
    "chose": ("You chose", "{name} chose"),
    "typed": ("You typed it", "{name} typed it"),
    "n8n": ("You typed it in n8n", "{name} typed it in n8n"),
}
GUESSED: Final = "I guessed"
NEEDED: Final = "Needed"


def _said(setting: SettingNow, viewer: UserId | None, names: Mapping[UserId, str]) -> str:
    """Where a value came from, in words for whoever reads it."""
    if setting.mark == "guessed":
        return GUESSED
    if setting.mark == "needed" or setting.source is None:
        return NEEDED
    yours, theirs = SAID_BY[setting.source.how]
    by = setting.source.by
    if by is None:
        return (
            "From the words it was asked in"
            if setting.source.how == "words"
            else theirs.format(name="Someone")
        )
    return yours if by == viewer else theirs.format(name=names.get(by, "Someone"))


def _label(setting: SettingNow) -> str | Words:
    """The plan's label, shown in quotes, or code's own words for a setting the builder adds."""
    if setting.kind == "key":
        return (f"{setting.label} ", quoted(setting.block or ""))
    if setting.kind == "approvers":
        return (setting.label,)
    return setting.label


def _value_words(setting: SettingNow) -> str | Words:
    """The value as the report shows it: a run time in code's words, else as written."""
    value = shown(setting) or ""
    return (value,) if setting.kind in ("run_time", "approvers") else value


def _draft_setting(setting: SettingNow, said: str) -> DraftSetting:
    if setting.mark == "needed" or setting.value is None:
        given: Filled | Guessed | Needed = Needed()
    elif setting.mark == "guessed":
        given = Guessed(_value_words(setting))
    else:
        given = Filled(_value_words(setting))
    return DraftSetting(_label(setting), given, said)
