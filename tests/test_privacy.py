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


if __name__ == "__main__":
    unittest.main()
