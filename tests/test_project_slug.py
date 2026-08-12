"""Journal entries are filed under the repository, not the checkout directory.

Conductor (and plain `git worktree`) put each task in its own directory named
after the branch, so basename-of-cwd files imtf-adrs work under "zurich".
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import journal  # noqa: E402


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class TestProjectSlug(unittest.TestCase):
    def test_plain_directory_falls_back_to_its_own_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "not-a-repo"
            plain.mkdir()
            self.assertEqual("not-a-repo", journal.project_slug(str(plain)))

    def test_repository_checkout_uses_the_repository_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "imtf-adrs"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "commit", "-q", "--allow-empty", "-m", "init")
            self.assertEqual("imtf-adrs", journal.project_slug(str(repo)))

    def test_worktree_uses_the_repository_name_not_the_branch_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "imtf-adrs"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "commit", "-q", "--allow-empty", "-m", "init")

            worktree = Path(tmp) / "workspaces" / "imtf-adrs" / "zurich"
            git(repo, "worktree", "add", "-q", "-b", "zurich", str(worktree))

            self.assertEqual("imtf-adrs", journal.project_slug(str(worktree)))


if __name__ == "__main__":
    unittest.main()
