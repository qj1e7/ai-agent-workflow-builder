"""The watchlist check with the sources ADR 0025 adds: package registries and vulnerabilities."""

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from agent_runtime.contract import (
    AgentMessageEvent,
    GithubSource,
    MavenSource,
    NpmSource,
    SoftwareToCheck,
    TaskFailed,
    TaskFinished,
    TaskRequest,
    WatchlistInputs,
)
from agent_runtime.contracts import watchlist_request
from agent_runtime.events import EventLog
from agent_runtime.planner import FixedPlanner, run_task
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from agent_runtime.vulnerabilities import AdvisoryReader
from tests.fakes import FakeClock, FakeSource
from tests.test_vulnerabilities import LOG4J, Services, nvd_answer, osv_record

LOG4J_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2L"
EXPRESS_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2M"
GITHUB_ID = "sw_01JC2A3B4C5D6E7F8G9H0J1K2N"


class Registry:
    """A registry with fixed versions per package, or a lasting outage or refusal."""

    def __init__(
        self, versions: dict[str, list[str]], down: int | None = None, refused: int | None = None
    ) -> None:
        self.versions = versions
        self.down = down
        self.refused = refused
        self.calls: list[str] = []

    def fetch(self, repo: str) -> list[Release]:
        self.calls.append(repo)
        if self.refused:
            raise SourceRejected(self.refused)
        if self.down:
            raise SourceUnavailable(self.down)
        return [Release(tag=v) for v in self.versions[repo]]


LOG4J_VERSIONS = ["2.14.1", "2.17.1", "2.24.3", "2.25.0-beta1"]
LOG4SHELL = [
    osv_record("GHSA-jfh8-c2jp-5v3q", ["CVE-2021-44228"], "CRITICAL", "2.15.0", "Log4Shell")
]


def log4j(our: str | None = "2.14.1", from_first_check: bool = False) -> SoftwareToCheck:
    return SoftwareToCheck(
        id=LOG4J_ID,
        name="Log4j",
        source=MavenSource(ref=LOG4J),
        our_version=our,
        from_first_check=from_first_check,
    )


def express(our: str = "4.21.2") -> SoftwareToCheck:
    return SoftwareToCheck(
        id=EXPRESS_ID, name="Express", source=NpmSource(ref="express"), our_version=our
    )


def on_github(our: str = "1.2.14") -> SoftwareToCheck:
    return SoftwareToCheck(
        id=GITHUB_ID,
        name="LangGraph",
        source=GithubSource(ref="langchain-ai/langgraph"),
        our_version=our,
    )


def request_for(*software: SoftwareToCheck) -> TaskRequest:
    request = watchlist_request("run_01JC2")
    assert isinstance(request.inputs, WatchlistInputs)
    inputs = request.inputs.model_copy(update={"software": list(software)})
    return request.model_copy(update={"inputs": inputs})


class Check:
    def __init__(
        self,
        maven: Registry | None = None,
        npm: Registry | None = None,
        services: Services | None = None,
        github: FakeSource | None = None,
    ) -> None:
        self.clock = FakeClock()
        registries = {}
        if maven:
            registries["maven"] = maven
        if npm:
            registries["npm"] = npm
        self.services = services
        advisories: AdvisoryReader | None = services.reader(self.clock) if services else None
        self.checker = VersionChecker(
            github or FakeSource(["1.2.16", "1.2.14"]),
            TemplateSummarizer(),
            sleep=self.clock.sleep,
            registries=registries,
            advisories=advisories,
        )

    def run(self, *software: SoftwareToCheck) -> TaskFinished | TaskFailed:
        log = EventLog(self.clock, lambda event: None)
        result = run_task(request_for(*software), FixedPlanner(), self.checker, log)
        assert isinstance(result, TaskFinished | TaskFailed)
        return result


def room_texts(events: Sequence[object]) -> list[str]:
    return [e.data.text for e in events if isinstance(e, AgentMessageEvent)]


def test_a_maven_package_behind_with_a_critical_flaw_gets_an_urgent_ticket_with_the_evidence():
    services = Services(LOG4SHELL, {"CVE-2021-44228": nvd_answer(10.0, "CRITICAL")})
    result = Check(maven=Registry({LOG4J: LOG4J_VERSIONS}), services=services).run(log4j())
    assert isinstance(result, TaskFinished)
    found = result.output.findings[0]
    assert (found.state, found.newest, found.new_versions) == (
        "behind",
        "2.24.3",
        ["2.24.3", "2.17.1"],
    )
    assert found.vulnerability_check == "checked"
    assert [v.id for v in found.vulnerabilities] == ["CVE-2021-44228"]
    [ticket] = result.output.proposed
    assert ticket.fields["title"] == "Urgent: Upgrade Log4j from 2.14.1 to 2.24.3"
    body = ticket.fields["body"]
    assert body.startswith(f"Log4j has 2 new releases on Maven Central ({LOG4J}) newer than")
    assert (
        "- CVE-2021-44228 (critical, CVSS 10, reported by OSV and NVD). Log4Shell Fixed in "
        "2.15.0. https://nvd.nist.gov/vuln/detail/CVE-2021-44228" in body
    )
    assert ticket.reason.endswith("which has a critical known vulnerability")
    assert "Log4j 2.14.1 has 1 known vulnerability, 1 critical." in result.output.summary
    texts = room_texts(result.events)
    assert any("The worst is CVE-2021-44228 (critical, CVSS 10)" in t for t in texts)


def test_a_flaw_below_critical_leaves_the_ticket_as_it_was_but_lists_the_flaw():
    services = Services(
        [osv_record("GHSA-1", ["CVE-2024-0001"], "HIGH")],
        {"CVE-2024-0001": nvd_answer(7.5, "HIGH")},
    )
    result = Check(maven=Registry({LOG4J: LOG4J_VERSIONS}), services=services).run(log4j())
    assert isinstance(result, TaskFinished)
    [ticket] = result.output.proposed
    assert ticket.fields["title"] == "Upgrade Log4j from 2.14.1 to 2.24.3"
    assert "CVE-2024-0001 (high, CVSS 7.5" in ticket.fields["body"]


def test_an_npm_package_up_to_date_with_none_known_says_so():
    services = Services([])
    result = Check(npm=Registry({"express": ["4.21.2", "5.0.0-beta.3"]}), services=services).run(
        express()
    )
    assert isinstance(result, TaskFinished)
    found = result.output.findings[0]
    assert (found.state, found.vulnerability_check, found.vulnerabilities) == (
        "up_to_date",
        "checked",
        [],
    )
    assert result.output.proposed == []
    assert "OSV lists no known vulnerabilities in Express 4.21.2." in room_texts(result.events)


def test_a_github_source_and_a_version_only_the_first_check_read_are_never_looked_up():
    services = Services(LOG4SHELL)
    result = Check(maven=Registry({LOG4J: LOG4J_VERSIONS}), services=services).run(
        on_github(), log4j("2.14.1", from_first_check=True)
    )
    assert isinstance(result, TaskFinished)
    assert [f.vulnerability_check for f in result.output.findings] == ["not_checked", "not_checked"]
    assert services.osv_bodies == []


def test_osv_down_is_said_plainly_and_does_not_stop_the_version_check():
    services = Services([], osv_status=503)
    result = Check(maven=Registry({LOG4J: LOG4J_VERSIONS}), services=services).run(log4j())
    assert isinstance(result, TaskFinished)
    found = result.output.findings[0]
    assert (found.state, found.vulnerability_check) == ("behind", "could_not_check")
    assert "Vulnerabilities could not be looked up for Log4j." in result.output.summary
    assert any("This does not mean it has none." in t for t in room_texts(result.events))


def test_a_registry_outage_is_retried_and_named_as_that_registry():
    check = Check(maven=Registry({}, down=503))
    result = check.run(log4j())
    assert isinstance(result, TaskFailed)
    assert result.error.message == (
        "Could not check Log4j: Maven Central returned 503 Service Unavailable three times"
    )
    assert (
        "Maven Central answered 503 Service Unavailable (try 1 of 3). "
        "Waiting 2 s before trying again." in room_texts(result.events)
    )


def test_an_unknown_package_names_the_registry_that_refused():
    result = Check(npm=Registry({}, refused=404)).run(express(), on_github())
    assert isinstance(result, TaskFinished)
    unknown = result.output.findings[0]
    assert unknown.state == "cant_check"
    assert unknown.detail == "npm answered 404 Not Found."
    # The not_found flag is GitHub's, for a moved repository, so a registry never sets it.
    assert not unknown.not_found


def test_a_kind_with_no_reader_set_up_cannot_be_checked():
    result = Check().run(log4j(), on_github())
    assert isinstance(result, TaskFinished)
    assert result.output.findings[0].detail == (
        "This runtime has no reader for Maven Central set up."
    )


@pytest.mark.parametrize(
    ("source", "ref"),
    [
        (MavenSource, "org..evil:x"),
        (MavenSource, "no-artifact"),
        (MavenSource, "org.example:.hidden"),
        (NpmSource, "../etc"),
        (NpmSource, "UPPER"),
        (NpmSource, "@scope/"),
    ],
)
def test_a_package_name_a_registry_would_not_hold_is_refused_at_the_door(
    source: type[MavenSource] | type[NpmSource], ref: str
):
    with pytest.raises(ValidationError):
        source(ref=ref)
