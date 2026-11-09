import httpx
import pytest

from agent_runtime.registries import MavenCentralSource, NpmRegistrySource, maven_path
from agent_runtime.release_source import SourceRejected, SourceUnavailable

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
