import re
from dataclasses import dataclass

from agent_runtime.contract import (
    FindSoftwareResult,
    FoundSoftware,
    SoftwareMatch,
    SoftwareNotChecked,
    SoftwareNotKnown,
)
from agent_runtime.release_source import ReleaseSource, SourceRejected, SourceUnavailable

GONE_STATUSES = {404, 410}


@dataclass(frozen=True)
class KnownProject:
    repo: str
    names: tuple[str, ...]


# Reviewed by hand. A name is never turned into a project by a model (ADR 0037).
KNOWN_PROJECTS = (
    KnownProject("kubernetes/kubernetes", ("kubernetes", "k8s")),
    KnownProject("facebook/react", ("react", "reactjs", "react js")),
    KnownProject("langchain-ai/langgraph", ("langgraph",)),
    KnownProject("langchain-ai/langchain", ("langchain",)),
    KnownProject("n8n-io/n8n", ("n8n",)),
    KnownProject("nodejs/node", ("node", "nodejs", "node js")),
    KnownProject("python/cpython", ("python", "cpython")),
    KnownProject("postgres/postgres", ("postgres", "postgresql")),
    KnownProject("hashicorp/terraform", ("terraform",)),
    KnownProject("opentofu/opentofu", ("opentofu", "open tofu", "terraform")),
    KnownProject("moby/moby", ("docker engine", "moby")),
    KnownProject("docker/compose", ("docker compose", "compose")),
    KnownProject("gitlab-org/gitlab", ("gitlab",)),
    KnownProject("grafana/grafana", ("grafana",)),
    KnownProject("prometheus/prometheus", ("prometheus",)),
    KnownProject("redis/redis", ("redis",)),
    KnownProject("elastic/elasticsearch", ("elasticsearch",)),
    KnownProject("microsoft/vscode", ("vs code", "vscode", "visual studio code")),
    KnownProject("vuejs/core", ("vue", "vuejs", "vue js")),
    KnownProject("angular/angular", ("angular",)),
)

MAX_MATCHES = 5


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def known_for(name: str) -> list[KnownProject]:
    wanted = normal(name)
    if not wanted:
        return []
    return [project for project in KNOWN_PROJECTS if wanted in project.names][:MAX_MATCHES]


class SoftwareFinder:
    def __init__(self, source: ReleaseSource) -> None:
        self._source = source

    def find(self, name: str) -> FindSoftwareResult:
        guesses = known_for(name)
        if not guesses:
            return SoftwareNotKnown(
                message=f"I don't know a GitHub project called {name.strip()}. "
                "Type the GitHub address instead, as owner/name."
            )
        matches: list[SoftwareMatch] = []
        for guess in guesses:
            try:
                releases = self._source.fetch(guess.repo)
            except SourceRejected as refused:
                if refused.status in GONE_STATUSES:
                    continue
                return _not_checked()
            except SourceUnavailable:
                return _not_checked()
            stable = [r.tag for r in releases if not (r.draft or r.prerelease)]
            matches.append(
                SoftwareMatch(
                    repo=guess.repo,
                    why=f"Our list of known projects says {name.strip()} is usually "
                    f"{guess.repo}. GitHub has it just now.",
                    releases="published" if stable else "none",
                    newest=stable[0] if stable else None,
                )
            )
        if not matches:
            return SoftwareNotKnown(
                message=f"GitHub no longer has the project I know as {name.strip()}. "
                "Type the GitHub address instead, as owner/name."
            )
        return FoundSoftware(matches=matches)


def _not_checked() -> SoftwareNotChecked:
    return SoftwareNotChecked(
        message="GitHub did not answer, so I can't check the project yet. Try again in a minute."
    )
