import re
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from agent_runtime.contract import (
    FindSoftwareResult,
    FoundSoftware,
    SoftwareMatch,
    SoftwareNotChecked,
    SoftwareNotKnown,
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
)

MAX_MATCHES = 5


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def known_for(name: str) -> list[KnownProject]:
    wanted = normal(name)
    if not wanted:
        return []
    return [project for project in KNOWN_PROJECTS if wanted in project.names][:MAX_MATCHES]


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


class SoftwareFinder:
    def __init__(self, source: ProjectSource) -> None:
        self._source = source

    def find(self, name: str, tag_pattern: str) -> FindSoftwareResult:
        name = name.strip()
        guesses = known_for(name)
        if not guesses:
            return SoftwareNotKnown(
                message=f"I don't know a GitHub project called {name}. "
                "Type the GitHub address instead, as owner/name."
            )
        matches: list[SoftwareMatch] = []
        not_found: list[str] = []
        for guess in guesses:
            try:
                matches.append(check_project(self._source, guess, tag_pattern))
            except SourceRejected as refused:
                if refused.status not in NOT_FOUND_STATUSES:
                    return _not_checked(name, refused)
                not_found.append(guess.repo)
            except SourceUnavailable as unavailable:
                return _not_checked(name, unavailable)
        if not matches:
            return SoftwareNotKnown(
                message=f"GitHub didn't find {tag_list(not_found)}, which our list has for "
                f"{name}. Type the GitHub address instead, as owner/name."
            )
        return FoundSoftware(matches=matches)


class Trouble(NamedTuple):
    what_happened: str
    next_step: str


def _not_checked(name: str, error: SourceRejected | SourceUnavailable) -> SoftwareNotChecked:
    trouble = _trouble(error)
    message = f"{trouble.what_happened}, so I can't check {name} yet. {trouble.next_step}"
    return SoftwareNotChecked(message=message.strip())


def _trouble(error: SourceRejected | SourceUnavailable) -> Trouble:
    later = "Try again later."
    limited = Trouble("GitHub is limiting how often we can ask it", later)
    if isinstance(error, SourceRejected):
        if error.status == 401:
            return Trouble(
                "GitHub did not accept the key in the GitHub connection",
                "Ask whoever looks after the platform to check that connection.",
            )
        if error.limited:
            return limited
        return Trouble(f"GitHub answered {phrase(error.status)}", "")
    if error.status == 429:
        return limited
    if error.status is None:
        return Trouble("I couldn't reach GitHub", later)
    return Trouble(f"GitHub answered {phrase(error.status)}", later)
