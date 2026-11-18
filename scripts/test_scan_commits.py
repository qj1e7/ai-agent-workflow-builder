"""scripts/scan_commits.py finds a key in any commit of a range, even one a later commit removed,
and never shows more of it than its first four letters.

Run from the repo root: python3 -I -m unittest discover -s scripts -p test_scan_commits.py"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import scan_commits

SCRIPT = Path(scan_commits.__file__).resolve()
# Each built at run time, so no secret scanner reads one as leaked. None is a real key.
ATLASSIAN = "ATATT" + "3xFfGF0" + "Qv7Jm2Kp" * 4 + "=9C1D2E3F"
GITHUB = "ghp_" + "Wq8Rt5Yu" * 5
HEX40 = "3f2a9c1e" * 5
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class Repo:
    """A throwaway git repo that sees no global or system git settings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.env = {**os.environ, **GIT_ENV}
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

    def scan(self, base: str, head: str) -> tuple[int, str]:
        done = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), base, head],
            cwd=self.path,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return done.returncode, done.stdout + done.stderr


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

    def test_a_marked_line_and_the_generated_n8n_catalogue_are_skipped(self):
        url = "postgres://" + "app:" + "s3cret" + "@db:5432/app"
        self.repo.commit(
            {
                "tests/test_x.py": f"KEY = '{GITHUB}'  # gitleaks:allow\n",
                "contracts/n8n/catalogue.json": json.dumps({"hint": url}) + "\n",
            }
        )

        code, output = self.repo.scan(self.base, "HEAD")

        self.assertEqual(code, 0, output)

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
        # 60,000 lines took about 2 seconds on a laptop on 18 Nov 2026.
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

    def test_a_long_line_is_read_in_linear_time(self):
        n = 100_000
        for text in ("\\n" * n, "%41" * n, "=3D" * n, "a" * n, "-" * n, "basic " * n, "eyJ-" * n):
            started = time.monotonic()
            scan_commits.matches_in(self.shapes, text)
            self.assertLess(time.monotonic() - started, 5, text[:12])


if __name__ == "__main__":
    unittest.main()
