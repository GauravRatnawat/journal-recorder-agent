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


if __name__ == "__main__":
    unittest.main()
