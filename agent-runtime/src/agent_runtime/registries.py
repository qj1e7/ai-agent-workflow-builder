"""Readers for the package registries a team installs from (ADR 0025).

Each reader answers the same way as the GitHub one: the versions as releases, a SourceRejected
for an answer that will not change if asked again (a 4xx), and a SourceUnavailable for one that
might (a 5xx, no answer, or an answer in a shape we do not know). Both only read, so neither
needs an approval.
"""

import json
import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from agent_runtime.capped import MEGABYTE, TooLarge, read_capped
from agent_runtime.release_source import Release, SourceRejected, SourceUnavailable

DEFAULT_MAVEN_BASE = "https://repo1.maven.org/maven2"
DEFAULT_NPM_BASE = "https://registry.npmjs.org"
TIMEOUT_SECONDS = 10.0
USER_AGENT = "ai-workflow-builder-version-checker"
LIMITED_STATUS = 429
# The npm document for a busy package runs to a few megabytes. Anything far past that is not
# an answer we should parse, and reading stops there (capped.py).
MAX_BODY_BYTES = 32 * MEGABYTE
# The abbreviated document npm serves to installers: versions and dist-tags, without readmes.
NPM_ABBREVIATED = "application/vnd.npm.install-v1+json"


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=TIMEOUT_SECONDS)


def _get(client: httpx.Client, url: str, headers: Mapping[str, str]) -> bytes:
    """One registry answer. A redirect is refused like any other 3xx: the address is fixed."""
    try:
        status, body = read_capped(
            client,
            "GET",
            url,
            limit=MAX_BODY_BYTES,
            headers={"User-Agent": USER_AGENT, **headers},
        )
    except httpx.TransportError as error:
        raise SourceUnavailable(None) from error
    except TooLarge as error:
        raise SourceUnavailable(None) from error
    if status >= 500:
        raise SourceUnavailable(status)
    if status == LIMITED_STATUS:
        raise SourceRejected(status, limited=True)
    if status >= 300:
        raise SourceRejected(status)
    return body


PACKAGE_VERSION = re.compile(r"(\d+\.\d+\.\d+)(\.Final|\.RELEASE|\.GA|-jre|-android)?", re.ASCII)
"""A package version a team can run: three numbers, and at most one qualifier that marks a
final build, not a prerelease. .Final (Netty, Hibernate), .RELEASE (older Spring) and .GA only
say it is final. -jre and -android are Guava's two builds of the same release. platform-api
holds the same rule as PACKAGE_VERSION_PATTERN."""
BUILDS: tuple[str, ...] = ("", "-jre", "-android")
"""The builds a package version can be. The first that a package has is the one watched when no
version was given, so Guava is watched as -jre, its build for servers."""


def build_of(version: str) -> str | None:
    """The build a package version is, or None when it is not a package version. .Final, .RELEASE
    and .GA are the plain build, so 5.3.39.RELEASE and 6.2.0 compare with each other."""
    found = PACKAGE_VERSION.fullmatch(version)
    if found is None:
        return None
    qualifier = found[2] or ""
    return qualifier if qualifier in BUILDS else ""


def package_candidates(releases: list[Release], our_version: str | None) -> list[str]:
    """The versions a package check compares: final versions of the build the team runs, or of
    the first build in BUILDS the package has when no version was given."""
    builds = {r.tag: build_of(r.tag) for r in releases if not r.prerelease}
    ours = None if our_version is None else build_of(our_version)
    present = set(builds.values())
    wanted = ours if ours is not None else next((b for b in BUILDS if b in present), "")
    return [tag for tag, build in builds.items() if build == wanted]


def _prerelease(version: str) -> bool:
    """A version with a qualifier, such as 2.0.0-beta1, 3.1.0-SNAPSHOT or 1.0.0-rc.1. A qualifier
    that marks a final build, as 33.3.1-jre or 4.1.115.Final, is not one."""
    if build_of(version) is not None:
        return False
    return "-" in version or version.upper().endswith("SNAPSHOT")


def maven_path(coordinate: str) -> str:
    """org.apache.logging.log4j:log4j-core is at org/apache/logging/log4j/log4j-core."""
    group, sep, artifact = coordinate.partition(":")
    parts = group.split(".")
    if not sep or not artifact or artifact.startswith(".") or "" in parts:
        raise SourceRejected(400)
    return "/".join(quote(part, safe="") for part in [*parts, artifact])


class MavenCentralSource:
    """Reads maven-metadata.xml, the registry's own list of every version it holds."""

    name = "Maven Central"

    def __init__(self, base_url: str = DEFAULT_MAVEN_BASE, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = _client(client)

    def fetch(self, repo: str) -> list[Release]:
        url = f"{self._base_url}/{maven_path(repo)}/maven-metadata.xml"
        body = _get(self._client, url, {"Accept": "application/xml"})
        return [Release(tag=v, prerelease=_prerelease(v)) for v in _maven_versions(body)]


def _maven_versions(body: bytes) -> list[str]:
    # A document type could declare entities. The registry never sends one, so one means the
    # answer is not the registry's, and nothing in it is read.
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise SourceUnavailable(None)
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise SourceUnavailable(None) from error
    found = [(v.text or "").strip() for v in root.iterfind("./versioning/versions/version")]
    return [version for version in found if version]


class NpmRegistrySource:
    """Reads the package's abbreviated document from the npm registry."""

    name = "npm"

    def __init__(self, base_url: str = DEFAULT_NPM_BASE, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = _client(client)

    def fetch(self, repo: str) -> list[Release]:
        # A scoped name keeps its @ and sends its slash encoded, as @angular%2Fcore.
        url = f"{self._base_url}/{quote(repo, safe='@')}"
        body = _get(self._client, url, {"Accept": NPM_ABBREVIATED})
        return [Release(tag=v, prerelease=_prerelease(v)) for v in _npm_versions(body)]


def _npm_versions(body: bytes) -> list[str]:
    try:
        document: object = json.loads(body)
    except ValueError as error:
        raise SourceUnavailable(None) from error
    if not isinstance(document, dict):
        raise SourceUnavailable(None)
    versions = cast(dict[str, object], document).get("versions")
    if not isinstance(versions, dict):
        raise SourceUnavailable(None)
    return [str(version) for version in cast(dict[object, object], versions)]
