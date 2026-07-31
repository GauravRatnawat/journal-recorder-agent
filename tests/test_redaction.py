"""Publish-time redaction is deterministic, not a request to an LLM."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal  # noqa: E402


class TestRedaction(unittest.TestCase):
    def rules_from(self, text):
        path = Path(tempfile.mkdtemp()) / "rules"
        path.write_text(text)
        original = journal.REDACT_CONFIG
        journal.REDACT_CONFIG = str(path)
        try:
            return journal.redact_rules()
        finally:
            journal.REDACT_CONFIG = original

    def test_literal_rules_match_regardless_of_case(self):
        rules, _ = self.rules_from("acme-nemo-wrapper => the wrapper service\n")

        redacted, _ = journal.redact("Renamed ACME-Nemo-Wrapper today", rules)

        self.assertEqual("Renamed the wrapper service today", redacted)

    def test_rule_without_replacement_becomes_a_placeholder(self):
        rules, _ = self.rules_from("AcmeCorp\n")

        redacted, _ = journal.redact("built for acmecorp", rules)

        self.assertEqual("built for <redacted>", redacted)

    def test_regex_rules_use_the_re_prefix(self):
        rules, _ = self.rules_from("re:JIRA-\\d+ => <ticket>\n")

        redacted, _ = journal.redact("tracked in JIRA-4412", rules)

        self.assertEqual("tracked in <ticket>", redacted)

    def test_comments_and_blank_lines_are_ignored(self):
        rules, exists = self.rules_from("# a comment\n\n   \n")

        self.assertTrue(exists)
        self.assertEqual(journal.BUILTIN_REDACTIONS, rules)

    def test_a_malformed_regex_is_skipped_rather_than_aborting(self):
        rules, _ = self.rules_from("re:[unclosed => x\nAcmeCorp\n")

        redacted, _ = journal.redact("acmecorp ships", rules)

        self.assertEqual("<redacted> ships", redacted)

    def test_credentials_are_stripped_without_any_rules_file(self):
        journal_config = journal.REDACT_CONFIG
        journal.REDACT_CONFIG = str(Path(tempfile.mkdtemp()) / "absent")
        try:
            rules, exists = journal.redact_rules()
        finally:
            journal.REDACT_CONFIG = journal_config

        self.assertFalse(exists)
        redacted, _ = journal.redact(
            "mail dev@example.com token ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", rules)

        self.assertEqual("mail <email> token <token>", redacted)

    def test_hits_report_what_was_replaced_and_how_often(self):
        rules, _ = self.rules_from("AcmeCorp\n")

        _, hits = journal.redact("AcmeCorp and acmecorp", rules)

        self.assertIn(("AcmeCorp", "<redacted>", 2), hits)

    def test_the_one_line_summary_becomes_the_published_excerpt(self):
        body = ("# Title\n\n**In one line:** Allowlist guarded paths that never "
                "existed.\n\n## The story\nLonger prose here.\n")

        self.assertEqual("Allowlist guarded paths that never existed.",
                         journal.extract_excerpt(body))

    def test_older_entries_still_excerpt_from_their_tldr(self):
        body = "# Title\n\n## TL;DR\nRenamed the package.\n\n## What Was Accomplished\n"

        self.assertEqual("Renamed the package.", journal.extract_excerpt(body))


if __name__ == "__main__":
    unittest.main()
