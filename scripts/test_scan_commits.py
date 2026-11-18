"""scripts/scan_commits.py finds a key in any commit of a range, even one a later commit removed,
and never shows more of it than its first few letters. scripts/gitleaks-commits.sh fails when
gitleaks can't read the range. Nothing cancels CI's scans job.

Run from the repo root: python3 -I -B -m unittest discover -s scripts -p test_scan_commits.py"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import scan_commits

SCRIPT = Path(scan_commits.__file__).resolve()
ROOT = SCRIPT.parent.parent
GITLEAKS = ROOT / "scripts" / "gitleaks-commits.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
# Each built at run time, so no secret scanner reads one as leaked. None is a real key.
ATLASSIAN = "ATATT" + "3xFfGF0" + "Qv7Jm2Kp" * 4 + "=9C1D2E3F"
GITHUB = "ghp_" + "Wq8Rt5Yu" * 5
ENTRA = "Q8k" + "8Q~" + ("Ab3_dEf9~h.K" * 3)[:34]
URL_PASSWORD = "Xk82mQp9Lz"
DB_URL = "postgresql://app:" + URL_PASSWORD + "@db:5432/app"
HEX40 = "3f2a9c1e" * 5
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}
FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" > "$FAKE_DOCKER_ARGS"
printf '%b' "$FAKE_DOCKER_OUTPUT"
exit "$FAKE_DOCKER_EXIT"
"""
"""Stands in for docker in the gitleaks tests: notes its arguments, prints what it is told."""
SCANNED = "\x1b[90m9:16AM\x1b[0m \x1b[32mINF\x1b[0m {} commits scanned.\n"
NO_LEAKS = "\x1b[90m9:16AM\x1b[0m \x1b[32mINF\x1b[0m no leaks found\n"
UNREADABLE = (
    "\x1b[90m9:16AM\x1b[0m \x1b[31mERR\x1b[0m failed to scan Git repository"
    ' error="git error encountered, see logs"\n'
)


class Repo:
    """A throwaway git repo that sees no global or system git settings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.env = {**os.environ, **GIT_ENV}
        path.mkdir(exist_ok=True)
        self.git("init", "--quiet", "--initial-branch=main")

    def git(self, *args: str, stdin: bytes | None = None) -> str:
        done = subprocess.run(
            ["git", *args], cwd=self.path, env=self.env, input=stdin, capture_output=True
        )
        if done.returncode != 0:
            raise AssertionError(f"git {args[0]} failed: {done.stderr.decode()}")
        return done.stdout.decode().strip()

    def commit(self, files: dict[str, str | None], message: str = "change") -> str:
        for name, text in files.items():
            path = self.path / name
            if text is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "--message", message)
        return self.git("rev-parse", "HEAD")

    def run(self, *command: str, env: dict[str, str] | None = None) -> tuple[int, str]:
        done = subprocess.run(
            command, cwd=self.path, env={**self.env, **(env or {})}, capture_output=True, text=True
        )
        return done.returncode, done.stdout + done.stderr

    def scan(self, base: str, head: str) -> tuple[int, str]:
        return self.run(sys.executable, "-I", "-B", str(SCRIPT), base, head)


def never_shown(key: str, output: str) -> list[str]:
    """Every five letters of the key that the output holds. Only the first four may show."""
    return [key[i : i + 5] for i in range(len(key) - 4) if key[i : i + 5] in output]


class ScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(Path(self.tmp.name))
        self.base = self.repo.commit({"README.md": "# A project\n"}, "start")

    def test_a_key_added_then_removed_is_found_and_shown_only_by_its_first_letters(self):
        added = self.repo.commit(
            {"config/jira.env": f"JIRA_URL=https://example.atlassian.net\nJIRA_TOKEN={ATLASSIAN}\n"}
        )
        self.repo.commit({"config/jira.env": "JIRA_URL=https://example.atlassian.net\n"})

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 1, output)
        self.assertIn(f"commit {added}  config/jira.env  line 2  Atlassian API token", output)
        self.assertIn("ATAT<redacted>", output)
        self.assertIn("revoke", output.lower())
        self.assertIn("even if a later commit removed it", output)
        self.assertIn("git reset --soft $(git merge-base origin/main HEAD)", output)
        self.assertEqual(never_shown(ATLASSIAN, output), [])

    def test_each_key_in_a_commit_is_reported_with_its_line(self):
        added = self.repo.commit(
            {"src/a.py": f"x = 1\nGH = '{GITHUB}'\ny = 2\nsaved = 'token: {HEX40}'\n"}
        )

        code, output = self.repo.scan(self.base, added)

        self.assertEqual(code, 1, output)
        self.assertIn(f"commit {added}  src/a.py  line 2  GitHub token  ghp_<redacted>", output)
        self.assertIn("src/a.py  line 4  40 hex after a key word  toke<redacted>", output)
        self.assertEqual(never_shown(GITHUB, output), [])

    def test_a_shape_with_no_fixed_start_shows_no_letters(self):
        added = self.repo.commit({"app.env": f"CLIENT_SECRET={ENTRA}\n"})

        code, output = self.repo.scan(self.base, added)

        self.assertEqual(code, 1, output)
        self.assertIn("app.env  line 1  Entra client secret  <redacted>", output)
        self.assertNotIn(ENTRA[:2], output)

    def test_a_password_in_a_url_is_found_and_never_shown(self):
        added = self.repo.commit({"deploy/app.env": f"DATABASE_URL={DB_URL}\n"})

        code, output = self.repo.scan(self.base, added)

        self.assertEqual(code, 1, output)
        self.assertIn("deploy/app.env  line 1  password in a URL  ://<redacted>", output)
        self.assertEqual(never_shown(URL_PASSWORD, output), [])

    def test_a_clean_range_passes(self):
        self.repo.commit({"src/app.py": "print('hello')\n"})
        self.repo.commit({"src/app.py": "print('hello, world')\n", "notes.md": "MOCK-123\n"})

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 0, output)
        self.assertIn("No line added", output)

    def test_only_the_commits_after_the_base_are_read(self):
        self.repo.commit({"old.env": f"TOKEN={ATLASSIAN}\n"})
        base = self.repo.commit({"old.env": None})
        self.repo.commit({"src/app.py": "print('hello')\n"})

        code, output = self.repo.scan(base, "HEAD")

        self.assertEqual(code, 0, output)

    def test_a_merge_is_read_for_its_own_lines_only(self):
        self.repo.git("checkout", "--quiet", "-b", "feature")
        self.repo.commit({"a.txt": "one\n"})
        self.repo.git("checkout", "--quiet", "main")
        self.repo.commit({"b.txt": "two\n"})
        self.repo.git("checkout", "--quiet", "feature")
        self.repo.git("merge", "--quiet", "--no-commit", "--no-ff", "main")
        (self.repo.path / "a.txt").write_text(f"one\nKEY={ATLASSIAN}\n")
        self.repo.git("add", "a.txt")
        self.repo.git("commit", "--quiet", "--message", "merge main")
        merge = self.repo.git("rev-parse", "HEAD")

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 1, output)
        self.assertIn(f"commit {merge}  a.txt  line 2  Atlassian API token", output)
        self.assertEqual(output.count("  commit "), 1, output)

    def test_a_marked_line_and_a_catalogue_url_pass_but_are_listed_as_allowed(self):
        added = self.repo.commit(
            {
                "tests/test_x.py": f"KEY = '{GITHUB}'  # gitleaks:allow\n",
                "contracts/n8n/catalogue.json": json.dumps({"hint": DB_URL}) + "\n",
            }
        )

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 0, output)
        self.assertIn(f"allowed  {added}  tests/test_x.py  line 1  GitHub token", output)
        self.assertIn(
            f"allowed  {added}  contracts/n8n/catalogue.json  line 1  password in a URL", output
        )
        self.assertEqual(never_shown(GITHUB, output), [])

    def test_any_other_key_in_the_catalogue_fails(self):
        self.repo.commit({"contracts/n8n/catalogue.json": json.dumps({"hint": GITHUB}) + "\n"})

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 1, output)
        self.assertIn("contracts/n8n/catalogue.json  line 1  GitHub token  ghp_<redacted>", output)

    def test_a_moved_file_is_not_read_again(self):
        self.repo.commit({"a.env": f"TOKEN={ATLASSIAN}\n" + "line\n" * 20})
        base = self.repo.git("rev-parse", "HEAD")
        self.repo.git("mv", "a.env", "b.env")
        self.repo.git("commit", "--quiet", "--message", "move")

        code, output = self.repo.scan(base, "HEAD")

        self.assertEqual(code, 0, output)

    def test_no_known_range_passes_with_a_note(self):
        for base in ("", "0" * 40):
            code, output = self.repo.scan(base, "HEAD")
            self.assertEqual(code, 0, output)
            self.assertIn("no commit was scanned", output)

    def test_a_commit_git_cant_find_fails_the_check(self):
        code, output = self.repo.scan("1" * 40, "HEAD")

        self.assertEqual(code, 2, output)
        self.assertIn("Couldn't read the commits", output)

    def test_a_long_history_is_read_in_one_pass(self):
        commits, lines = 3000, 20
        stream = bytearray()
        for i in range(commits):
            body = "".join(
                f"release {i}.{n}.0 of langgraph==0.2.{n} at {HEX40} id {i:08d}-1a2b-4c3d-9e8f"
                f"-0a1b2c3d4e5f MOCK-{i}\n"
                for n in range(lines)
            )
            if i == commits // 2:
                body += f"JIRA_TOKEN={ATLASSIAN}\n"
            data = body.encode()
            stream += b"commit refs/heads/main\n"
            stream += f"committer Test <test@example.com> {1_700_000_000 + i} +0000\n".encode()
            stream += b"data 6\nchange\n"
            if i == 0:
                stream += f"from {self.base}\n".encode()
            stream += f"M 644 inline d/{i}.txt\ndata {len(data)}\n".encode() + data + b"\n"
        self.repo.git("fast-import", "--quiet", stdin=bytes(stream))

        started = time.monotonic()
        code, output = self.repo.scan(self.base, "main")
        took = time.monotonic() - started

        self.assertEqual(code, 1, output)
        self.assertEqual(output.count("  commit "), 1, output)
        self.assertIn(f"d/{commits // 2}.txt  line {lines + 1}  Atlassian API token", output)
        # This whole test, the history's import included, took about 3 seconds on a laptop on
        # 18 Nov 2026.
        self.assertLess(took, 30, f"{took:.1f} s")


class LineTest(unittest.TestCase):
    shapes = scan_commits.load_shapes()

    def test_every_shape_has_a_name(self):
        sources = json.loads(scan_commits.SHAPES_FILE.read_text())["shapes"]
        unnamed = [s for s in sources if s not in scan_commits.NAMES]
        self.assertEqual(unnamed, [], "name each new shape in NAMES in scripts/scan_commits.py")

    def test_plain_text_is_not_a_key(self):
        plain = [
            "langgraph==0.2.45 and langchain-core>=0.3.0,<0.4",
            "Release v1.2.3-rc.1 is out, see CHANGELOG.md#v1.2.3",
            f"commit {HEX40} fixed it",
            f"Merge pull request #132 from team/branch at {HEX40[:12]}",
            "run 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d finished",
            "MOCK-123, PROJ-4567 and OPS-1 are open in Jira",
            "the task-management-workflow sets up a basic 2-step-approval-flow",
            "postgresql://db:5432/app?sslmode=require",
            "https://github.com/langchain-ai/langgraph/releases/tag/0.2.45",
            "image: postgres:17@sha256:" + "2d2b8998" * 8,
            "2026-11-18T09:30:00+08:00 bearer instruments",
            "uses: actions/checkout@" + HEX40[:40] + " # v5",
            "Authorization: Bearer ${{ secrets.TOKEN }}",
        ]
        for line in plain:
            with self.subTest(line=line):
                self.assertEqual(scan_commits.matches_in(self.shapes, line), [])

    def test_a_placeholder_or_short_password_in_a_url_is_not_a_key(self):
        placeholders = [
            "PLATFORM_TEST_DATABASE_URL: postgresql://postgres:test@127.0.0.1:5432/postgres",
            "redis://:secret@localhost:6379",
            "postgres://app:${DB_PASSWORD}@db:5432/app",
            "postgres://app:$DATABASE_PASSWORD@db:5432/app",
            "amqp://guest:{password}@rabbit:5672",
            "mongodb://admin:<your-password>@cluster.example.com",
            "mysql://root:%(password)s@db/app",
        ]
        for line in placeholders:
            with self.subTest(line=line):
                self.assertEqual(scan_commits.matches_in(self.shapes, line), [])

    def test_a_long_line_is_read_in_linear_time(self):
        n = 100_000
        for text in ("\\n" * n, "%41" * n, "=3D" * n, "a" * n, "-" * n, "basic " * n, "eyJ-" * n):
            started = time.monotonic()
            scan_commits.matches_in(self.shapes, text)
            self.assertLess(time.monotonic() - started, 5, text[:12])


class GitleaksTest(unittest.TestCase):
    """gitleaks v8.21.2 logs that it couldn't read the commits and still exits 0."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        work = Path(self.tmp.name)
        self.repo = Repo(work / "repo")
        self.base = self.repo.commit({"README.md": "# A project\n"}, "start")
        self.head = self.repo.commit({"src/app.py": "print('hello')\n"})
        bin_dir = work / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(FAKE_DOCKER)
        (bin_dir / "docker").chmod(0o755)
        self.args = work / "docker-args.txt"
        self.path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def gitleaks(self, output: str, exit_code: int = 0, base: str = "") -> tuple[int, str]:
        env = {
            "PATH": self.path,
            "GITLEAKS_IMAGE": "gitleaks:test",
            "FAKE_DOCKER_ARGS": str(self.args),
            "FAKE_DOCKER_OUTPUT": output,
            "FAKE_DOCKER_EXIT": str(exit_code),
        }
        return self.repo.run("bash", str(GITLEAKS), base or self.base, self.head, env=env)

    def test_a_readable_range_with_no_leak_passes(self):
        code, output = self.gitleaks(SCANNED.format(1) + NO_LEAKS)

        self.assertEqual(code, 0, output)
        self.assertIn(f"--log-opts={self.base}..{self.head}", self.args.read_text())

    def test_a_range_gitleaks_cant_read_fails(self):
        code, output = self.gitleaks(UNREADABLE + SCANNED.format(0) + NO_LEAKS)

        self.assertEqual(code, 1, output)
        self.assertIn("gitleaks couldn't read the commits", output)

    def test_no_commit_scanned_in_a_range_that_has_some_fails(self):
        code, output = self.gitleaks(SCANNED.format(0) + NO_LEAKS)

        self.assertEqual(code, 1, output)
        self.assertIn("gitleaks scanned no commit", output)

    def test_an_empty_range_may_scan_no_commit(self):
        code, output = self.gitleaks(SCANNED.format(0) + NO_LEAKS, base=self.head)

        self.assertEqual(code, 0, output)

    def test_a_leak_fails(self):
        code, output = self.gitleaks(SCANNED.format(1) + "leaks found: 1\n", exit_code=1)

        self.assertEqual(code, 1, output)


def ci_jobs() -> tuple[str, dict[str, str]]:
    """ci.yml's text before `jobs:`, and each job's text by its id."""
    head, jobs = CI.read_text().split("\njobs:\n", 1)
    parts = re.split(r"^  ([A-Za-z0-9_-]+):[ \t]*$", jobs, flags=re.M)
    return head, dict(zip(parts[1::2], parts[2::2], strict=True))


class CiTest(unittest.TestCase):
    def test_nothing_cancels_the_scans_job(self):
        head, jobs = ci_jobs()

        self.assertIsNone(re.search(r"^concurrency:", head, re.M), "a run-wide group cancels it")
        self.assertIn("scans", jobs)
        self.assertNotIn("concurrency:", jobs["scans"])

    def test_every_other_job_cancels_only_its_own_older_run(self):
        _, jobs = ci_jobs()
        groups = {}
        for name, text in jobs.items():
            if name == "scans":
                continue
            group = re.search(r"^    concurrency:\n      group: (.+)\n", text, re.M)
            self.assertIsNotNone(group, f"job {name} has no concurrency group")
            assert group is not None
            groups[name] = group[1]
        self.assertEqual(len(set(groups.values())), len(groups), groups)
        self.assertIn("matrix.project", groups["checks"], "each leg needs its own group")


if __name__ == "__main__":
    unittest.main()
