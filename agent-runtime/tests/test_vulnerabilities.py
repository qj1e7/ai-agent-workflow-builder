import json
from typing import Any

import httpx

from agent_runtime.vulnerabilities import AdvisoryReader, Nvd, NvdPace, Osv
from tests.fakes import FakeClock

LOG4J = "org.apache.logging.log4j:log4j-core"


def osv_record(
    vuln_id: str,
    aliases: list[str],
    severity: str | None = None,
    fixed: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    record: dict[str, Any] = {"id": vuln_id, "aliases": aliases, "summary": summary}
    if severity:
        record["database_specific"] = {"severity": severity}
    if fixed:
        record["affected"] = [
            {
                "package": {"ecosystem": "Maven", "name": LOG4J},
                "ranges": [
                    {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fixed}]}
                ],
            }
        ]
    return record


def nvd_answer(score: float, label: str, kind: str = "Primary") -> dict[str, Any]:
    metric = {"type": kind, "cvssData": {"baseScore": score, "baseSeverity": label}}
    return {"vulnerabilities": [{"cve": {"metrics": {"cvssMetricV31": [metric]}}}]}


class Services:
    """OSV and NVD on one fake transport. It records each request."""

    def __init__(
        self,
        records: list[dict[str, Any]],
        scores: dict[str, dict[str, Any]] | None = None,
        osv_status: int = 200,
    ) -> None:
        self.records = records
        self.scores = scores or {}
        self.osv_status = osv_status
        self.osv_bodies: list[dict[str, Any]] = []
        self.nvd_asked: list[str] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "osv.test":
            self.osv_bodies.append(json.loads(request.content))
            return httpx.Response(self.osv_status, json={"vulns": self.records})
        cve = request.url.params["cveId"]
        self.nvd_asked.append(cve)
        if cve not in self.scores:
            return httpx.Response(404)
        return httpx.Response(200, json=self.scores[cve])

    def reader(self, clock: FakeClock, key: str | None = None) -> AdvisoryReader:
        osv = Osv("https://osv.test", client=self.client)
        nvd = Nvd("https://nvd.test", api_key=key, client=self.client)
        return AdvisoryReader(osv, nvd, sleep=clock.sleep)


def test_osv_finds_and_nvd_scores_one_record_per_cve_worst_first():
    services = Services(
        [
            osv_record("GHSA-7rjr-3q55-vv33", ["CVE-2021-45046"], "CRITICAL", "2.16.0"),
            osv_record(
                "GHSA-jfh8-c2jp-5v3q", ["CVE-2021-44228"], "CRITICAL", "2.15.0", "Log4Shell"
            ),
            # The same CVE from a second database is merged, not counted twice.
            osv_record("MAVEN-2021-1", ["CVE-2021-44228"], None, "2.15.0"),
            osv_record("GHSA-8489-44mv-ggj8", [], "MODERATE", "2.17.1"),
        ],
        scores={
            "CVE-2021-44228": nvd_answer(10.0, "CRITICAL"),
            "CVE-2021-45046": nvd_answer(9.0, "CRITICAL"),
        },
    )
    looked = services.reader(FakeClock()).look("maven", LOG4J, "2.14.1")
    assert looked is not None and looked.state == "checked"
    assert services.osv_bodies[0] == {
        "version": "2.14.1",
        "package": {"name": LOG4J, "ecosystem": "Maven"},
    }
    found = looked.vulnerabilities
    assert [(v.id, v.severity, v.score) for v in found] == [
        ("CVE-2021-44228", "critical", 10.0),
        ("CVE-2021-45046", "critical", 9.0),
        ("GHSA-8489-44mv-ggj8", "medium", None),
    ]
    log4shell = found[0]
    assert log4shell.reported_by == ["OSV", "NVD"]
    assert log4shell.summary == "Log4Shell"
    assert log4shell.fixed_in == "2.15.0"
    assert log4shell.url == "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    assert log4shell.urgent
    # An advisory with no CVE is never sent to NVD, and links to OSV instead.
    assert found[2].reported_by == ["OSV"]
    assert found[2].url == "https://osv.dev/vulnerability/GHSA-8489-44mv-ggj8"
    assert not found[2].urgent
    assert sorted(services.nvd_asked) == ["CVE-2021-44228", "CVE-2021-45046"]


def test_nvd_is_paced_and_capped_and_a_cve_past_the_cap_keeps_the_advisory_severity():
    records = [osv_record(f"GHSA-{n}", [f"CVE-2024-{n:04d}"], "HIGH") for n in range(12)]
    services = Services(records, {f"CVE-2024-{n:04d}": nvd_answer(7.5, "HIGH") for n in range(12)})
    clock = FakeClock()
    looked = services.reader(clock).look("maven", LOG4J, "2.14.1")
    assert looked is not None
    pace = NvdPace.for_key(None)
    assert len(services.nvd_asked) == pace.max_lookups == 10
    assert clock.slept == [pace.wait_seconds] * (pace.max_lookups - 1)
    assert looked.unscored == 2
    unscored = [v for v in looked.vulnerabilities if v.score is None]
    assert len(unscored) == 2 and all(v.severity == "high" for v in unscored)


def test_a_key_lets_nvd_be_asked_faster():
    assert NvdPace.for_key("key") == NvdPace(0.6, 50)


def test_the_cap_starts_again_for_each_check():
    records = [osv_record(f"GHSA-{n}", [f"CVE-2024-{n:04d}"], "HIGH") for n in range(10)]
    services = Services(records)
    reader = services.reader(FakeClock())
    reader.start_check()
    reader.look("maven", LOG4J, "2.14.1")
    reader.start_check()
    reader.look("maven", LOG4J, "2.14.1")
    assert len(services.nvd_asked) == 20


def test_nvd_not_answering_keeps_the_advisory_and_says_it_was_not_scored():
    services = Services([osv_record("GHSA-1", ["CVE-2024-0001"], "HIGH")])
    looked = services.reader(FakeClock()).look("maven", LOG4J, "2.14.1")
    assert looked is not None and looked.unscored == 1
    assert [(v.severity, v.reported_by) for v in looked.vulnerabilities] == [("high", ["OSV"])]


def test_osv_down_means_could_not_check_never_none_found():
    services = Services([], osv_status=503)
    looked = services.reader(FakeClock()).look("npm", "express", "4.17.1")
    assert looked is not None
    assert looked.state == "could_not_check"
    assert looked.vulnerabilities == []
    assert looked.problem == "OSV answered 503"


def test_a_github_source_names_no_package_so_it_is_not_looked_up():
    services = Services([])
    assert services.reader(FakeClock()).look("github", "owner/repo", "1.0.0") is None
    assert services.osv_bodies == []


def test_the_fix_named_is_the_lowest_newer_than_our_version():
    services = Services(
        [osv_record("GHSA-1", [], "LOW", "2.3.2"), osv_record("GHSA-1", [], "LOW", "2.12.4")]
    )
    looked = services.reader(FakeClock()).look("maven", LOG4J, "2.12.1")
    assert looked is not None
    assert looked.vulnerabilities[0].fixed_in == "2.12.4"
