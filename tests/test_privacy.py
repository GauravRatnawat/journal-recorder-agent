"""Fake secrets test shared privacy gates. No live model or remote."""

from pathlib import Path
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules = self.root / "rules"
        self.rules.write_text("AcmeCorp => <company>\n")
        for patch in (
            mock.patch.object(journal, "REDACT_CONFIG", str(self.rules)),
            mock.patch.object(journal, "journal_root", return_value=str(self.root / "notes")),
            mock.patch.object(journal, "log_line"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_model_boundary_scrubs_input_and_output(self):
        secret = "ghp_" + "a" * 30
        prompts = []

        def provider(prompt):
            prompts.append(prompt)
            return "# AcmeCorp\npassword=hunter_fake_42\nBearer opaque_fake_42"

        with mock.patch.object(journal.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(journal, "run_claude", side_effect=provider):
            body, _ = journal.run_llm(f"AcmeCorp {secret} api_key=plain_fake_42")
        self.assertNotIn(secret, prompts[0])
        self.assertNotIn("AcmeCorp", prompts[0])
        self.assertNotIn("plain_fake_42", prompts[0])
        self.assertNotIn("hunter_fake_42", body)
        self.assertNotIn("opaque_fake_42", body)
        self.assertNotIn("AcmeCorp", body)

    def test_failed_model_saves_no_entry(self):
        digest = self.root / "digest"
        digest.write_text("raw session must stay out")
        args = argparse.Namespace(digest_file=str(digest), project="demo",
                                  session_id="session", source="stop")
        with mock.patch.object(journal, "run_llm", return_value=("", "fake")), \
                mock.patch.object(journal, "git_commit") as commit:
            self.assertEqual(1, journal.cmd_write(args))
        self.assertEqual([], list((self.root / "notes").rglob("*.md")))
        commit.assert_not_called()

    def test_temp_digest_holds_only_scrubbed_text(self):
        captured = []

        def spawn(argv, **kwargs):
            path = Path(argv[argv.index("--digest-file") + 1])
            captured.append(path.read_text())
            path.unlink()

        with mock.patch.object(journal.subprocess, "Popen", side_effect=spawn):
            journal.spawn_writer(str(self.root / "notes"), "demo", "s", "stop",
                                 "Keep safe choice. password=fake_temp_42 AcmeCorp")
        self.assertIn("Keep safe choice.", captured[0])
        self.assertNotIn("fake_temp_42", captured[0])
        self.assertNotIn("AcmeCorp", captured[0])

    def test_saved_entry_and_metadata_use_scrubbed_text(self):
        digest = self.root / "digest"
        digest.write_text("safe session")
        secret = "ghp_" + "z" * 30
        args = argparse.Namespace(digest_file=str(digest), project="AcmeCorp",
                                  session_id=secret, source="stop")
        with mock.patch.object(journal, "run_llm", return_value=(
                "# AcmeCorp choice\n\npassword=fake_output_42\n## Tags\n#AcmeCorp", "fake")), \
                mock.patch.object(journal, "git_commit"):
            self.assertEqual(0, journal.cmd_write(args))
        paths = list((self.root / "notes").rglob("*"))
        saved = "\n".join(str(p) + (p.read_text() if p.is_file() else "") for p in paths)
        for value in (secret, "AcmeCorp", "fake_output_42"):
            self.assertNotIn(value, saved)
        self.assertIn("choice", saved)

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def repo(self):
        root = self.root / "repo"
        root.mkdir()
        self.git(root, "init", "-b", "main")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "config", "user.email", "test@example.test")
        (root / "base.md").write_text("safe base")
        self.git(root, "add", "base.md")
        self.git(root, "commit", "-m", "base")
        return root

    def test_commit_blocks_unrelated_staged_data(self):
        root = self.repo()
        (root / "other.txt").write_text("unrelated")
        self.git(root, "add", "other.txt")
        (root / "entry.md").write_text("safe choice")
        before = self.git(root, "rev-parse", "HEAD")
        self.assertFalse(journal.git_commit(str(root), "journal: safe", ["entry.md"]))
        self.assertEqual(before, self.git(root, "rev-parse", "HEAD"))
        self.assertEqual("other.txt", self.git(root, "diff", "--cached", "--name-only"))

    def test_commit_rejects_unsafe_owned_text(self):
        root = self.repo()
        (root / "entry.md").write_text("password=fake_commit_42")
        before = self.git(root, "rev-parse", "HEAD")
        with mock.patch.object(journal, "git_push") as push:
            self.assertFalse(journal.git_commit(str(root), "journal: safe", ["entry.md"]))
        self.assertEqual(before, self.git(root, "rev-parse", "HEAD"))
        self.assertEqual("", self.git(root, "diff", "--cached", "--name-only"))
        push.assert_not_called()

    def test_push_scans_old_outgoing_content_even_when_deleted(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        baseline = self.git(remote, "rev-parse", "main")
        (root / "entry.md").write_text("password=fake_history_42")
        self.git(root, "add", "entry.md")
        self.git(root, "commit", "-m", "unsafe")
        (root / "entry.md").unlink()
        self.git(root, "add", "-u")
        self.git(root, "commit", "-m", "clean head")
        def run(*args):
            return subprocess.run(["git", "-C", str(root), *args],
                                  capture_output=True, text=True)
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual(baseline, self.git(remote, "rev-parse", "main"))

    def test_safe_writer_pushes_only_its_outputs(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        (root / "unrelated.txt").write_text("keep local")
        digest = self.root / "digest"
        digest.write_text("safe choice")
        args = argparse.Namespace(digest_file=str(digest), project="demo",
                                  session_id="s", source="stop")
        with mock.patch.object(journal, "journal_root", return_value=str(root)), \
                mock.patch.object(journal, "run_llm", return_value=("# Safe choice\n", "fake")):
            self.assertEqual(0, journal.cmd_write(args))
        self.assertEqual(self.git(root, "rev-parse", "HEAD"), self.git(remote, "rev-parse", "main"))
        changed = self.git(root, "show", "--format=", "--name-only", "HEAD").splitlines()
        self.assertIn("demo/INDEX.md", changed)
        self.assertIn("HOME.md", changed)
        self.assertTrue(any(p.startswith("demo/") and p.endswith(".md") and "INDEX" not in p for p in changed))
        self.assertNotIn("unrelated.txt", self.git(root, "ls-files"))

    def test_publish_failure_never_writes_or_commits(self):
        site = self.root / "site"
        (site / "journal").mkdir(parents=True)
        entry = self.root / "entry.md"
        entry.write_text("# Safe note\npassword=fake_publish_42")
        with mock.patch.object(journal, "run_llm", return_value=("", "fake")), \
                mock.patch.object(journal.subprocess, "run") as git, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_publish(str(entry), None, str(site)))
        self.assertEqual([], list((site / "journal").iterdir()))
        git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
