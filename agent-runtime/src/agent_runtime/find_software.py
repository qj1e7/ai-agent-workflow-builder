import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from agent_runtime.contract import (
    SOURCE_NAMES,
    FindSoftwareResult,
    FoundSoftware,
    SoftwareMatch,
    SoftwareNotChecked,
    SoftwareNotKnown,
    SourceKind,
)
from agent_runtime.release_source import (
    ReleaseSource,
    SourceRejected,
    SourceUnavailable,
    candidates,
    phrase,
    tag_list,
)
from agent_runtime.tags import highest

NOT_FOUND_STATUSES = {404, 410}


class ProjectSource(ReleaseSource, Protocol):
    def current_name(self, repo: str) -> str: ...


@dataclass(frozen=True)
class KnownProject:
    repo: str
    what: str
    names: tuple[str, ...]
    kind: SourceKind = "github"
    """Where it is published. A package is read from its registry, a project from GitHub."""


# A name is never turned into a project by a model (ADR 0037).
KNOWN_PROJECTS = (
    KnownProject("kubernetes/kubernetes", "Kubernetes itself", ("kubernetes", "k8s")),
    KnownProject(
        "react/react",
        "React, a JavaScript library for building web pages",
        ("react", "reactjs", "react js"),
    ),
    KnownProject(
        "langchain-ai/langgraph",
        "LangGraph, a Python library for building AI agents",
        ("langgraph",),
    ),
    KnownProject(
        "langchain-ai/langchain",
        "LangChain, a Python library for building on AI models",
        ("langchain",),
    ),
    KnownProject("n8n-io/n8n", "n8n, a tool that connects apps and automates steps", ("n8n",)),
    KnownProject(
        "nodejs/node",
        "Node.js, which runs JavaScript outside the browser",
        ("node", "nodejs", "node js"),
    ),
    KnownProject("python/cpython", "Python, the programming language", ("python", "cpython")),
    KnownProject("postgres/postgres", "PostgreSQL, the database", ("postgres", "postgresql")),
    KnownProject("hashicorp/terraform", "Terraform itself, from HashiCorp", ("terraform",)),
    KnownProject(
        "opentofu/opentofu",
        "OpenTofu, an open-source fork of Terraform",
        ("opentofu", "open tofu", "terraform"),
    ),
    KnownProject(
        "moby/moby", "Moby, the open-source project behind Docker Engine", ("docker engine", "moby")
    ),
    KnownProject(
        "docker/compose",
        "Docker Compose, which runs apps made of several containers",
        ("docker compose", "compose"),
    ),
    KnownProject("grafana/grafana", "Grafana, for dashboards of monitoring data", ("grafana",)),
    KnownProject(
        "prometheus/prometheus", "Prometheus, which collects monitoring data", ("prometheus",)
    ),
    KnownProject("redis/redis", "Redis, an in-memory data store", ("redis",)),
    KnownProject("elastic/elasticsearch", "Elasticsearch, a search engine", ("elasticsearch",)),
    KnownProject(
        "microsoft/vscode",
        "Visual Studio Code, the code editor",
        ("vs code", "vscode", "visual studio code"),
    ),
    KnownProject(
        "vuejs/core",
        "Vue, a JavaScript framework for building web pages",
        ("vue", "vuejs", "vue js"),
    ),
    KnownProject("angular/angular", "Angular, a framework for building web apps", ("angular",)),
    # Libraries a team installs from Maven Central or npm (ADR 0025). Reviewed like the projects:
    # each is the package its own project page names.
    KnownProject(
        "org.apache.logging.log4j:log4j-core",
        "Log4j core, the Java logging library from Apache",
        ("log4j", "log4j core", "log4j2", "apache log4j"),
        "maven",
    ),
    KnownProject(
        "org.springframework:spring-core",
        "Spring Framework's core, for Java applications",
        ("spring", "spring framework", "spring core"),
        "maven",
    ),
    KnownProject(
        "com.fasterxml.jackson.core:jackson-databind",
        "Jackson databind, which reads and writes JSON in Java",
        ("jackson", "jackson databind"),
        "maven",
    ),
    KnownProject(
        "com.google.guava:guava", "Guava, Google's core libraries for Java", ("guava",), "maven"
    ),
    KnownProject(
        "express", "Express, a web framework for Node.js", ("express", "expressjs"), "npm"
    ),
    KnownProject("lodash", "Lodash, JavaScript utility functions", ("lodash",), "npm"),
    KnownProject("axios", "Axios, an HTTP client for JavaScript", ("axios",), "npm"),
)

MAX_MATCHES = 5


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def known_for(name: str) -> list[KnownProject]:
    wanted = normal(name)
    if not wanted:
        return []
    return [project for project in KNOWN_PROJECTS if wanted in project.names][:MAX_MATCHES]


def check_package(
    registry: ReleaseSource, project: KnownProject, tag_pattern: str
) -> SoftwareMatch:
    newest = highest(candidates(registry.fetch(project.repo), tag_pattern))
    return SoftwareMatch(
        kind=project.kind,
        repo=project.repo,
        what=project.what,
        why="From our list of known packages. Your team installs it from "
        f"{SOURCE_NAMES[project.kind]}.",
        releases="none" if newest is None else "published",
        newest=newest,
    )


def check_project(source: ProjectSource, project: KnownProject, tag_pattern: str) -> SoftwareMatch:
    current = source.current_name(project.repo)
    counted = candidates(source.fetch(current), tag_pattern)
    newest = highest(counted)
    why = "From our list of known projects."
    if current != project.repo:
        why = f"From our list of known projects, as {project.repo}. GitHub now has it at {current}."
    return SoftwareMatch(
        repo=current,
        what=project.what,
        why=why,
        releases="none" if newest is None else "published",
        newest=newest,
    )


TYPE_IT = "Choose where it's published and type its name there."


class SoftwareFinder:
    def __init__(
        self, source: ProjectSource, registries: Mapping[str, ReleaseSource] | None = None
    ) -> None:
        """source reads GitHub. registries reads Maven Central and npm by kind. A known package
        whose registry is not set up here is left out, never offered unchecked."""
        self._source = source
        self._registries = dict(registries or {})

    def _check(self, guess: KnownProject, tag_pattern: str) -> SoftwareMatch | None:
        if guess.kind == "github":
            return check_project(self._source, guess, tag_pattern)
        registry = self._registries.get(guess.kind)
        return None if registry is None else check_package(registry, guess, tag_pattern)

    def find(self, name: str, tag_pattern: str) -> FindSoftwareResult:
        name = name.strip()
        guesses = known_for(name)
        unknown = SoftwareNotKnown(message=f"I don't know software called {name}. {TYPE_IT}")
        if not guesses:
            return unknown
        matches: list[SoftwareMatch] = []
        not_found: list[str] = []
        for guess in guesses:
            where = SOURCE_NAMES[guess.kind]
            try:
                found = self._check(guess, tag_pattern)
            except SourceRejected as refused:
                if refused.status not in NOT_FOUND_STATUSES:
                    return _not_checked(name, refused, where)
                not_found.append(f"{guess.repo} on {where}")
                continue
            except SourceUnavailable as unavailable:
                return _not_checked(name, unavailable, where)
            if found is not None:
                matches.append(found)
        if not matches:
            if not not_found:
                return unknown
            return SoftwareNotKnown(
                message=f"I couldn't find {tag_list(not_found)}, which our list has for "
                f"{name}. {TYPE_IT}"
            )
        return FoundSoftware(matches=matches)


class Trouble(NamedTuple):
    what_happened: str
    next_step: str


def _not_checked(
    name: str, error: SourceRejected | SourceUnavailable, where: str = "GitHub"
) -> SoftwareNotChecked:
    trouble = _trouble(error, where)
    message = f"{trouble.what_happened}, so I can't check {name} yet. {trouble.next_step}"
    return SoftwareNotChecked(message=message.strip())


def _trouble(error: SourceRejected | SourceUnavailable, where: str = "GitHub") -> Trouble:
    later = "Try again later."
    limited = Trouble(f"{where} is limiting how often we can ask it", later)
    if isinstance(error, SourceRejected):
        if error.status == 401 and where == "GitHub":
            return Trouble(
                "GitHub did not accept the key in the GitHub connection",
                "Ask whoever looks after the platform to check that connection.",
            )
        if error.limited:
            return limited
        return Trouble(f"{where} answered {phrase(error.status)}", "")
    if error.status == 429:
        return limited
    if error.status is None:
        return Trouble(f"I couldn't reach {where}", later)
    return Trouble(f"{where} answered {phrase(error.status)}", later)
