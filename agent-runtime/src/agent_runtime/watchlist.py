# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_runtime.contract import (
    REPO_PATTERN,
    SOURCE_NAMES,
    CarryForward,
    Finding,
    FindingState,
    ProposedIntent,
    SoftwareToCheck,
    TaskError,
    TaskOutput,
    Vulnerability,
    WatchlistInputs,
)
from agent_runtime.events import Draft
from agent_runtime.release_source import (
    DEFAULT_RETRY,
    MovableSource,
    Release,
    ReleaseSource,
    RetryPolicy,
    SourceRejected,
    SourceUnavailable,
    candidates,
    could_not_check,
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
from agent_runtime.vulnerabilities import AdvisoryReader, Looked

NO_PLAIN_VERSION = "No release has a plain version number."
NOT_FOUND_STATUSES = {404, 410}

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
    newer = newer_than(our, read, any_family=True)
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


@dataclass(frozen=True)
class Address:
    """What GitHub says about the saved repository: the name it answers for, or that it has none."""

    full_name: str | None = None
    not_found: bool = False


class Watching:
    """Reads one repository's releases and notes what GitHub said on the way: a rename shows as a
    redirect, and a 404 on the releases says the repository is gone. This is why a check needs no
    second call to learn the repository's address, except after a redirect."""

    def __init__(self, source: MovableSource) -> None:
        self._source = source
        self.read = False
        self.redirected = False
        self.not_found = False

    def fetch(self, repo: str) -> list[Release]:
        try:
            got = self._source.fetch_noting_move(repo)
        except SourceRejected as refused:
            self.not_found = refused.status in NOT_FOUND_STATUSES
            raise
        self.read, self.redirected = True, got.redirected
        return got.releases

    def address(self, repo: str) -> Address:
        if self.not_found:
            return Address(not_found=True)
        if not self.read:
            return Address()
        if not self.redirected:
            return Address(full_name=repo)
        try:
            name = self._source.current_name(repo)
        except SourceRejected, SourceUnavailable:
            return Address()
        return Address(full_name=name if re.fullmatch(REPO_PATTERN, name) else None)


def with_address(finding: Finding, address: Address) -> Finding:
    return finding.model_copy(
        update={"full_name": address.full_name, "not_found": address.not_found}
    )


def source_name(item: SoftwareToCheck) -> str:
    return SOURCE_NAMES[item.source.kind]


def _severity_words(vulnerability: Vulnerability) -> str:
    score = "" if vulnerability.score is None else f", CVSS {vulnerability.score:g}"
    return f"{vulnerability.severity}{score}"


def vulnerability_lines(finding: Finding) -> str:
    """The ticket's section on known vulnerabilities. Each line links its record, so the
    Approver checks the evidence, not our summary of it."""
    if finding.vulnerability_check != "checked" or not finding.vulnerabilities:
        return ""
    lines: list[str] = []
    for v in finding.vulnerabilities:
        fix = f" Fixed in {v.fixed_in}." if v.fixed_in else ""
        about = f" {v.summary}" if v.summary else ""
        sources = " and ".join(v.reported_by)
        lines.append(f"- {v.id} ({_severity_words(v)}, reported by {sources}).{about}{fix} {v.url}")
    return f"\n\nOur version has {vulnerability_count(len(lines))}:\n" + "\n".join(lines)


def vulnerability_count(count: int) -> str:
    return f"{count} known vulnerability" if count == 1 else f"{count} known vulnerabilities"


def is_urgent(finding: Finding) -> bool:
    return finding.vulnerability_check == "checked" and any(
        v.urgent for v in finding.vulnerabilities
    )


def ticket_for(item: SoftwareToCheck, finding: Finding) -> ProposedIntent:
    assert item.our_version and finding.newest, "only a software that is behind gets a ticket"
    name, ref, our = item.name, item.source.ref, item.our_version
    if finding.full_name is not None and finding.full_name.casefold() != ref.casefold():
        ref = f"{ref}, which GitHub now calls {finding.full_name}"
    count = plural(len(finding.new_versions), "new release")
    bullets = "\n".join(f"- {tag}" for tag in finding.new_versions)
    if item.from_first_check:
        title = f"Upgrade {name} to {finding.newest}"
        newer = f"newer than {our}, the newest the first check read"
        reason = (
            f"{name} {finding.newest} is out, newer than {our}, the newest the first check read"
        )
    else:
        title = f"Upgrade {name} from {our} to {finding.newest}"
        newer = f"newer than our version {our}"
        reason = f"{name} {finding.newest} is out, and we run {our}"
    urgent = is_urgent(finding)
    if urgent:
        # The ticket still waits for an Approver, like any other (ADR 0025).
        title = f"Urgent: {title}"
        reason = f"{reason}, which has a critical known vulnerability"
    return ProposedIntent(
        kind="create_ticket",
        fields={
            "title": title,
            "body": f"{name} has {count} on {source_name(item)} ({ref}) {newer}:\n"
            f"{bullets}{vulnerability_lines(finding)}\n\nProposed by the AI workflow builder.",
        },
        reason=reason,
        subject=item.id,
    )


@dataclass(frozen=True)
class NothingChecked:
    error: TaskError
    findings: list[Finding]


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
        source: MovableSource,
        summarizer: Summarizer,
        sleep: Callable[[float], None],
        retry: RetryPolicy = DEFAULT_RETRY,
        registries: Mapping[str, ReleaseSource] | None = None,
        advisories: AdvisoryReader | None = None,
    ) -> None:
        """source reads GitHub. registries reads every other source kind, by kind, and a kind
        with no reader here cannot be checked. Without advisories, no vulnerability is looked
        up and every finding says not_checked."""
        self._source = source
        self._summarizer = summarizer
        self._sleep = sleep
        self._retry = retry
        self._registries = dict(registries or {})
        self._advisories = advisories
        self._graph = self._build()

    def check(
        self, inputs: WatchlistInputs, emit: Callable[[Draft], None]
    ) -> TaskOutput | NothingChecked:
        final: dict[str, object] = {}
        for mode, chunk in self._graph.stream(
            WatchlistState(inputs=inputs), stream_mode=["custom", "values"]
        ):
            if mode == "custom" and isinstance(chunk, Draft):
                emit(chunk)
            elif mode == "values" and isinstance(chunk, dict):
                final = cast(dict[str, object], chunk)
        outcome = final.get("error") or final.get("output")
        if isinstance(outcome, TaskError):
            return NothingChecked(outcome, cast(list[Finding], final.get("findings", [])))
        assert isinstance(outcome, TaskOutput)
        return outcome

    def _build(self):
        graph = StateGraph(WatchlistState)
        graph.add_node("read_sources", self._read_sources)
        graph.add_node("check_vulnerabilities", self._check_vulnerabilities)
        graph.add_node("report", self._report)
        graph.add_edge(START, "read_sources")
        graph.add_edge("read_sources", "check_vulnerabilities")
        graph.add_edge("check_vulnerabilities", "report")
        graph.add_edge("report", END)
        return graph.compile()

    def _read_one(
        self, item: SoftwareToCheck, write: Callable[[Draft], None]
    ) -> tuple[list[Release] | TaskError, Address]:
        """GitHub notes a moved repository on the way. A registry has no such address."""
        name = source_name(item)
        if item.source.kind == "github":
            watching = Watching(self._source)
            releases = read_releases(watching, item.source.ref, self._retry, self._sleep, write)
            return releases, watching.address(item.source.ref)
        registry = self._registries.get(item.source.kind)
        if registry is None:
            return TaskError(
                type="UpstreamRejected",
                message=f"This runtime has no reader for {name} set up",
                retryable=False,
            ), Address()
        found = read_releases(
            registry, item.source.ref, self._retry, self._sleep, write, source_name=name
        )
        return found, Address()

    def _read_sources(self, state: WatchlistState) -> Update:
        write = get_stream_writer()
        inputs = state.inputs
        findings: list[Finding] = []
        read_errors: list[TaskError] = []
        last = len(inputs.software) - 1
        for position, item in enumerate(inputs.software):
            where = "" if item.source.kind == "github" else f" on {source_name(item)}"
            write(started("read_source", f"reading the releases of {item.name}{where}."))
            releases, address = self._read_one(item, write)
            if isinstance(releases, TaskError):
                read: Read = releases
                read_errors.append(releases)
            else:
                read = candidates(releases, inputs.tag_pattern)
            finding = with_address(decide(item, read), address)
            findings.append(finding)
            write(_read_finished(item, finding))
            if finding.state == "cant_check":
                unreadable = isinstance(read, TaskError)
                write(_cannot_check(item, finding, unreadable=unreadable, more=position < last))
        return {"findings": findings, "read_errors": read_errors}

    def _check_vulnerabilities(self, state: WatchlistState) -> Update:
        """Looks only at the version the team runs. A version the first check read is not one
        anyone said the team runs, so it is not looked up either (ADR 0025)."""
        advisories = self._advisories
        if advisories is None:
            return {}
        write = get_stream_writer()
        advisories.start_check()
        findings = list(state.findings)
        for index, item in enumerate(state.inputs.software):
            if item.our_version is None or item.from_first_check:
                continue
            if item.source.kind == "github":
                continue
            write(
                started(
                    "check_vulnerabilities",
                    f"looking up known vulnerabilities in {item.name} {item.our_version}.",
                )
            )
            looked = advisories.look(item.source.kind, item.source.ref, item.our_version)
            if looked is None:
                continue
            findings[index] = findings[index].model_copy(
                update={
                    "vulnerability_check": looked.state,
                    "vulnerabilities": looked.vulnerabilities,
                }
            )
            write(_vulnerabilities_finished(item, looked))
            write(_vulnerabilities_to_room(item, looked))
        return {"findings": findings}

    def _report(self, state: WatchlistState) -> Update:
        write = get_stream_writer()
        items = state.inputs.software
        findings = state.findings
        if all(f.state == "cant_check" for f in findings):
            error = _nothing_readable(items, findings, state.read_errors)
            reason = (
                f"{items[0].name} could not be checked."
                if len(items) == 1
                else "none of the watched software could be checked."
            )
            write(failed(None, error, reason))
            return {"error": error}
        pairs = list(zip(items, findings, strict=True))
        behind = [(item, f) for item, f in pairs if f.state == "behind"]
        tickets = [ticket_for(item, f) for item, f in behind]
        write(_report_total(items, behind))
        checked = [Checked(item.name, f) for item, f in pairs]
        # The model writes about versions only. Vulnerabilities are added in fixed words, so
        # the summary never drops one and never makes one up.
        summary = self._summarizer.summarise_check(checked)
        vulnerable = vulnerability_sentence(pairs)
        output = TaskOutput(
            summary=f"{summary} {vulnerable}" if vulnerable else summary,
            new_tags=[],
            proposed=tickets,
            carry_forward=CarryForward(),
            findings=findings,
        )
        return {"output": output}


def _nothing_readable(
    items: list[SoftwareToCheck], findings: list[Finding], read_errors: list[TaskError]
) -> TaskError:
    retryable = any(e.retryable for e in read_errors)
    if len(items) == 1:
        message = could_not_check(items[0].name, findings[0].detail.removesuffix("."))
    else:
        cause = read_errors[0].message if read_errors else NO_PLAIN_VERSION.removesuffix(".")
        message = f"None of the {len(items)} watched software could be checked. {cause}"
    return TaskError(
        type="UpstreamUnavailable" if retryable else "UpstreamRejected",
        message=message,
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


def _cannot_check(
    item: SoftwareToCheck, finding: Finding, *, unreadable: bool, more: bool
) -> Draft:
    start = (
        f"I could not read {item.name}'s releases"
        if unreadable
        else f"I could not check {item.name}"
    )
    if not more:
        return to_room(f"could not check {item.name}.", f"{start}: {finding.detail}")
    return to_room(
        f"could not check {item.name} and carried on.",
        f"{start}: {finding.detail} I will carry on with the rest.",
    )


def _report_total(
    items: list[SoftwareToCheck], behind: list[tuple[SoftwareToCheck, Finding]]
) -> Draft:
    total = len(items)
    if not behind:
        checked = items[0].name if total == 1 else f"{total} watched software"
        return to_room(
            "reported to the room that nothing needs a ticket.",
            f"I checked {checked}. Nothing needs a ticket, so I have nothing to propose.",
        )
    if total == 1:
        item, finding = behind[0]
        return to_room(
            f"reported that {item.name} is behind and suggested one ticket.",
            f"{item.name} has a new release: {finding.newest}. I suggest one ticket.",
        )
    names = [item.name for item, _ in behind]
    count = len(names)
    suggestion = "one ticket" if count == 1 else f"{count} tickets, one for each"
    verb = "has" if count == 1 else "have"
    return to_room(
        f"reported {count} of {total} watched software behind and suggested "
        f"{plural(count, 'ticket')}.",
        f"{count} of {total} watched software {verb} new releases: {tag_list(names)}. "
        f"I suggest {suggestion}.",
    )


def _vulnerabilities_finished(item: SoftwareToCheck, looked: Looked) -> Draft:
    if looked.state == "could_not_check":
        what = f"could not look up vulnerabilities in {item.name}."
    else:
        what = f"found {vulnerability_count(len(looked.vulnerabilities))} in {item.name}."
    result: dict[str, object] = {
        "software_id": item.id,
        "vulnerability_check": looked.state,
        "vulnerabilities": [v.id for v in looked.vulnerabilities],
    }
    return finished("check_vulnerabilities", what, result)


def _vulnerabilities_to_room(item: SoftwareToCheck, looked: Looked) -> Draft:
    version = f"{item.name} {item.our_version}"
    if looked.state == "could_not_check":
        return to_room(
            f"could not look up vulnerabilities in {item.name}.",
            f"I could not look up known vulnerabilities in {version}: {looked.problem}. "
            "This does not mean it has none.",
        )
    found = looked.vulnerabilities
    if not found:
        return to_room(
            f"found no known vulnerabilities in {item.name}.",
            f"OSV lists no known vulnerabilities in {version}.",
        )
    worst = found[0]
    urgent = [v.id for v in found if v.urgent]
    text = (
        f"{version} has {vulnerability_count(len(found))}. The worst is {worst.id} "
        f"({_severity_words(worst)})."
    )
    if urgent:
        text += f" {tag_list(urgent)} {'is' if len(urgent) == 1 else 'are'} critical."
    if looked.unscored:
        text += (
            f" NVD did not score {looked.unscored} of them, so those show the advisory's "
            "own severity."
        )
    return to_room(f"reported {vulnerability_count(len(found))} in {item.name}.", text)


def vulnerability_sentence(pairs: list[tuple[SoftwareToCheck, Finding]]) -> str:
    """One fixed sentence for the run's summary, or nothing when no vulnerability was found
    and no lookup failed."""
    parts: list[str] = []
    failed_names: list[str] = []
    for item, finding in pairs:
        if finding.vulnerability_check == "could_not_check":
            failed_names.append(item.name)
        elif finding.vulnerabilities:
            critical = sum(1 for v in finding.vulnerabilities if v.urgent)
            extra = f", {critical} critical" if critical else ""
            count = vulnerability_count(len(finding.vulnerabilities))
            parts.append(f"{item.name} {item.our_version} has {count}{extra}")
    sentences: list[str] = []
    if parts:
        sentences.append(f"{'; '.join(parts)}.")
    if failed_names:
        sentences.append(f"Vulnerabilities could not be looked up for {tag_list(failed_names)}.")
    return " ".join(sentences)
