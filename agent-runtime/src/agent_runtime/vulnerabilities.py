"""Known vulnerabilities in the version the team runs (ADR 0025).

OSV.dev finds them, because it matches a package by ecosystem, name and version. NVD then gives
each CVE its official CVSS score. NVD alone would need a CPE name for every watched software,
which nobody has confirmed, so it is never asked to find anything, only to score.

NVD allows about 5 requests every 30 seconds without a key and 50 with one, so lookups are
paced and capped per check. A CVE past the cap keeps the advisory's own severity, and the
finding says NVD did not score it. Every source here only reads.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_runtime.contract import Severity, Vulnerability, VulnerabilitySource
from agent_runtime.tags import parse_tag

DEFAULT_OSV_BASE = "https://api.osv.dev"
DEFAULT_NVD_BASE = "https://services.nvd.nist.gov"
TIMEOUT_SECONDS = 15.0
USER_AGENT = "ai-workflow-builder-version-checker"
OSV_PAGES = 5
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
class Score:
    score: float
    severity: Severity


class Osv:
    def __init__(self, base_url: str = DEFAULT_OSV_BASE, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    def query(self, ecosystem: str, name: str, version: str) -> list[Advisory]:
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
        return found

    def _post(self, body: Mapping[str, object]) -> _OsvAnswer:
        try:
            response = self._client.post(
                f"{self._base_url}/v1/query", json=body, headers={"User-Agent": USER_AGENT}
            )
        except httpx.TransportError as error:
            raise AdvisoriesUnavailable("OSV could not be reached") from error
        if response.status_code >= 300:
            raise AdvisoriesUnavailable(f"OSV answered {response.status_code}")
        try:
            return _OsvAnswer.model_validate_json(response.content)
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
            response = self._client.get(
                f"{self._base_url}/rest/json/cves/2.0",
                params={"cveId": cve},
                headers=self._headers,
            )
        except httpx.TransportError:
            return None
        if response.status_code >= 300:
            return None
        try:
            document: object = response.json()
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
    """How many CVEs NVD did not score, because the cap was reached or NVD did not answer."""
    problem: str | None = None


class AdvisoryReader:
    """Finds the known vulnerabilities of one package version and scores them."""

    def __init__(self, osv: Osv, nvd: Nvd | None, sleep: Callable[[float], None]) -> None:
        self._osv = osv
        self._nvd = nvd
        self._sleep = sleep
        self._lookups = 0

    def start_check(self) -> None:
        """The NVD cap is per check, so a new check starts counting again."""
        self._lookups = 0

    def look(self, kind: str, name: str, version: str) -> Looked | None:
        """None when the source kind names no package OSV knows."""
        ecosystem = OSV_ECOSYSTEMS.get(kind)
        if ecosystem is None:
            return None
        try:
            advisories = self._osv.query(ecosystem, name, version)
        except AdvisoriesUnavailable as error:
            return Looked("could_not_check", problem=str(error))
        merged, unscored = self._merge(advisories, version)
        return Looked("checked", merged, unscored)

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
            score = self._score(cve) if cve else None
            if cve and score is None:
                unscored += 1
            found.append(_vulnerability(key, cve, group, score, version))
        found.sort(key=lambda v: (_rank(v.severity), -(v.score or 0), v.id))
        return found, unscored

    def _score(self, cve: str) -> Score | None:
        nvd = self._nvd
        if nvd is None or self._lookups >= nvd.pace.max_lookups:
            return None
        if self._lookups:
            self._sleep(nvd.pace.wait_seconds)
        self._lookups += 1
        return nvd.score(cve)


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
