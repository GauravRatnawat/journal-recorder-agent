"""run_llm fallback ordering: claude first, codex exec when claude is
missing or empty, empty tuple when neither works.

Run: python3 -m unittest discover tests
"""

import importlib.util
import os
import sys
import unittest
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "journal",
    os.path.join(os.path.dirname(__file__), "..", "journal.py"),
)
journal = importlib.util.module_from_spec(_SPEC)
sys.modules["journal"] = journal
_SPEC.loader.exec_module(journal)


def _which(available):
    return lambda name: f"/bin/{name}" if name in available else None


class TestRunLlm(unittest.TestCase):
    def test_claude_present_and_working_wins(self):
        with mock.patch.object(journal.shutil, "which", _which({"claude", "codex"})), \
             mock.patch.object(journal, "run_claude", return_value="claude body"), \
             mock.patch.object(journal, "run_codex") as codex:
            self.assertEqual(journal.run_llm("p"), ("claude body", journal.MODEL))
            codex.assert_not_called()

    def test_codex_only_machine_uses_codex(self):
        with mock.patch.object(journal.shutil, "which", _which({"codex"})), \
             mock.patch.object(journal, "run_claude") as claude, \
             mock.patch.object(journal, "run_codex", return_value="codex body"):
            self.assertEqual(journal.run_llm("p"), ("codex body", "codex-exec"))
            claude.assert_not_called()

    def test_claude_failure_falls_back_to_codex(self):
        with mock.patch.object(journal.shutil, "which", _which({"claude", "codex"})), \
             mock.patch.object(journal, "run_claude", return_value=""), \
             mock.patch.object(journal, "run_codex", return_value="codex body"):
            self.assertEqual(journal.run_llm("p"), ("codex body", "codex-exec"))

    def test_no_cli_returns_empty(self):
        with mock.patch.object(journal.shutil, "which", _which(set())):
            self.assertEqual(journal.run_llm("p"), ("", journal.MODEL))


if __name__ == "__main__":
    unittest.main()