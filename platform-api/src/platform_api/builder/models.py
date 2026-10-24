from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from platform_api.builder.templates import TAG_PATTERN
from platform_api.orchestration import AT_PATTERN, Day, Status
from platform_api.shared import ApprovalId, RunId, SoftwareId, UserId
from platform_api.wire import RepoName, WireModel
from platform_api.wire import RunState as RunStateName

type BlockKind = Literal["agent", "approval", "write_action"]


class BlockView(WireModel):
    key: str
    name: str
    description: str
    kind: BlockKind


class ParamSpec(WireModel):
    name: str
    description: str
    example: str


class TemplateView(WireModel):
    key: str
    name: str
    description: str
    blocks: list[BlockView]
    params: list[ParamSpec]


class TemplateList(WireModel):
    templates: list[TemplateView]


class CreateUseCase(WireModel):
    template: str
    name: str
    instruction: str
    params: dict[str, str]


class UseCaseCreated(WireModel):
    use_case_id: str
    version: int


class UseCaseView(WireModel):
    use_case_id: str
    version: int
    template: str
    name: str
    instruction: str
    params: dict[str, str]
    owner: UserId
    created_at: datetime


class UseCaseList(WireModel):
    use_cases: list[UseCaseView]


class SuggestIn(WireModel):
    text: str


class SuggestOut(WireModel):
    template: TemplateView | None
    matched_terms: list[str]


class RunStarted(WireModel):
    run_id: RunId
    state: Literal["pending"] = "pending"
    events_url: str


type SoftwareName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
type Version = Annotated[str, Field(pattern=TAG_PATTERN)]


class AddSoftware(WireModel):
    name: SoftwareName
    repo: RepoName
    our_version: Version | None = Field(
        default=None,
        description="The version the team runs now, such as 1.2.14. Leave it out to take the "
        "newest release at the first check as ours.",
    )


class SourceView(WireModel):
    kind: Literal["github"]
    ref: str
    url: str


type VersionSourceKind = Literal["given", "first_check", "ticket_done"]


class VersionSourceView(WireModel):
    kind: VersionSourceKind
    at: datetime
    ticket: str | None


class WatchedSoftwareView(WireModel):
    id: SoftwareId
    name: str
    source: SourceView
    our_version: str | None
    our_version_source: VersionSourceView | None
    newest_version: str | None
    checked_at: datetime | None
    status: Status
    problem: str | None
    open_ticket: str | None
    approval_id: ApprovalId | None
    added_by: UserId
    added_at: datetime


class LastCheckView(WireModel):
    run_id: RunId
    state: RunStateName
    started_at: datetime


type ClockTime = Annotated[str, Field(pattern=AT_PATTERN, examples=["09:00"])]


class ScheduleIn(WireModel):
    day: Day
    at: ClockTime = Field(description="Time of day in Singapore, HH:MM on a 5-minute step.")


class ScheduleView(WireModel):
    day: Day
    at: ClockTime
    time_zone: str
    owner: UserId = Field(description="The schedule owner. Only another Approver can approve.")
    owner_name: str
    saved_at: datetime
    next_at: datetime = Field(description="The next time a check starts.")


class WatchlistView(WireModel):
    use_case_id: str
    version: int
    ticket_project: str
    software: list[WatchedSoftwareView] = Field(
        description="Rows that need a person first: cannot check, behind, awaiting approval, "
        "ticket open, not checked; then up to date. Rows with one status sort by name."
    )
    last_check: LastCheckView | None
    schedule: ScheduleView | None = Field(description="Null when the schedule is turned off.")


class WatchlistOut(WireModel):
    watchlist: WatchlistView | None
