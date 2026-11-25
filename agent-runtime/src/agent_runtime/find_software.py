import re
import string
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple, Protocol

from pydantic import ValidationError

from agent_runtime.contract import (
    SOURCE_NAMES,
    FindSoftwareResult,
    FoundSoftware,
    GithubSource,
    SoftwareMatch,
    SoftwareNotChecked,
    SoftwareNotKnown,
    SourceKind,
)
from agent_runtime.registries import package_candidates
from agent_runtime.release_source import (
    FoundRepo,
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

    def search(self, words: str, limit: int) -> list[FoundRepo]: ...


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
    KnownProject(
        "fastapi/fastapi", "FastAPI, a Python framework for building APIs", ("fastapi", "fast api")
    ),
    KnownProject("django/django", "Django, a Python web framework", ("django",)),
    KnownProject("pallets/flask", "Flask, a small Python web framework", ("flask",)),
    KnownProject("pydantic/pydantic", "Pydantic, which checks data in Python", ("pydantic",)),
    KnownProject(
        "vercel/next.js",
        "Next.js, a React framework for building web apps",
        ("next js", "nextjs"),
    ),
    KnownProject("microsoft/TypeScript", "TypeScript, JavaScript with types", ("typescript",)),
    KnownProject("helm/helm", "Helm, which installs apps on Kubernetes", ("helm",)),
    KnownProject(
        "argoproj/argo-cd",
        "Argo CD, which deploys apps to Kubernetes from Git",
        ("argo cd", "argocd"),
    ),
    KnownProject("keycloak/keycloak", "Keycloak, for sign-in and user access", ("keycloak",)),
    KnownProject(
        "ansible/ansible",
        "ansible-core, the base of Ansible, which automates setting up servers",
        ("ansible", "ansible core"),
    ),
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
MAX_NAME_LENGTH: Final = 80
"""The longest name a request may give (FindSoftwareRequest). A longer one is not read at all."""

SEARCH_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + " .-_+#")
"""The only characters a name may hold to be searched. Any other, as a colon, a quote or a letter
outside ASCII, could carry a GitHub search qualifier, and no software name we search needs it."""
MAX_SEARCH_LENGTH: Final = 50
MAX_SEARCH_WORDS: Final = 4
SEARCH_HITS: Final = 5
"""How many of GitHub's best matches are checked. Each one costs one more read of GitHub."""
MAX_SEARCH_MATCHES: Final = 3
WHAT_LENGTH: Final = 120
NO_DESCRIPTION: Final = "No description on GitHub"
_WORD: Final = re.compile(r"[a-z0-9]+")


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def known_for(name: str) -> list[KnownProject]:
    wanted = normal(name)
    if not wanted:
        return []
    return [project for project in KNOWN_PROJECTS if wanted in project.names][:MAX_MATCHES]


def search_words(name: str) -> str | None:
    """The plain words GitHub's search is asked for, or None when the name is not searched. The
    length is checked before anything else reads the name, and the one pattern is a single
    character class, so no name can make it slow. Lowercase words hold no qualifier and no
    operator, so the name is only ever data in the query."""
    name = name.strip()
    if not name or len(name) > MAX_SEARCH_LENGTH or not SEARCH_CHARACTERS.issuperset(name):
        return None
    words = _WORD.findall(name.lower())
    if not words or len(words) > MAX_SEARCH_WORDS:
        return None
    return " ".join(words)


def check_package(registry: ReleaseSource, project: KnownProject) -> SoftwareMatch:
    """A package's versions follow its registry's rule, not the GitHub tag pattern (ADR 0025)."""
    newest = highest(package_candidates(registry.fetch(project.repo), None))
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
    """Finds where a software's plain name is published, never through a model. The reviewed
    list comes first. Only a name it lacks is searched on GitHub, and a search match is only ever
    a choice for the person (ADR 0025)."""

    def __init__(
        self, source: ProjectSource, registries: Mapping[str, ReleaseSource] | None = None
    ) -> None:
        """source reads and searches GitHub, through the platform's GitHub connection. registries
        reads Maven Central and npm by kind. A known package whose registry is not set up here is
        left out, never offered unchecked."""
        self._source = source
        self._registries = dict(registries or {})

    def _check(self, guess: KnownProject, tag_pattern: str) -> SoftwareMatch | None:
        if guess.kind == "github":
            return check_project(self._source, guess, tag_pattern)
        registry = self._registries.get(guess.kind)
        return None if registry is None else check_package(registry, guess)

    def find(self, name: str, tag_pattern: str) -> FindSoftwareResult:
        if len(name) > MAX_NAME_LENGTH:
            return SoftwareNotKnown(message=f"That name is too long to look up. {TYPE_IT}")
        name = name.strip()
        guesses = known_for(name)
        unknown = SoftwareNotKnown(message=f"I don't know software called {name}. {TYPE_IT}")
        if not guesses:
            words = search_words(name)
            return unknown if words is None else self._search(name, words, tag_pattern)
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

    def _search(self, name: str, words: str, tag_pattern: str) -> FindSoftwareResult:
        """GitHub's best matches, in its order, each read under the tag rule. Only a project whose
        releases the rule counts is offered, at most MAX_SEARCH_MATCHES of them."""
        try:
            hits = self._source.search(words, SEARCH_HITS)
        except SourceRejected as refused:
            if refused.status == 422:
                return SoftwareNotChecked(message=f"GitHub couldn't search for {name}. {TYPE_IT}")
            return _search_trouble(name, refused)
        except SourceUnavailable as unavailable:
            return _search_trouble(name, unavailable)
        matches: list[SoftwareMatch] = []
        for hit in hits:
            if len(matches) == MAX_SEARCH_MATCHES:
                break
            if not _a_repo(hit.repo):
                continue
            try:
                newest = highest(candidates(self._source.fetch(hit.repo), tag_pattern))
            except SourceRejected as refused:
                # Only a limit ends the search. A hit GitHub won't show, as one gone (404) or held
                # back (451, or a 403 that is no limit), is left out.
                if refused.limited:
                    return _search_trouble(name, refused)
                continue
            except SourceUnavailable as unavailable:
                return _search_trouble(name, unavailable)
            if newest is not None:
                matches.append(_searched(hit, newest))
        if not matches:
            message = f"I couldn't find {name} on our list or by searching GitHub. {TYPE_IT}"
            return SoftwareNotKnown(message=message)
        return FoundSoftware(matches=matches)


def _a_repo(repo: str) -> bool:
    try:
        GithubSource(ref=repo)
    except ValidationError:
        return False
    return True


def _searched(hit: FoundRepo, newest: str) -> SoftwareMatch:
    stars = f"{hit.stars:,} {'star' if hit.stars == 1 else 'stars'}"
    return SoftwareMatch(
        repo=hit.repo,
        what=_plain(hit.description) or NO_DESCRIPTION,
        why=f"Found by searching GitHub, so make sure it's the one you mean. It has {stars}.",
        releases="published",
        newest=newest,
        found_by="github_search",
        stars=hit.stars,
    )


def _plain(text: str | None) -> str:
    """GitHub's description as one plain line of data: no control character, single spaces, no
    full stop at the end, as the Portal adds its own, and at most WHAT_LENGTH characters."""
    if not text:
        return ""
    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    line = " ".join(printable.split()).rstrip(" .")
    if len(line) > WHAT_LENGTH:
        line = line[: WHAT_LENGTH - 1].rstrip() + "\u2026"
    return line


def _search_trouble(name: str, error: SourceRejected | SourceUnavailable) -> SoftwareNotChecked:
    limited = error.limited if isinstance(error, SourceRejected) else error.status == 429
    if not limited:
        return _not_checked(name, error)
    return SoftwareNotChecked(
        message=f"GitHub search is busy just now, so I couldn't look up {name}. "
        "Type its repository as owner/name instead, or try again later."
    )


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
