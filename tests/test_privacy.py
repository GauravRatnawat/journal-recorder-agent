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

    def test_public_publish_uses_shared_git_gate(self):
        site = self.root / "site"
        (site / "journal").mkdir(parents=True)
        entry = self.root / "entry.md"
        entry.write_text("# Safe note")
        with mock.patch.object(journal, "run_llm", return_value=("# Safe note\n", "fake")), \
                mock.patch.object(journal, "git_commit", return_value=True) as commit, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, journal.cmd_publish(str(entry), None, str(site)))
        self.assertEqual(1, commit.call_count)
        paths = commit.call_args.args[2]
        self.assertEqual(2, len(paths))
        self.assertIn("journal/index.js", paths)
        self.assertTrue(all(p.startswith("journal/") for p in paths))

    def test_any_agent_can_submit_safe_summary_on_stdin(self):
        payload = {"agent": "copilot", "cwd": str(self.root),
                   "session_id": "s", "summary": "# Safe choice\npassword=fake_manual_42"}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.object(journal, "git_commit", return_value=True), \
                mock.patch.object(journal, "run_llm") as model:
            self.assertEqual(0, journal.cmd_record())
        entries = list((self.root / "notes").rglob("*.md"))
        text = "\n".join(p.read_text() for p in entries)
        self.assertIn("Safe choice", text)
        self.assertIn("agent: copilot", text)
        self.assertNotIn("fake_manual_42", text)
        model.assert_not_called()

    def test_finalize_refuses_direct_file_sync(self):
        with mock.patch.object(journal, "git_commit") as commit, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_finalize())
        self.assertFalse((self.root / "notes").exists())
        commit.assert_not_called()

    def test_digest_scrubs_output_before_owned_sync(self):
        notes = self.root / "notes"
        project = notes / "demo"
        project.mkdir(parents=True)
        import datetime
        date = datetime.datetime.now().astimezone().isoformat()
        (project / "entry.md").write_text(f"---\ndate: {date}\n---\n# Safe choice")
        with mock.patch.object(journal, "run_llm", return_value=("# Digest\npassword=fake_digest_42", "fake")), \
                mock.patch.object(journal, "git_commit", return_value=True) as commit, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, journal.cmd_digest(7, None))
        output = next((notes / "digests").glob("*.md"))
        self.assertNotIn("fake_digest_42", output.read_text())
        self.assertEqual([str(output.relative_to(notes))], commit.call_args.args[2])

    def test_codex_lookup_requires_exact_thread_and_cwd(self):
        sessions = self.root / "sessions"
        folder = sessions / "2026" / "10" / "24"
        folder.mkdir(parents=True)
        for name, thread, cwd in (("one", "wanted", "/project"),
                                  ("two", "other", "/project"),
                                  ("three", "wanted", "/elsewhere")):
            (folder / f"rollout-{name}.jsonl").write_text(json.dumps({
                "type": "session_meta", "payload": {"id": thread, "cwd": cwd}}) + "\n")
        with mock.patch.object(journal, "CODEX_SESSIONS", str(sessions)):
            path, _ = journal.find_codex_rollout("/project", "wanted")
            self.assertEqual("rollout-one.jsonl", Path(path).name)
            self.assertEqual((None, {}), journal.find_codex_rollout("/missing", "wanted"))
            self.assertEqual((None, {}), journal.find_codex_rollout("/project", "missing"))

    def test_native_text_adapters_send_only_documented_text(self):
        fixtures = {
            "cursor": {"hook_event_name": "afterAgentResponse", "conversation_id": "c",
                       "workspace_roots": [str(self.root)], "text": "Safe choice. password=fake_adapter_42"},
            "gemini": {"hook_event_name": "AfterAgent", "session_id": "g", "cwd": str(self.root),
                       "prompt": "Keep choice clear", "prompt_response": "Safe choice. password=fake_adapter_42"},
        }
        for source, payload in fixtures.items():
            with self.subTest(source=source), \
                    mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    mock.patch.object(journal, "spawn_writer") as spawn:
                self.assertEqual(0, journal.cmd_hook_text(source))
                self.assertEqual(1, spawn.call_count)
                text = spawn.call_args.args[4]
                self.assertIn("Safe choice", text)
                self.assertNotIn("fake_adapter_42", text)
                self.assertEqual(source, spawn.call_args.args[3])

    def test_installer_merges_native_hooks_and_root_codex_notify(self):
        home = self.root / "home"
        (home / ".codex").mkdir(parents=True)
        (home / ".codex/config.toml").write_text('[projects."/demo"]\ntrust_level = "trusted"\n')
        env = {**os.environ, "HOME": str(home)}
        script = Path(journal.__file__).parent / "install.sh"
        for _ in range(2):
            subprocess.run(["bash", str(script), "--agents", "claude,codex,cursor,gemini"],
                           env=env, check=True, capture_output=True, text=True)
        import tomllib
        cfg = tomllib.loads((home / ".codex/config.toml").read_text())
        self.assertIn("notify", cfg)
        for tool, file, event in (("cursor", "hooks.json", "afterAgentResponse"),
                                  ("gemini", "settings.json", "AfterAgent")):
            config = json.loads((home / f".{tool}" / file).read_text())
            self.assertEqual(1, len(config["hooks"][event]))
        self.assertTrue((home / ".claude/hooks/journal.py").is_file())

    def test_unreadable_policy_blocks_model(self):
        self.rules.unlink()
        self.rules.mkdir()
        with mock.patch.object(journal, "run_claude") as provider:
            with self.assertRaises(ValueError):
                journal.run_llm("AcmeCorp choice")
        provider.assert_not_called()

    def test_raw_names_scrub_before_slug(self):
        self.rules.write_text("registry.acme.internal => hidden\n")
        data = {"agent": "registry.acme.internal", "cwd": "/tmp/registry.acme.internal",
                "summary": "# Safe choice"}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(data))), \
                mock.patch.object(journal, "git_commit", return_value=True):
            journal.cmd_record()
        paths = list((self.root / "notes").rglob("*"))
        text = "\n".join(str(p) + (p.read_text() if p.is_file() else "") for p in paths)
        self.assertNotIn("registry-acme-internal", text)
        self.assertIn("hidden", text)


if __name__ == "__main__":
    unittest.main()
