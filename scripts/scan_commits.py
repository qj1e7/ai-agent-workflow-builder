"""Check every line added in a range of commits for anything shaped like a key.

GitHub keeps every commit of a pull request, even after a squash merge, and the repo is public. So
a key added in one commit and removed in a later one is still out there. CI's gitleaks scan of the
files can't see one, and gitleaks' default rules miss some shapes, such as an Atlassian API token.
This reads each added line of each commit in the range, a merge's own lines included, against the
agent runtime's key shapes (contracts/fixtures/agent/key-shapes.json). It is CI's main check of the
commits. gitleaks reads them too, as a second check.

It prints the commit, the file, the line, the shape's name and at most the first four letters of
what matched, never more, as the CI log is public. A shape that starts with letters of the key
itself shows fewer, or none.

A line with a gitleaks:allow comment, and an example URL with a password in n8n's catalogue, are
listed as allowed and don't fail the check. A password in a URL that starts with $, {, < or %, or
is shorter than 8 letters, is a placeholder or a test value, so it doesn't count.

It doesn't read binary files, which include UTF-16 text, a key split across lines, or commit
messages.

usage: uv run --no-project --python 3.14 scripts/scan_commits.py <base> <head>
       python3 -I scripts/scan_commits.py <base> <head>    with Python 3.11 or later

Exits 0 when nothing matched, or when <base> is empty or all zeros, as no range is known then.
Exits 1 on any match, and 2 when git can't read the range.
"""

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SHAPES_FILE = Path(__file__).resolve().parent.parent / "contracts/fixtures/agent/key-shapes.json"
NAMES = {
    r"sk-ant-[A-Za-z0-9_\-]{8,}": "Anthropic key",
    r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,}": "OpenAI project key",
    r"sk-lf-[0-9a-f\-]{36}": "Langfuse secret key",
    r"sk-or-v1-[0-9a-f]{64}": "OpenRouter key",
    r"(?=sk-)(?:(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})|(?<=[%=][0-9A-Fa-f]{2})|(?<![A-Za-z]))"
    r"sk-[A-Za-z0-9_\-]{16,}": "OpenAI key",
    r"[sr]k_(?:live|test)_[A-Za-z0-9]{20,}": "Stripe key",
    r"gh[pousr]_[A-Za-z0-9]{16,}": "GitHub token",
    r"github_pat_[A-Za-z0-9_]{16,}": "GitHub fine-grained token",
    r"gl(?:pat|rt|dt|ptt|soat)-[A-Za-z0-9_\-]{16,}": "GitLab token",
    r"(?:AKIA|ASIA)[0-9A-Z]{16}": "AWS access key id",
    r"xox[abcdeprs]-[A-Za-z0-9%\-]{10,}": "Slack token",
    r"xapp-[0-9]-[A-Za-z0-9\-]{10,}": "Slack app token",
    r"npm_[A-Za-z0-9]{36}": "npm token",
    r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}": "PyPI token",
    r"hf_[A-Za-z0-9]{34}": "Hugging Face token",
    r"sq[upa]_[0-9a-f]{40}": "SonarQube token",
    r"[A-Za-z0-9_~.]{3}\dQ~[A-Za-z0-9_~.\-]{31,34}": "Entra client secret",
    r"hooks\.slack\.com/(?:services|triggers|workflows)/[A-Za-z0-9_/\-]+": "Slack webhook",
    r"webhook\.office\.com/[A-Za-z0-9@_/\-]+": "Teams webhook",
    r"ATATT[A-Za-z0-9_=\-]{16,}": "Atlassian API token",
    r"AIza[A-Za-z0-9_\-]{35}": "Google API key",
    r"(?i:accountkey|sharedaccesskey)=[A-Za-z0-9+/=]{32,}": "Azure storage or Service Bus key",
    r"sig=[A-Za-z0-9%+/=_\-]{40,}": "Azure SAS signature",
    r"(?i:token|key|secret|password|pat|auth)\b\W{1,10}[0-9a-f]{40}\b": "40 hex after a key word",
    r":\\?/\\?/[^\s:/@]*:[^\s/@]+@": "password in a URL",
    r"(?:(?<=\\)(?![bfnrt]|u[0-9A-Fa-f]{4})|(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})"
    r"|(?<![A-Za-z0-9_\-\\]))"
    r"(?=[A-Za-z0-9_\-]*?eyJ)"
    r"[A-Za-z0-9_\-]++\.eyJ[A-Za-z0-9_\-]++\.[A-Za-z0-9_\-]+": "signed token",
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[^"\\-]|\\(?!")|-(?!----END))*+'
    r"(?:-----END [A-Z ]*PRIVATE KEY-----"
    r'|(?:(?:\\[nr]|[\s",+])++[A-Za-z0-9+/=]{16,}+(?!\\?"\s*:))*+)': "private key",
    r"(?i:bearer)\s+(?=[A-Za-z._~\-]*[0-9+/=]|[A-Za-z]{24})[A-Za-z0-9._~+/=\-]{8,}": "bearer token",
    r"(?i:basic)\s+(?=[A-Za-z]*[0-9+/=])[A-Za-z0-9+/=]{8,}": "basic auth header",
}
"""A name for each shape in key-shapes.json, for the report. A test fails when a shape has none."""
SHOWN = 4
"""Letters of a match shown in the report. Most shapes start with fixed letters this long."""
SHOWN_BY_SHAPE = {
    "Entra client secret": 0,
    "OpenAI key": 3,
    "Hugging Face token": 3,
    "password in a URL": 3,
}
"""Shapes whose fixed start is shorter, so a fourth letter, or any, would be part of the key."""
ALLOW_MARK = "gitleaks:allow"
"""A line that holds this is allowed, as gitleaks skips it, so one comment covers both scans."""
ALLOWED_SHAPES = frozenset({("contracts/n8n/catalogue.json", "password in a URL")})
"""The catalogue is written from n8n's public image by scripts/n8n-catalogue.sh, and pack smoke
fails when it differs from what n8n serves. n8n's help texts in it hold example URLs with a
password. Any other shape in it still fails."""
URL_PASSWORD = re.compile(r":\\?/\\?/[^\s:/@]*:(?P<password>[^\s/@]+)@")
"""The password in a match of the "password in a URL" shape."""
PLACEHOLDER_STARTS = ("$", "{", "<", "%")
"""A password in a URL that starts like this is a variable or a template, such as ${DB_PASSWORD}."""
SHORTEST_URL_PASSWORD = 8
"""A shorter password in a URL, such as postgres:test@, is a test value. The masker still hides it
in the product, so key-shapes.json keeps the shape whole."""
GIT_LOG = (
    "git",
    "-c",
    "core.quotePath=false",
    "-c",
    "log.showSignature=false",
    "log",
    "--format=commit %H",
    "--patch",
    "--cc",
    "--unified=0",
    "--find-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
)
"""Each commit's added lines and nothing around them. A merge shows only lines that differ from
every parent, which are the merge's own. A moved file shows only what changed in it."""
HUNK = re.compile(r"(@+) (?:-\S+ )+\+(\d+)")
NO_RANGE = frozenset({"", "0" * 40, "0" * 64})

Shapes = list[tuple[str, re.Pattern[str]]]


class RangeError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    commit: str
    path: str
    line: int
    shape: str
    shown: str
    """At most the first few letters of the match, then <redacted>."""
    allowed: bool
    """Listed, but doesn't fail the check."""


def load_shapes(path: Path = SHAPES_FILE) -> Shapes:
    """Each shape with its name. Each is searched for on its own: Python's re finds a shape's
    fixed letters fast, but tries every shape at every letter of a pattern that joins them."""
    sources: list[str] = json.loads(path.read_text())["shapes"]
    return [(NAMES.get(s, f"key shape {i + 1}"), re.compile(s)) for i, s in enumerate(sources)]


def is_placeholder(shape: str, matched: str) -> bool:
    if shape != "password in a URL" or not (url := URL_PASSWORD.fullmatch(matched)):
        return False
    password = url["password"]
    return password.startswith(PLACEHOLDER_STARTS) or len(password) < SHORTEST_URL_PASSWORD


def matches_in(shapes: Shapes, text: str) -> list[tuple[str, str]]:
    """Each match's shape name and at most its first few letters, then <redacted>, in the order
    they sit. Where two shapes match the same letters, the one listed first names it."""
    found: list[tuple[int, int, str]] = []
    for name, pattern in shapes:
        for match in pattern.finditer(text):
            start, end = match.span()
            if is_placeholder(name, match.group()):
                continue
            if all(end <= s or e <= start for s, e, _ in found):
                found.append((start, end, name))
    return [
        (name, text[s : s + SHOWN_BY_SHAPE.get(name, SHOWN)] + "<redacted>")
        for s, _, name in sorted(found)
    ]


def added_lines(lines: Iterable[str]) -> Iterator[tuple[str, str, int, str]]:
    """Each added line of `git log` output as GIT_LOG writes it: commit, file, line number and
    text. A merge's line counts when it is new against every parent."""
    commit, path, parents, number, in_hunk = "", "", 1, 0, False
    for line in lines:
        if line.startswith("commit "):
            commit, in_hunk = line[7:], False
        elif line.startswith("diff "):
            path, in_hunk = "", False
        elif not in_hunk and line.startswith("+++ "):
            path = line[4:].strip('"').removeprefix("b/")
        elif hunk := HUNK.match(line):
            parents, number, in_hunk = len(hunk[1]) - 1, int(hunk[2]), True
        elif in_hunk and line and not line.startswith("\\"):
            marks = line[:parents]
            if "-" in marks:
                continue
            if marks == "+" * parents:
                yield commit, path, number, line[parents:]
            number += 1


def scan(lines: Iterable[str], shapes: Shapes) -> Iterator[Finding]:
    for commit, path, number, text in added_lines(lines):
        marked = ALLOW_MARK in text
        for shape, shown in matches_in(shapes, text):
            allowed = marked or (path, shape) in ALLOWED_SHAPES
            yield Finding(commit, path, number, shape, shown, allowed)


def git_log(base: str, head: str, cwd: Path | None = None) -> Iterator[str]:
    with (
        tempfile.TemporaryFile() as errors,
        subprocess.Popen(
            [*GIT_LOG, f"{base}..{head}", "--"], cwd=cwd, stdout=subprocess.PIPE, stderr=errors
        ) as git,
    ):
        assert git.stdout is not None
        for raw in git.stdout:
            yield raw.decode("utf-8", "replace").rstrip("\r\n")
        if git.wait() != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", "replace").strip()
            raise RangeError(message or f"git log exited {git.returncode}")


def allowed_report(allowed: list[Finding]) -> str:
    rows = [f"  allowed  {f.commit}  {f.path}  line {f.line}  {f.shape}" for f in allowed]
    return "\n".join(
        [
            f"Allowed {len(allowed)} value(s) shaped like a key, by a gitleaks:allow comment or"
            " as an example in n8n's catalogue. Check that each one is made up:",
            *rows,
            "",
        ]
    )


def report(findings: list[Finding], base: str, head: str) -> str:
    rows = [f"  commit {f.commit}  {f.path}  line {f.line}  {f.shape}  {f.shown}" for f in findings]
    return "\n".join(
        [
            f"Found {len(findings)} value(s) shaped like a key"
            f" in the lines added by {base}..{head}:",
            *rows,
            "",
            "A key stays public even if a later commit removed it. GitHub keeps every commit of a",
            "pull request, and anyone can read them. So treat each real key here as leaked:",
            "  1. Revoke it where it was made, and make a new one. Keep the new one out of git,",
            "     in Azure Key Vault or a GitHub Actions secret.",
            "  2. Take it out of the files, then out of the history. To squash the branch into",
            "     one commit and push it:",
            "       git reset --soft $(git merge-base origin/main HEAD) && git commit"
            " && git push --force-with-lease",
            "     Or open a fresh branch from main without it, and close this one.",
            "If it is a made-up value for a test, build it from pieces at run time, as in",
            '"ghp_" + "Zx9" * 12, or add a gitleaks:allow comment on that line. Then squash the',
            "branch the same way, as the commit that added it still fails this check.",
        ]
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3 or any(arg.startswith("-") for arg in argv[1:]):
        print("usage: scripts/scan_commits.py <base> <head>", file=sys.stderr)
        return 2
    base, head = argv[1].strip(), argv[2].strip()
    if base in NO_RANGE:
        print("No range of commits is known for this run, so no commit was scanned.")
        return 0
    try:
        findings = list(scan(git_log(base, head), load_shapes()))
    except RangeError as error:
        print(f"Couldn't read the commits {base}..{head}: {error}", file=sys.stderr)
        return 2
    if allowed := [f for f in findings if f.allowed]:
        print(allowed_report(allowed))
    if failing := [f for f in findings if not f.allowed]:
        print(report(failing, base, head))
        return 1
    no_line = "No other line" if allowed else "No line"
    print(f"{no_line} added in the commits {base}..{head} is shaped like a key.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
