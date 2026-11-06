import os
import sys

from agent_runtime.api import DEFAULT_GITHUB_API_BASE
from agent_runtime.contract import RELEASE_TAG_PATTERN
from agent_runtime.find_software import KNOWN_PROJECTS, NOT_FOUND_STATUSES, check_project
from agent_runtime.github import GitHubReleaseSource
from agent_runtime.release_source import SourceRejected, SourceUnavailable, phrase


def main() -> int:
    source = GitHubReleaseSource(
        os.environ.get("GITHUB_API_BASE") or DEFAULT_GITHUB_API_BASE,
        token=os.environ.get("GITHUB_TOKEN") or None,
    )
    rows = [("On our list", "On GitHub now", "Newest the watch counts", "Verdict")]
    failed = 0
    for project in KNOWN_PROJECTS:
        try:
            match = check_project(source, project, RELEASE_TAG_PATTERN)
        except (SourceRejected, SourceUnavailable) as error:
            failed += 1
            rows.append((project.repo, "-", "-", _trouble(error)))
            continue
        verdict = "ok"
        if match.repo != project.repo:
            failed += 1
            verdict = f"change the list to {match.repo}"
        if match.releases == "none":
            verdict += ", no release the watch counts"
        rows.append((project.repo, match.repo, match.newest or "none", verdict))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    print(f"Tag rule: {RELEASE_TAG_PATTERN}")
    for row in rows:
        padded = (cell.ljust(width) for cell, width in zip(row[:3], widths, strict=True))
        print("  ".join([*padded, row[3]]))
    print(f"{len(KNOWN_PROJECTS)} projects, {failed} not ok.")
    return 1 if failed else 0


def _trouble(error: SourceRejected | SourceUnavailable) -> str:
    if isinstance(error, SourceRejected) and error.status in NOT_FOUND_STATUSES:
        return "GitHub didn't find it, so fix or drop the entry"
    if isinstance(error, SourceRejected) and error.limited:
        return "not checked: GitHub is limiting how often we can ask it"
    if error.status is None:
        return "not checked: GitHub could not be reached"
    return f"not checked: GitHub answered {phrase(error.status)}"


if __name__ == "__main__":
    sys.exit(main())
