"""Fake setup checks. Real hooks stay untouched."""

import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal


class SetupTests(unittest.TestCase):
    def test_local_record_saves_scrubbed_note_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.claude').mkdir()
            (home / '.claude/.journal-folder').write_text(str(home / 'journal'))
            (home / '.claude/.journal-sync').write_text('local\n')
            args = argparse.Namespace(project='demo', source='manual', session_id='s',
                                      summary='# Keep choice\npassword=fake_local_42')
            with mock.patch.dict(os.environ, HOME=tmp), \
                    mock.patch.object(journal, 'git_commit') as commit:
                self.assertEqual(0, journal.cmd_write(args))
                commit.assert_not_called()
                root = home / 'journal'
                self.assertFalse((root / '.git').exists())
                self.assertTrue(journal.is_duplicate(str(root), 'demo', int(journal.time.time())))
                entry = next((root / 'demo').glob('20*.md')).read_text()
                self.assertNotIn('fake_local_42', entry)
                self.assertIn('Keep choice', entry)
