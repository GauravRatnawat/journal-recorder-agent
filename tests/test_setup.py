"""Fake setup checks. Real hooks stay untouched."""

import argparse
import importlib.util
import os
import contextlib
import io
import json
import subprocess
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
            home = Path(tmp).resolve()
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

    def load_setup(self):
        spec = importlib.util.spec_from_file_location('recorder_setup', Path(journal.__file__).with_name('setup.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_guided_defaults_keep_hooks_and_back_up_config(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            config = home / '.claude/settings.json'
            config.parent.mkdir()
            old = '{"theme":"dark","hooks":{"Stop":[{"hooks":[{"command":"keep-me"}]}]}}'
            config.write_text(old)
            with mock.patch.dict(os.environ, HOME=tmp), \
                    mock.patch.object(setup.shutil, 'which', return_value=None), \
                    mock.patch('builtins.input', side_effect=['', '', '', '']):
                self.assertEqual(0, setup.guided(home))
            self.assertEqual('local', (home / '.claude/.journal-sync').read_text().strip())
            self.assertEqual(str(home / 'journal'), (home / '.claude/.journal-folder').read_text().strip())
            self.assertIn('keep-me', config.read_text())
            self.assertIn('dark', config.read_text())
            self.assertEqual(old, next(config.parent.glob('settings.json.backup-*')).read_text())
            count = len(json.loads(config.read_text())['hooks']['Stop'])
            with mock.patch.dict(os.environ, HOME=tmp), \
                    mock.patch.object(setup.shutil, 'which', return_value=None), \
                    mock.patch('builtins.input', side_effect=['claude', '', '', '']):
                self.assertEqual(0, setup.guided(home))
            self.assertEqual(count, len(json.loads(config.read_text())['hooks']['Stop']))

    def test_cancel_or_bad_config_changes_nothing(self):
        setup = self.load_setup()
        for bad in (False, True):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp).resolve()
                config = home / '.claude/settings.json'
                config.parent.mkdir()
                config.write_text('bad JSON' if bad else '{}')
                before = {str(p): p.read_bytes() for p in home.rglob('*') if p.is_file()}
                with mock.patch.dict(os.environ, HOME=tmp), \
                        mock.patch.object(setup.shutil, 'which', return_value=None), \
                        mock.patch('builtins.input', side_effect=['', '', '', 'n']):
                    if bad:
                        with self.assertRaises(ValueError):
                            setup.guided(home)
                    else:
                        self.assertEqual(0, setup.guided(home))
                self.assertEqual(before, {str(p): p.read_bytes() for p in home.rglob('*') if p.is_file()})

    def test_symlink_config_blocks_before_install(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / '.claude').mkdir()
            outside = home / 'outside'
            outside.write_text('{}')
            (home / '.claude/settings.json').symlink_to(outside)
            with self.assertRaises(ValueError):
                setup.install_plan(home, ['claude'])
            self.assertFalse((home / '.claude/hooks').exists())
            self.assertEqual('{}', outside.read_text())

    def test_invalid_mode_blocks_before_entry_or_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / '.claude').mkdir()
            (home / '.claude/.journal-folder').write_text(str(home / 'notes'))
            (home / '.claude/.journal-sync').write_text('typo')
            args = argparse.Namespace(project='demo', source='manual', session_id='s', summary='# Safe')
            with mock.patch.dict(os.environ, HOME=tmp), mock.patch.object(journal, 'run_llm') as provider:
                self.assertEqual(1, journal.cmd_write(args))
                provider.assert_not_called()
            self.assertEqual([], list((home / 'notes').rglob('*.md')))

    def test_absent_mode_keeps_git(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, HOME=tmp):
            with mock.patch.object(journal, 'git_commit', return_value=True) as commit:
                self.assertTrue(journal.sync_journal(tmp, 'safe', ['safe.md']))
                commit.assert_called_once_with(tmp, 'safe', ['safe.md'])

    def test_local_digest_skips_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / '.claude').mkdir()
            root = home / 'notes'
            (root / 'demo').mkdir(parents=True)
            (home / '.claude/.journal-folder').write_text(str(root))
            (home / '.claude/.journal-sync').write_text('local')
            now = journal.datetime.datetime.now().astimezone().isoformat()
            (root / 'demo/entry.md').write_text(journal.render_frontmatter({'date': now}) + '# Safe note')
            with mock.patch.dict(os.environ, HOME=tmp), \
                    mock.patch.object(journal, 'run_llm', return_value=('# Safe digest', 'fake')), \
                    mock.patch.object(journal, 'git_commit') as commit:
                self.assertEqual(0, journal.cmd_digest(7, None))
                commit.assert_not_called()
            self.assertEqual(1, len(list((root / 'digests').glob('*.md'))))

    def test_doctor_uses_no_model_or_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / '.claude').mkdir()
            (home / '.claude/.journal-folder').write_text(str(home / 'notes'))
            (home / '.claude/.journal-sync').write_text('local')
            with mock.patch.dict(os.environ, HOME=tmp), \
                    mock.patch.object(journal, 'run_llm') as model, \
                    mock.patch.object(journal, 'git_commit') as git:
                self.assertEqual(0, journal.cmd_doctor())
                model.assert_not_called()
                git.assert_not_called()
            self.assertFalse((home / 'notes/.journal-check').exists())

    def test_git_setup_checks_existing_clone_and_keeps_notify(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            root = home / 'notes'
            root.mkdir()
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            with self.assertRaises(ValueError):
                setup.check_git(root)
            git('init', '-b', 'main')
            git('config', 'user.name', 'Recorder')
            git('config', 'user.email', 'recorder@localhost')
            (root / 'base').write_text('safe')
            git('add', 'base')
            git('commit', '-m', 'safe base')
            remote = home / 'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            git('remote', 'add', 'origin', str(remote))
            git('push', '-u', 'origin', 'main')
            setup.check_git(root)
            config = home / '.codex/config.toml'
            config.parent.mkdir()
            config.write_text('notify = ["keep-me"]\n')
            files, warnings = setup.install_plan(home, ['codex'])
            self.assertEqual(config.read_bytes(), files[config][0])
            self.assertIn('notify kept', warnings[0])
            (home / '.claude').mkdir()
            (home / '.claude/.journal-folder').write_text(str(root))
            (home / '.claude/.journal-sync').write_text('git')
            with mock.patch.dict(os.environ, HOME=str(home)), \
                    mock.patch.object(setup.shutil, 'which', return_value=None), \
                    mock.patch('builtins.input', side_effect=['manual', '', '', 'y', '']):
                self.assertEqual(0, setup.guided(home))
            self.assertEqual('git', (home / '.claude/.journal-sync').read_text().strip())
            self.assertEqual('safe base', git('log', '-1', '--format=%s'))

    def test_failed_apply_restores_config_bytes(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            first, second = root / 'first', root / 'second'
            first.write_text('old first')
            second.write_text('old second')
            replace = setup.os.replace
            calls = 0
            def fail_second(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('fake write failure')
                return replace(src, dst)
            with mock.patch.object(setup.os, 'replace', side_effect=fail_second):
                with self.assertRaises(OSError):
                    setup.apply_plan({first: (b'new first', 0o600), second: (b'new second', 0o600)})
            self.assertEqual('old first', first.read_text())
            self.assertEqual('old second', second.read_text())

    def test_quoted_codex_notify_stays_valid(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            config = home / '.codex/config.toml'
            config.parent.mkdir()
            config.write_text('\"notify\" = [\"keep\"]\n')
            text, warning = setup.codex_config(home)
            self.assertEqual(config.read_text(), text)
            self.assertTrue(warning)

    def test_preview_never_prints_config_values(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            path = home / 'settings.json'
            data = b'{"env":{"ANTHROPIC_API_KEY":"fake_hidden_value"},"hooks":{"Stop":[{"command":"python3 journal.py hook stop"}]}}'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                setup.preview({path: (data, 0o600)}, home, home / 'notes', 'local', ['claude'])
            self.assertNotIn('fake_hidden_value', output.getvalue())
            self.assertIn('Recorder hook: Stop', output.getvalue())

    def test_check_failure_and_interrupt_restore_old_files(self):
        setup = self.load_setup()
        for error in (ValueError('fake check failure'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                config = root / 'settings.json'
                core = root / 'journal.py'
                config.write_text('old config')
                def fail():
                    raise error
                with self.assertRaises(type(error)):
                    setup.apply_plan({config: (b'new config', 0o600), core: (b'new core', 0o700)}, verify=fail)
                self.assertEqual('old config', config.read_text())
                self.assertFalse(core.exists())

    def test_failed_check_restores_hook_mode_and_repair_works(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'hook.sh'
            path.write_bytes(b'old')
            path.chmod(0o700)
            def fail():
                raise ValueError('fake')
            with self.assertRaises(ValueError):
                setup.apply_plan({path: (b'new', 0o700)}, verify=fail)
            self.assertEqual(b'old', path.read_bytes())
            self.assertEqual(0o700, path.stat().st_mode & 0o777)
            path.chmod(0o600)
            setup.apply_plan({path: (b'old', 0o700)})
            self.assertEqual(0o700, path.stat().st_mode & 0o777)

    def test_nested_codex_notify_does_not_hide_root_route(self):
        import tomllib
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            config = home / '.codex/config.toml'
            config.parent.mkdir()
            config.write_text('[mcp_servers.demo.env]\nnotify = "quiet"\n')
            text, warning = setup.codex_config(home)
            parsed = tomllib.loads(text)
            self.assertIn('notify', parsed)
            self.assertEqual('quiet', parsed['mcp_servers']['demo']['env']['notify'])
            self.assertEqual('', warning)

    def test_legacy_install_keeps_default_root_and_git_choice(self):
        setup = self.load_setup()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            hook = home / '.claude/hooks/journal.py'
            hook.parent.mkdir(parents=True)
            hook.write_text('# old core')
            prompts = []
            def answer(prompt, default):
                prompts.append((prompt, default))
                return 'n' if prompt.startswith('Confirm origin') else default
            with mock.patch.object(setup, 'ask', side_effect=answer), \
                    mock.patch.object(setup, 'check_git'), \
                    mock.patch.object(setup.shutil, 'which', return_value=None):
                self.assertEqual(0, setup.guided(home))
            self.assertIn(('Save notes here?', str(home / 'claude-journal')), prompts)
            self.assertIn(('Sync to existing private Git clone? y/n', 'y'), prompts)
            self.assertEqual('# old core', hook.read_text())

    def test_bootstrap_main_uses_checked_payload_and_terminal(self):
        spec = importlib.util.spec_from_file_location('bootstrap', Path(journal.__file__).with_name('bootstrap.py'))
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'fake archive'
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', return_value=response), \
                mock.patch.object(bootstrap, 'extract_checked', return_value=Path('/fake/payload')) as extract, \
                mock.patch('builtins.open', mock.mock_open()), \
                mock.patch.object(bootstrap.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(0, bootstrap.main())
            self.assertEqual(b'fake archive', extract.call_args.args[0])
            self.assertEqual(bootstrap.SHA256, extract.call_args.args[2])
            self.assertEqual('-I', run.call_args.args[0][1])
            self.assertIn('stdin', run.call_args.kwargs)

    def test_bootstrap_checks_hash_paths_and_links(self):
        import hashlib
        import tarfile
        spec = importlib.util.spec_from_file_location('bootstrap', Path(journal.__file__).with_name('bootstrap.py'))
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        for unsafe in ('good', 'hash', 'path', 'link'):
            with self.subTest(case=unsafe), tempfile.TemporaryDirectory() as tmp:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
                    for name in ('pkg/setup.py', 'pkg/journal.py'):
                        info = tarfile.TarInfo(name)
                        data = b'# fake safe payload\n'
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
                    if unsafe in ('path', 'link'):
                        info = tarfile.TarInfo('../escape' if unsafe == 'path' else 'pkg/link')
                        if unsafe == 'link':
                            info.type = tarfile.SYMTYPE
                            info.linkname = '/tmp/outside'
                        archive.addfile(info)
                data = buffer.getvalue()
                digest = 'bad' if unsafe == 'hash' else hashlib.sha256(data).hexdigest()
                if unsafe == 'good':
                    root = bootstrap.extract_checked(data, Path(tmp), digest)
                    self.assertTrue((root / 'setup.py').is_file())
                else:
                    with self.assertRaises(ValueError):
                        bootstrap.extract_checked(data, Path(tmp), digest)
                    self.assertEqual([], list(Path(tmp).iterdir()))
