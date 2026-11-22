"""Known vulnerabilities in the version the team runs (ADR 0025).

OSV.dev finds them, because it matches a package by ecosystem, name and version. NVD then gives
each CVE its official CVSS score. NVD alone would need a CPE name for every watched software,
which nobody has confirmed, so it is never asked to find anything, only to score.

NVD allows about 5 requests every 30 seconds without a key and 50 with one, so lookups are
paced across the whole runtime, and capped in number and in time per check, so the check ends
well inside the 60 seconds n8n and platform-api give it. A CVE past the cap keeps the
advisory's own severity, and the finding says NVD did not score it. Every answer is read with a
size limit, and no redirect is followed (capped.py). Every source here only reads.
"""

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_runtime.capped import MEGABYTE, OutOfTime, TooLarge, read_capped, time_left
from agent_runtime.contract import Severity, Vulnerability, VulnerabilitySource
from agent_runtime.tags import parse_tag

DEFAULT_OSV_BASE = "https://api.osv.dev"
DEFAULT_NVD_BASE = "https://services.nvd.nist.gov"
TIMEOUT_SECONDS = 15.0
USER_AGENT = "ai-workflow-builder-version-checker"
OSV_PAGES = 5
RECORD_NOT_READ = "OSV or NVD sent a vulnerability record in a shape we don't read"
OSV_PAGE_BYTES = 8 * MEGABYTE
"""One OSV page holds up to 1,000 records. Past this, the answer is not one we read."""
NVD_ANSWER_BYTES = 2 * MEGABYTE
"""NVD's record of one CVE, with all its references, is well under this."""
NVD_BUDGET_SECONDS = 20.0
"""How long one check may spend scoring CVEs on NVD, waits included. Without a key that is about
four scores at NVD's pace; the rest keep the advisory's severity."""
SUMMARY_LENGTH = 200

# OSV names the ecosystems as below. A GitHub source names no package, so it has none.
OSV_ECOSYSTEMS: dict[str, str] = {"maven": "Maven", "npm": "npm"}

SEVERITY_ORDER: list[Severity] = ["critical", "high", "medium", "low", "unknown"]
_ADVISORY_SEVERITY: dict[str, Severity] = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MODERATE": "medium",
    "MEDIUM": "medium",
    "LOW": "low",
}


def _rank(severity: Severity) -> int:
    return SEVERITY_ORDER.index(severity)


@dataclass(frozen=True)
class NvdPace:
    """How often NVD may be asked, and how many CVEs one check scores."""

    wait_seconds: float
    max_lookups: int

    @classmethod
    def for_key(cls, key: str | None) -> NvdPace:
        return cls(0.6, 50) if key else cls(6.0, 10)


class AdvisoriesUnavailable(Exception):
    """OSV did not answer, so nothing can be said about vulnerabilities, not even none."""


# OSV's records, as far as we read them. Anything else in a record is ignored.
class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _OsvEvent(_Loose):
    introduced: str | None = None
    fixed: str | None = None


class _OsvRange(_Loose):
    type: str = ""
    events: list[_OsvEvent] = Field(default_factory=list[_OsvEvent])


class _OsvPackage(_Loose):
    name: str = ""
    ecosystem: str = ""


class _OsvAffected(_Loose):
    package: _OsvPackage | None = None
    ranges: list[_OsvRange] = Field(default_factory=list[_OsvRange])


class _OsvVuln(_Loose):
    id: str
    summary: str | None = None
    details: str | None = None
    aliases: list[str] = Field(default_factory=list[str])
    affected: list[_OsvAffected] = Field(default_factory=list[_OsvAffected])
    database_specific: dict[str, object] = Field(default_factory=dict[str, object])


class _OsvAnswer(_Loose):
    vulns: list[_OsvVuln] = Field(default_factory=list[_OsvVuln])
    next_page_token: str | None = None


@dataclass(frozen=True)
class Advisory:
    """One OSV record, reduced to what a finding needs."""

    id: str
    cve: str | None
    summary: str
    severity: Severity
    fixed: tuple[str, ...]


@dataclass(frozen=True)
class Found:
    """What OSV listed for one package version."""

    advisories: list[Advisory]
    all_read: bool = True
    """False when OSV had more pages than one check reads, so the list may not be complete."""


@dataclass(frozen=True)
class Score:
    score: float
    severity: Severity


class Osv:
    def __init__(self, base_url: str = DEFAULT_OSV_BASE, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    def query(self, ecosystem: str, name: str, version: str) -> Found:
        """The advisories on up to OSV_PAGES pages. Found.all_read is False when OSV had more."""
        found: list[Advisory] = []
        token: str | None = None
        for _ in range(OSV_PAGES):
            body: dict[str, object] = {
                "version": version,
                "package": {"name": name, "ecosystem": ecosystem},
            }
            if token:
                body["page_token"] = token
            answer = self._post(body)
            found += [_advisory(v, ecosystem, name) for v in answer.vulns]
            token = answer.next_page_token
            if not token:
                break
        return Found(found, all_read=not token)

    def _post(self, body: Mapping[str, object]) -> _OsvAnswer:
        try:
            status, content = read_capped(
                self._client,
                "POST",
                f"{self._base_url}/v1/query",
                limit=OSV_PAGE_BYTES,
                headers={"User-Agent": USER_AGENT},
                json=body,
            )
        except httpx.TransportError as error:
            raise AdvisoriesUnavailable("OSV could not be reached") from error
        except TooLarge as error:
            raise AdvisoriesUnavailable("OSV answered more than one page should hold") from error
        except OutOfTime as error:
            raise AdvisoriesUnavailable("the check ran out of time before OSV answered") from error
        if status >= 300:
            raise AdvisoriesUnavailable(f"OSV answered {status}")
        try:
            return _OsvAnswer.model_validate_json(content)
        except ValidationError as error:
            raise AdvisoriesUnavailable("OSV answered in a way we did not expect") from error


def _advisory(vuln: _OsvVuln, ecosystem: str, name: str) -> Advisory:
    names = [vuln.id, *vuln.aliases]
    cve = next((n for n in names if n.upper().startswith("CVE-")), None)
    raw = vuln.database_specific.get("severity")
    severity = _ADVISORY_SEVERITY.get(raw.upper(), "unknown") if isinstance(raw, str) else "unknown"
    fixed = tuple(
        event.fixed
        for affected in vuln.affected
        if affected.package is None
        or (affected.package.ecosystem == ecosystem and affected.package.name == name)
        for span in affected.ranges
        for event in span.events
        if event.fixed
    )
    text = (vuln.summary or vuln.details or "").strip().splitlines()
    return Advisory(
        id=vuln.id,
        cve=cve.upper() if cve else None,
        summary=(text[0] if text else "")[:SUMMARY_LENGTH],
        severity=severity,
        fixed=fixed,
    )


class Nvd:
    def __init__(
        self,
        base_url: str = DEFAULT_NVD_BASE,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": USER_AGENT}
        if api_key:
            self._headers["apiKey"] = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self.pace = NvdPace.for_key(api_key)

    def score(self, cve: str) -> Score | None:
        """NVD's CVSS base score for one CVE, or None when NVD did not give one."""
        try:
            status, content = read_capped(
                self._client,
                "GET",
                f"{self._base_url}/rest/json/cves/2.0",
                limit=NVD_ANSWER_BYTES,
                params={"cveId": cve},
                headers=self._headers,
            )
        except httpx.TransportError, TooLarge, OutOfTime:
            return None
        if status >= 300:
            return None
        try:
            document: object = json.loads(content)
        except ValueError:
            return None
        return _nvd_score(document)


_METRIC_KEYS = ("cvssMetricV31", "cvssMetricV40", "cvssMetricV30")


def _nvd_score(document: object) -> Score | None:
    if not isinstance(document, dict):
        return None
    items = cast(dict[str, object], document).get("vulnerabilities")
    if not isinstance(items, list) or not items:
        return None
    first = cast(list[object], items)[0]
    cve = cast(dict[str, object], first).get("cve") if isinstance(first, dict) else None
    metrics = cast(dict[str, object], cve).get("metrics") if isinstance(cve, dict) else None
    if not isinstance(metrics, dict):
        return None
    for key in _METRIC_KEYS:
        entries = cast(dict[str, object], metrics).get(key)
        if not isinstance(entries, list):
            continue
        # NVD's own score, marked Primary, comes before one a vendor sent.
        listed = [
            cast(dict[str, object], e) for e in cast(list[object], entries) if isinstance(e, dict)
        ]
        listed.sort(key=lambda e: e.get("type") != "Primary")
        for entry in listed:
            data = entry.get("cvssData")
            if not isinstance(data, dict):
                continue
            values = cast(dict[str, object], data)
            score, label = values.get("baseScore"), values.get("baseSeverity")
            if isinstance(score, int | float) and isinstance(label, str):
                return Score(float(score), _ADVISORY_SEVERITY.get(label.upper(), "unknown"))
    return None


type CheckState = Literal["checked", "could_not_check"]


@dataclass(frozen=True)
class Looked:
    """What one software's vulnerability check found."""

    state: CheckState
    vulnerabilities: list[Vulnerability] = field(default_factory=list[Vulnerability])
    unscored: int = 0
    """How many CVEs NVD did not score: the check's cap or time ran out, or NVD did not answer."""
    problem: str | None = None
    all_read: bool = True
    """False when OSV listed more than one check reads, so there may be more than these."""


class AdvisoryReader:
    """Finds the known vulnerabilities of package versions and scores them. One reader serves the
    whole runtime: NVD's pace is kept across every check, and each check has its own cap and
    time budget (start_check)."""

    def __init__(
        self,
        osv: Osv,
        nvd: Nvd | None,
        sleep: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
        budget_seconds: float = NVD_BUDGET_SECONDS,
    ) -> None:
        self._osv = osv
        self._nvd = nvd
        self._sleep = sleep
        self._clock = clock
        self._budget = budget_seconds
        self._pace = threading.Lock()
        self._last_asked: float | None = None

    def start_check(self) -> AdvisoryCheck:
        """A new check's own count and clock, so checks that run at once don't share them."""
        return AdvisoryCheck(self, self._clock())

    def query(self, ecosystem: str, name: str, version: str) -> Found:
        return self._osv.query(ecosystem, name, version)

    def score(self, cve: str, check: AdvisoryCheck) -> Score | None:
        """NVD's score, or None past the check's cap or time budget. Calls from every check wait
        their turn, so the runtime never asks NVD faster than its pace."""
        nvd = self._nvd
        if nvd is None or check.lookups >= nvd.pace.max_lookups:
            return None
        with self._pace:
            now = self._clock()
            wait = 0.0
            if self._last_asked is not None:
                wait = max(0.0, self._last_asked + nvd.pace.wait_seconds - now)
            if now + wait - check.started > self._budget:
                return None
            left = time_left()
            if left is not None and left <= wait:
                return None
            if wait:
                self._sleep(wait)
            check.lookups += 1
            self._last_asked = self._clock()
            return nvd.score(cve)


class AdvisoryCheck:
    """One check's vulnerability lookups, from AdvisoryReader.start_check."""

    def __init__(self, reader: AdvisoryReader, started: float) -> None:
        self._reader = reader
        self.started = started
        self.lookups = 0

    def look(self, kind: str, name: str, version: str) -> Looked | None:
        """None when the source kind names no package OSV knows."""
        ecosystem = OSV_ECOSYSTEMS.get(kind)
        if ecosystem is None:
            return None
        try:
            found = self._reader.query(ecosystem, name, version)
        except AdvisoriesUnavailable as error:
            return Looked("could_not_check", problem=str(error))
        try:
            merged, unscored = self._merge(found.advisories, version)
        except ValidationError:
            # One record outside the contract, as an id over 60 letters or a score over 10, makes
            # only this package "could not check". The check goes on for the rest.
            return Looked("could_not_check", problem=RECORD_NOT_READ)
        return Looked("checked", merged, unscored, all_read=found.all_read)

    def _merge(
        self, advisories: Iterable[Advisory], version: str
    ) -> tuple[list[Vulnerability], int]:
        by_key: dict[str, list[Advisory]] = {}
        for advisory in advisories:
            by_key.setdefault(advisory.cve or advisory.id, []).append(advisory)
        found: list[Vulnerability] = []
        unscored = 0
        for key, group in by_key.items():
            cve = group[0].cve
            score = self._reader.score(cve, self) if cve else None
            if cve and score is None:
                unscored += 1
            found.append(_vulnerability(key, cve, group, score, version))
        found.sort(key=lambda v: (_rank(v.severity), -(v.score or 0), v.id))
        return found, unscored


def _vulnerability(
    key: str, cve: str | None, group: list[Advisory], score: Score | None, version: str
) -> Vulnerability:
    # A group always holds at least one advisory, the one that made its key.
    severities: list[Severity] = [a.severity for a in group]
    advisory_severity = min(severities, key=_rank)
    reported_by: list[VulnerabilitySource] = ["OSV"]
    if score is not None:
        reported_by.append("NVD")
    url = (
        f"https://nvd.nist.gov/vuln/detail/{cve}"
        if cve
        else f"https://osv.dev/vulnerability/{group[0].id}"
    )
    return Vulnerability(
        id=key,
        severity=score.severity if score else advisory_severity,
        score=score.score if score else None,
        summary=next((a.summary for a in group if a.summary), ""),
        fixed_in=_lowest_fix(version, [f for a in group for f in a.fixed]),
        reported_by=reported_by,
        url=url,
    )


def _lowest_fix(version: str, fixes: list[str]) -> str | None:
    """The lowest fixed version newer than ours, so the ticket can name the smallest upgrade."""
    ours = parse_tag(version)
    parsed = [p for p in map(parse_tag, fixes) if p]
    if ours is not None:
        parsed = [p for p in parsed if p.key > ours.key]
    return min(parsed, key=lambda p: p.key).tag if parsed else None
