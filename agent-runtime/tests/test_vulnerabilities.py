import json
from typing import Any

import httpx

from agent_runtime.vulnerabilities import (
    NVD_ANSWER_BYTES,
    NVD_BUDGET_SECONDS,
    OSV_PAGE_BYTES,
    OSV_PAGES,
    AdvisoryReader,
    Nvd,
    NvdPace,
    Osv,
)
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
        return AdvisoryReader(osv, nvd, sleep=clock.sleep, clock=lambda: clock.now.timestamp())


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
    looked = services.reader(FakeClock()).start_check().look("maven", LOG4J, "2.14.1")
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


def many(count: int) -> Services:
    records = [osv_record(f"GHSA-{n}", [f"CVE-2024-{n:04d}"], "HIGH") for n in range(count)]
    scores = {f"CVE-2024-{n:04d}": nvd_answer(7.5, "HIGH") for n in range(count)}
    return Services(records, scores)


def test_without_a_key_nvd_is_paced_and_stops_at_the_check_s_time_budget():
    """Ten keyless lookups at NVD's pace took 54 seconds, against the 60 n8n and platform-api
    give the task. The budget stops them at 20, and the rest keep the advisory's severity."""
    services = many(12)
    clock = FakeClock()
    looked = services.reader(clock).start_check().look("maven", LOG4J, "2.14.1")
    assert looked is not None
    pace = NvdPace.for_key(None)
    assert len(services.nvd_asked) == 4
    assert clock.slept == [pace.wait_seconds] * 3
    assert sum(clock.slept) <= NVD_BUDGET_SECONDS
    assert looked.unscored == 8
    unscored = [v for v in looked.vulnerabilities if v.score is None]
    assert len(unscored) == 8 and all(v.severity == "high" for v in unscored)


def test_the_count_cap_holds_when_the_budget_allows_more():
    services = many(12)
    clock = FakeClock()
    osv = Osv("https://osv.test", client=services.client)
    nvd = Nvd("https://nvd.test", client=services.client)
    reader = AdvisoryReader(
        osv, nvd, sleep=clock.sleep, clock=lambda: clock.now.timestamp(), budget_seconds=600
    )
    looked = reader.start_check().look("maven", LOG4J, "2.14.1")
    assert looked is not None
    assert len(services.nvd_asked) == NvdPace.for_key(None).max_lookups == 10
    assert looked.unscored == 2


def test_a_key_lets_nvd_be_asked_faster():
    assert NvdPace.for_key("key") == NvdPace(0.6, 50)


def test_each_check_has_its_own_cap_and_budget_but_the_pace_is_shared():
    """Two checks at once count separately, and neither resets the other, but NVD is never
    asked faster than its pace by the two together. Both start at 0 s: the first asks at 0, 6
    and 12, so the second, waiting its turn, asks at 18 and has no time left for 24."""
    services = many(3)
    clock = FakeClock()
    reader = services.reader(clock)
    first, second = reader.start_check(), reader.start_check()
    first.look("maven", LOG4J, "2.14.1")
    second.look("maven", LOG4J, "2.14.1")
    assert (first.lookups, second.lookups) == (3, 1)
    assert clock.slept == [NvdPace.for_key(None).wait_seconds] * 3


def test_a_new_check_starts_its_count_and_clock_again():
    """The first check asks at 0, 6, 12 and 18 s. The next starts at 18, still keeps the pace,
    and asks at 24, 30 and 36 inside its own 20 s."""
    services = many(10)
    clock = FakeClock()
    reader = services.reader(clock)
    reader.start_check().look("maven", LOG4J, "2.14.1")
    reader.start_check().look("maven", LOG4J, "2.14.1")
    assert len(services.nvd_asked) == 4 + 3


def test_osv_listing_more_pages_than_a_check_reads_says_so():
    pages = {"count": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        pages["count"] += 1
        vuln = osv_record(f"GHSA-{pages['count']}", [], "HIGH")
        return httpx.Response(200, json={"vulns": [vuln], "next_page_token": "more"})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    reader = AdvisoryReader(Osv("https://osv.test", client=client), None, sleep=FakeClock().sleep)
    looked = reader.start_check().look("maven", LOG4J, "2.14.1")
    assert looked is not None and looked.state == "checked"
    assert pages["count"] == OSV_PAGES and len(looked.vulnerabilities) == OSV_PAGES
    assert not looked.all_read


def test_an_osv_answer_past_its_size_limit_is_not_read():
    huge = b"x" * (OSV_PAGE_BYTES + 1)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=huge))
    )
    reader = AdvisoryReader(Osv("https://osv.test", client=client), None, sleep=FakeClock().sleep)
    looked = reader.start_check().look("maven", LOG4J, "2.14.1")
    assert looked is not None and looked.state == "could_not_check"
    assert looked.problem == "OSV answered more than one page should hold"


def test_an_nvd_answer_past_its_size_limit_or_a_redirect_leaves_the_cve_unscored():
    huge = b"{" + b" " * NVD_ANSWER_BYTES + b"}"
    answers = iter(
        [
            httpx.Response(200, content=huge),
            httpx.Response(302, headers={"location": "https://elsewhere.test/"}),
        ]
    )
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url.host))
        return next(answers)

    nvd = Nvd("https://nvd.test", client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert nvd.score("CVE-2024-0001") is None
    assert nvd.score("CVE-2024-0002") is None
    assert asked == ["nvd.test", "nvd.test"]


def test_nvd_not_answering_keeps_the_advisory_and_says_it_was_not_scored():
    services = Services([osv_record("GHSA-1", ["CVE-2024-0001"], "HIGH")])
    looked = services.reader(FakeClock()).start_check().look("maven", LOG4J, "2.14.1")
    assert looked is not None and looked.unscored == 1
    assert [(v.severity, v.reported_by) for v in looked.vulnerabilities] == [("high", ["OSV"])]


def test_osv_down_means_could_not_check_never_none_found():
    services = Services([], osv_status=503)
    looked = services.reader(FakeClock()).start_check().look("npm", "express", "4.17.1")
    assert looked is not None
    assert looked.state == "could_not_check"
    assert looked.vulnerabilities == []
    assert looked.problem == "OSV answered 503"


def test_a_github_source_names_no_package_so_it_is_not_looked_up():
    services = Services([])
    assert services.reader(FakeClock()).start_check().look("github", "owner/repo", "1.0.0") is None
    assert services.osv_bodies == []


def test_the_fix_named_is_the_lowest_newer_than_our_version():
    services = Services(
        [osv_record("GHSA-1", [], "LOW", "2.3.2"), osv_record("GHSA-1", [], "LOW", "2.12.4")]
    )
    looked = services.reader(FakeClock()).start_check().look("maven", LOG4J, "2.12.1")
    assert looked is not None
    assert looked.vulnerabilities[0].fixed_in == "2.12.4"
