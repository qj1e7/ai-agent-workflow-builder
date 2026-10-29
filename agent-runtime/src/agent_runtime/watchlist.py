# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_runtime.contract import (
    CarryForward,
    Finding,
    FindingState,
    ProposedIntent,
    SoftwareToCheck,
    TaskError,
    TaskOutput,
    WatchlistInputs,
)
from agent_runtime.events import Draft
from agent_runtime.release_source import (
    DEFAULT_RETRY,
    ReleaseSource,
    RetryPolicy,
    candidates,
    failed,
    finished,
    plural,
    read_releases,
    started,
    tag_list,
    to_room,
)
from agent_runtime.summary import Checked, Summarizer
from agent_runtime.tags import family_of, highest, newer_than

NO_PLAIN_VERSION = "No release has a plain version number."

# What reading one source gave: the releases that match the tag pattern, or why it failed.
type Read = list[str] | TaskError


def decide(item: SoftwareToCheck, read: Read) -> Finding:
    """One finding for one software, from what we run, what is held and what the source has."""
    if isinstance(read, TaskError):
        return _finding(item, "cant_check", None, [], f"{read.message}.")
    newest = highest(read)
    our = item.our_version
    if newest is None:
        return _finding(item, "cant_check", None, [], NO_PLAIN_VERSION)
    if our is None:
        return _finding(
            item,
            "starting_point",
            newest,
            [],
            f"No version was given, so {newest} is the starting point.",
        )
    if family_of(our) is None:
        return _finding(
            item, "cant_check", newest, [], f"Our version {our} is not a version number."
        )
    newer = newer_than(our, read)
    if not newer:
        return _finding(item, "up_to_date", newest, [], f"Nothing is newer than {our}.")
    count = plural(len(newer), "release")
    if item.open_ticket:
        held = f"ticket {item.open_ticket} is still open"
    elif item.awaiting_approval:
        held = "a ticket is waiting for approval"
    else:
        return _finding(item, "behind", newer[0], newer, f"{count} newer than {our}.")
    return _finding(item, "already_raised", newer[0], newer, f"{newer[0]} is out, but {held}.")


def _finding(
    item: SoftwareToCheck,
    state: FindingState,
    newest: str | None,
    new_versions: list[str],
    detail: str,
) -> Finding:
    return Finding(
        software_id=item.id, state=state, newest=newest, new_versions=new_versions, detail=detail
    )


def ticket_for(item: SoftwareToCheck, finding: Finding) -> ProposedIntent:
    assert item.our_version and finding.newest, "only a software that is behind gets a ticket"
    name, ref, our = item.name, item.source.ref, item.our_version
    count = plural(len(finding.new_versions), "new release")
    bullets = "\n".join(f"- {tag}" for tag in finding.new_versions)
    return ProposedIntent(
        kind="create_ticket",
        fields={
            "title": f"Upgrade {name} from {our} to {finding.newest}",
            "body": f"{name} has {count} on GitHub ({ref}) newer than our version {our}:\n"
            f"{bullets}\n\nProposed by the AI workflow builder.",
        },
        reason=f"{name} {finding.newest} is out, and we run {our}",
        subject=item.id,
    )


@dataclass
class WatchlistState:
    inputs: WatchlistInputs
    findings: list[Finding] = field(default_factory=list[Finding])
    read_errors: list[TaskError] = field(default_factory=list[TaskError])
    output: TaskOutput | None = None
    error: TaskError | None = None


type Update = dict[str, object]


class WatchlistChecker:
    def __init__(
        self,
        source: ReleaseSource,
        summarizer: Summarizer,
        sleep: Callable[[float], None],
        retry: RetryPolicy = DEFAULT_RETRY,
    ) -> None:
        self._source = source
        self._summarizer = summarizer
        self._sleep = sleep
        self._retry = retry
        self._graph = self._build()

    def check(
        self, inputs: WatchlistInputs, emit: Callable[[Draft], None]
    ) -> TaskOutput | TaskError:
        final: dict[str, object] = {}
        for mode, chunk in self._graph.stream(
            WatchlistState(inputs=inputs), stream_mode=["custom", "values"]
        ):
            if mode == "custom" and isinstance(chunk, Draft):
                emit(chunk)
            elif mode == "values" and isinstance(chunk, dict):
                final = cast(dict[str, object], chunk)
        outcome = final.get("error") or final.get("output")
        assert isinstance(outcome, TaskError | TaskOutput)
        return outcome

    def _build(self):
        graph = StateGraph(WatchlistState)
        graph.add_node("read_sources", self._read_sources)
        graph.add_node("report", self._report)
        graph.add_edge(START, "read_sources")
        graph.add_edge("read_sources", "report")
        graph.add_edge("report", END)
        return graph.compile()

    def _read_sources(self, state: WatchlistState) -> Update:
        write = get_stream_writer()
        inputs = state.inputs
        findings: list[Finding] = []
        read_errors: list[TaskError] = []
        for item in inputs.software:
            write(started("read_source", f"reading the releases of {item.name}."))
            releases = read_releases(self._source, item.source.ref, self._retry, self._sleep, write)
            if isinstance(releases, TaskError):
                read: Read = releases
                read_errors.append(releases)
            else:
                read = candidates(releases, inputs.tag_pattern)
            finding = decide(item, read)
            findings.append(finding)
            write(_read_finished(item, finding))
            if finding.state == "cant_check":
                write(_cannot_check(item, finding, isinstance(read, TaskError)))
        return {"findings": findings, "read_errors": read_errors}

    def _report(self, state: WatchlistState) -> Update:
        write = get_stream_writer()
        items = state.inputs.software
        findings = state.findings
        if all(f.state == "cant_check" for f in findings):
            error = _nothing_readable(state.read_errors, len(findings))
            write(failed(None, error, "none of the watched software could be checked."))
            return {"error": error}
        pairs = list(zip(items, findings, strict=True))
        behind = [(item, f) for item, f in pairs if f.state == "behind"]
        tickets = [ticket_for(item, f) for item, f in behind]
        write(_report_total(len(items), [item.name for item, _ in behind]))
        checked = [Checked(item.name, f) for item, f in pairs]
        output = TaskOutput(
            summary=self._summarizer.summarise_check(checked),
            new_tags=[],
            proposed=tickets,
            carry_forward=CarryForward(),
            findings=findings,
        )
        return {"output": output}


def _nothing_readable(read_errors: list[TaskError], total: int) -> TaskError:
    retryable = any(e.retryable for e in read_errors)
    cause = read_errors[0].message if read_errors else NO_PLAIN_VERSION
    return TaskError(
        type="UpstreamUnavailable" if retryable else "UpstreamRejected",
        message=f"None of the {total} watched software could be checked. {cause}.",
        retryable=retryable,
    )


def _read_finished(item: SoftwareToCheck, finding: Finding) -> Draft:
    what = (
        f"could not read {item.name}."
        if finding.state == "cant_check"
        else f"read {item.name}. {finding.detail}"
    )
    result: dict[str, object] = {
        "software_id": item.id,
        "state": finding.state,
        "newest": finding.newest,
    }
    return finished("read_source", what, result)


def _cannot_check(item: SoftwareToCheck, finding: Finding, unreadable: bool) -> Draft:
    start = (
        f"I could not read {item.name}'s releases"
        if unreadable
        else f"I could not check {item.name}"
    )
    return to_room(
        f"could not check {item.name} and carried on.",
        f"{start}: {finding.detail} I will carry on with the rest.",
    )


def _report_total(total: int, behind: list[str]) -> Draft:
    if not behind:
        return to_room(
            "reported to the room that nothing needs a ticket.",
            f"I checked {total} watched software. Nothing needs a ticket, so I have nothing "
            "to propose.",
        )
    count = len(behind)
    suggestion = "one ticket" if count == 1 else f"{count} tickets, one for each"
    verb = "has" if count == 1 else "have"
    return to_room(
        f"reported {count} of {total} watched software behind and suggested "
        f"{plural(count, 'ticket')}.",
        f"{count} of {total} watched software {verb} new releases: {tag_list(behind)}. "
        f"I suggest {suggestion}.",
    )
