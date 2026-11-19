import httpx
import pytest

from agent_runtime.registries import (
    MavenCentralSource,
    NpmRegistrySource,
    build_of,
    maven_path,
    package_candidates,
)
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable
from agent_runtime.tags import highest, newer_than

LOG4J = "org.apache.logging.log4j:log4j-core"
METADATA = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>org.apache.logging.log4j</groupId>
  <artifactId>log4j-core</artifactId>
  <versioning>
    <latest>2.25.0-beta1</latest>
    <release>2.24.3</release>
    <versions>
      <version>2.14.1</version>
      <version>2.17.1</version>
      <version>2.24.3</version>
      <version>2.25.0-beta1</version>
    </versions>
  </versioning>
</metadata>"""


def answering(status: int, body: bytes, seen: list[httpx.Request] | None = None) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_maven_reads_every_version_from_the_registry_metadata():
    seen: list[httpx.Request] = []
    source = MavenCentralSource("https://maven.test/maven2", client=answering(200, METADATA, seen))
    releases = source.fetch(LOG4J)
    assert [r.tag for r in releases] == ["2.14.1", "2.17.1", "2.24.3", "2.25.0-beta1"]
    assert [r.prerelease for r in releases] == [False, False, False, True]
    assert str(seen[0].url) == (
        "https://maven.test/maven2/org/apache/logging/log4j/log4j-core/maven-metadata.xml"
    )


@pytest.mark.parametrize("coordinate", ["org..evil:x", "org.x", "org:", "org:.hidden", ":art"])
def test_a_coordinate_that_would_leave_its_folder_is_refused(coordinate: str):
    with pytest.raises(SourceRejected) as refused:
        maven_path(coordinate)
    assert refused.value.status == 400


def test_a_metadata_file_with_a_document_type_is_not_read():
    body = b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x "y">]><metadata/>'
    source = MavenCentralSource(client=answering(200, body))
    with pytest.raises(SourceUnavailable):
        source.fetch(LOG4J)


def test_an_unknown_package_is_a_refusal_and_an_outage_can_be_retried():
    with pytest.raises(SourceRejected) as refused:
        MavenCentralSource(client=answering(404, b"")).fetch(LOG4J)
    assert refused.value.status == 404 and not refused.value.limited
    with pytest.raises(SourceUnavailable) as down:
        MavenCentralSource(client=answering(503, b"")).fetch(LOG4J)
    assert down.value.status == 503


def test_npm_asks_for_the_short_document_and_keeps_the_scope_in_the_address():
    seen: list[httpx.Request] = []
    body = b'{"name":"@angular/core","versions":{"18.2.0":{},"19.0.0-rc.1":{},"19.0.0":{}}}'
    source = NpmRegistrySource("https://npm.test", client=answering(200, body, seen))
    releases = source.fetch("@angular/core")
    assert [(r.tag, r.prerelease) for r in releases] == [
        ("18.2.0", False),
        ("19.0.0-rc.1", True),
        ("19.0.0", False),
    ]
    assert seen[0].url.raw_path == b"/@angular%2Fcore"
    assert seen[0].headers["Accept"] == "application/vnd.npm.install-v1+json"


def test_npm_saying_slow_down_is_marked_as_limited():
    with pytest.raises(SourceRejected) as refused:
        NpmRegistrySource(client=answering(429, b"")).fetch("express")
    assert refused.value.limited


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"versions": []}'])
def test_npm_answering_in_another_shape_is_not_trusted(body: bytes):
    with pytest.raises(SourceUnavailable):
        NpmRegistrySource(client=answering(200, body)).fetch("express")


@pytest.mark.parametrize(
    ("version", "build"),
    [
        ("2.24.3", ""),
        ("4.1.115.Final", ""),
        ("5.3.39.RELEASE", ""),
        ("1.0.0.GA", ""),
        ("33.3.1-jre", "-jre"),
        ("33.3.1-android", "-android"),
        ("2.25.0-beta1", None),
        ("3.1.0-SNAPSHOT", None),
        ("4.1.115.final", None),
        ("2.24", None),
    ],
)
def test_a_package_version_is_three_numbers_and_at_most_a_final_qualifier(
    version: str, build: str | None
):
    assert build_of(version) == build


def test_guava_and_netty_versions_are_final_releases_not_prereleases():
    body = METADATA.replace(b"2.25.0-beta1", b"33.3.1-jre").replace(b"2.14.1", b"4.1.115.Final")
    releases = MavenCentralSource(client=answering(200, body)).fetch(LOG4J)
    assert {r.tag: r.prerelease for r in releases} == {
        "4.1.115.Final": False,
        "2.17.1": False,
        "2.24.3": False,
        "33.3.1-jre": False,
    }


GUAVA = [Release(tag=v) for v in ("33.2.0-jre", "33.2.0-android", "33.3.1-jre", "33.3.1-android")]


@pytest.mark.parametrize(
    ("ours", "counted"),
    [
        ("33.2.0-jre", ["33.2.0-jre", "33.3.1-jre"]),
        ("33.2.0-android", ["33.2.0-android", "33.3.1-android"]),
        (None, ["33.2.0-jre", "33.3.1-jre"]),
    ],
)
def test_a_guava_check_compares_only_the_build_the_team_runs(ours: str | None, counted: list[str]):
    assert package_candidates(GUAVA, ours) == counted


def test_a_final_marker_compares_as_its_numbers():
    """Spring went from 5.3.39.RELEASE to 6.2.0, so the plain numbers count for both."""
    spring = [Release(tag=v) for v in ("5.3.39.RELEASE", "6.2.0", "6.2.1-RC1")]
    counted = package_candidates(spring, "5.3.39.RELEASE")
    assert counted == ["5.3.39.RELEASE", "6.2.0"]
    assert highest(counted) == "6.2.0"
    assert newer_than("5.3.39.RELEASE", counted, any_family=True) == ["6.2.0"]
    netty = ["4.1.114.Final", "4.1.115.Final", "4.2.0.Final"]
    assert newer_than("4.1.114.Final", netty, any_family=True) == ["4.2.0.Final", "4.1.115.Final"]
