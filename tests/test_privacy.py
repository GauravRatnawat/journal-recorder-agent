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
        entry = next(p for p in entries if p.name not in ("HOME.md", "INDEX.md"))
        self.assertEqual("copilot", journal.parse_frontmatter(str(entry))["agent"])
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

    def test_push_checks_renamed_path_with_reused_blob(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        baseline = self.git(remote, "rev-parse", "main")
        self.git(root, "mv", "base.md", "AcmeCorp.md")
        self.git(root, "commit", "-m", "rename")
        def run(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual(baseline, self.git(remote, "rev-parse", "main"))

    def test_split_push_url_blocks_before_upload(self):
        root = self.repo()
        fetch_remote = self.root / "fetch.git"
        push_remote = self.root / "push.git"
        for remote in (fetch_remote, push_remote):
            self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(fetch_remote))
        self.git(root, "push", "-u", "origin", "main")
        self.git(root, "remote", "set-url", "--push", "origin", str(push_remote))
        self.git(root, "commit", "--allow-empty", "-m", "safe")
        def run(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual("", self.git(push_remote, "for-each-ref", "--format=%(refname)"))

    def test_outgoing_author_identity_cannot_bypass_scan(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        baseline = self.git(remote, "rev-parse", "main")
        self.git(root, "-c", "user.name=AcmeCorp", "commit", "--allow-empty", "-m", "safe")
        def run(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual(baseline, self.git(remote, "rev-parse", "main"))

    def test_model_error_log_contains_no_provider_stderr(self):
        result = subprocess.CompletedProcess([], 1, "", "password=fake_error_42")
        with mock.patch.object(journal.subprocess, "run", return_value=result), \
                mock.patch.object(journal, "log_line") as log:
            self.assertEqual("", journal.run_claude("safe prompt"))
        self.assertNotIn("fake_error_42", str(log.call_args_list))

    def test_claude_generation_has_no_tools_or_project_context(self):
        seen = []
        def run(argv, **kwargs):
            seen.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "# Safe choice", "")
        with mock.patch.object(journal.subprocess, "run", side_effect=run):
            self.assertEqual("# Safe choice", journal.run_claude("safe prompt"))
        argv, kwargs = seen[0]
        self.assertEqual("", argv[argv.index("--tools") + 1])
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotEqual(os.getcwd(), kwargs["cwd"])
        self.assertEqual("safe prompt", kwargs["input"])
        self.assertNotIn("safe prompt", argv)

    def test_codex_provider_needs_explicit_opt_in(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(journal.shutil, "which", return_value="/bin/cli"), \
                mock.patch.object(journal, "run_claude", return_value=""), \
                mock.patch.object(journal, "run_codex", return_value="# Choice") as codex:
            self.assertEqual("", journal.run_llm("safe prompt")[0])
        codex.assert_not_called()

    def test_public_publish_requires_local_policy(self):
        self.rules.unlink()
        site = self.root / "site"
        (site / "journal").mkdir(parents=True)
        entry = self.root / "entry.md"
        entry.write_text("# Safe choice")
        with mock.patch.object(journal, "run_llm", return_value=("# Safe choice", "fake")) as model, \
                mock.patch.object(journal, "git_commit", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_publish(str(entry), None, str(site)))
        model.assert_not_called()
        self.assertEqual([], list((site / "journal").iterdir()))

    def test_hook_log_refuses_symlink_before_spawn(self):
        notes = self.root / "notes"
        notes.mkdir()
        sentinel = self.root / "keep"
        sentinel.write_text("keep bytes")
        (notes / ".journal.log").symlink_to(sentinel)
        with mock.patch.object(journal.subprocess, "Popen") as spawn:
            try:
                journal.spawn_writer(str(notes), "demo", "s", "stop", "safe choice")
            except (ValueError, OSError):
                pass
        self.assertEqual("keep bytes", sentinel.read_text())
        spawn.assert_not_called()

    def test_digest_and_publish_refuse_symlink_outputs(self):
        import datetime
        notes = self.root / "notes"
        project = notes / "demo"
        project.mkdir(parents=True)
        entry = project / "entry.md"
        entry.write_text("---\ndate: " + datetime.datetime.now().astimezone().isoformat() + "\n---\n# Safe note")
        outside = self.root / "outside"
        outside.mkdir()
        (notes / "digests").symlink_to(outside)
        with mock.patch.object(journal, "run_llm", return_value=("# Safe note", "fake")), \
                mock.patch.object(journal, "git_commit", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_digest(7, "demo"))
            site = self.root / "site"
            (site / "journal").mkdir(parents=True)
            sentinel = outside / "keep"
            sentinel.write_text("keep bytes")
            for name in (datetime.date.today().isoformat() + "-safe-note.md", "index.js"):
                link = site / "journal" / name
                link.symlink_to(sentinel)
                self.assertEqual(1, journal.cmd_publish(str(entry), None, str(site)))
                self.assertEqual("keep bytes", sentinel.read_text())
                link.unlink()
        self.assertEqual([sentinel], list(outside.iterdir()))

    def test_overlapping_writer_cannot_change_active_transaction(self):
        args = argparse.Namespace(project="demo", session_id="s", source="manual",
                                  summary="# Safe note")
        nested = []
        def commit(*unused):
            with mock.patch.object(journal, "git_commit", return_value=True):
                nested.append(journal.cmd_write(args))
            return True
        with mock.patch.object(journal, "git_commit", side_effect=commit):
            self.assertEqual(0, journal.cmd_write(args))
        self.assertEqual([1], nested)
        entries = [p for p in (self.root / "notes" / "demo").glob("*.md") if p.name != "INDEX.md"]
        self.assertEqual(1, len(entries))

    def test_failed_sync_reports_local_save_without_dedup(self):
        args = argparse.Namespace(project="demo", session_id="s", source="manual",
                                  summary="# Safe note")
        with mock.patch.object(journal, "git_commit", return_value=False):
            self.assertEqual(1, journal.cmd_write(args))
        notes = self.root / "notes"
        self.assertTrue(list((notes / "demo").glob("*.md")))
        self.assertFalse((notes / "demo" / ".last-written").exists())
        with mock.patch.object(journal, "run_llm", return_value=("# Digest", "fake")), \
                mock.patch.object(journal, "git_commit", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_digest(7, "demo"))

    def test_push_ignores_other_fetch_head(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        baseline = self.git(remote, "rev-parse", "main")
        (root / "entry.md").write_text("password=fake_baseline_42")
        self.git(root, "add", "entry.md")
        self.git(root, "-c", "user.email=recorder@localhost", "commit", "-m", "note")
        head = self.git(root, "rev-parse", "HEAD")
        def run(*args):
            result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
            if "fetch" in args:
                (root / ".git" / "FETCH_HEAD").write_text(head + "\n")
            return result
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual(baseline, self.git(remote, "rev-parse", "main"))

    def test_commit_uses_scanned_bytes_when_worktree_changes(self):
        root = self.repo()
        entry = root / "entry.md"
        entry.write_text("safe choice")
        original = journal.safe_text
        def scan(text):
            clean = original(text)
            if text == "safe choice":
                entry.write_text("password=fake_race_42")
            return clean
        with mock.patch.object(journal, "safe_text", side_effect=scan), \
                mock.patch.object(journal, "git_push", return_value=True):
            self.assertTrue(journal.git_commit(str(root), "journal: safe", ["entry.md"]))
        self.assertEqual("safe choice", self.git(root, "show", "HEAD:entry.md"))
        self.assertEqual("password=fake_race_42", entry.read_text())
        self.assertEqual("", self.git(root, "diff", "--cached", "--name-only"))

    def test_metadata_quotes_round_trip_special_text(self):
        values = {"title": 'Fix: "retry" loop', "project": "[cache]",
                  "session_id": "line\nbreak", "tags": ["x,y", "[cache]"]}
        entry = self.root / "quoted.md"
        encoded = journal.render_frontmatter(values)
        self.assertIn('title: "Fix:', encoded)
        self.assertNotIn("line\nbreak", encoded)
        entry.write_text(encoded + "# Note")
        self.assertEqual(values, journal.parse_frontmatter(str(entry)))

    def test_existing_dashboard_edits_stay_local(self):
        root = self.repo()
        (root / "HOME.md").write_text("old dashboard")
        self.git(root, "add", "HOME.md")
        self.git(root, "commit", "-m", "dashboard")
        (root / "HOME.md").write_text("user local edit")
        args = argparse.Namespace(project="demo", session_id="s", source="manual",
                                  summary="# Safe note")
        with mock.patch.object(journal, "journal_root", return_value=str(root)), \
                mock.patch.object(journal, "git_push", return_value=True):
            self.assertEqual(0, journal.cmd_write(args))
        self.assertEqual("old dashboard", self.git(root, "show", "HEAD:HOME.md"))
        self.assertEqual("user local edit", (root / "HOME.md").read_text())

    def test_output_writes_refuse_symlinks(self):
        notes = self.root / "notes"
        notes.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_text("keep bytes")
        args = argparse.Namespace(project="demo", session_id="s", source="manual",
                                  summary="# Safe note")
        for target in ("demo", "demo/INDEX.md", "HOME.md", "demo/.last-written"):
            with self.subTest(target=target):
                case_root = notes / str(len(list(notes.iterdir())))
                case_root.mkdir()
                outside = self.root / ("outside" + case_root.name)
                outside.mkdir()
                sentinel = outside / "keep"
                sentinel.write_text("keep bytes")
                link = case_root / target
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside if target == "demo" else sentinel)
                with mock.patch.object(journal, "git_commit", return_value=True), \
                        mock.patch.object(journal, "journal_root", return_value=str(case_root)):
                    try:
                        result = journal.cmd_write(args)
                    except (ValueError, OSError):
                        result = 1
                self.assertEqual("keep bytes", sentinel.read_text())
                self.assertEqual([sentinel], list(outside.iterdir()))
                self.assertEqual(1, result)
                link.unlink()
        dangling = notes / "demo" / "fresh.md"
        dangling.parent.mkdir(exist_ok=True)
        dangling.symlink_to(outside / "missing")
        self.assertNotEqual(str(dangling), journal.unique_path(str(dangling.parent), "fresh"))

    def test_publish_rejects_date_path_escape_before_write(self):
        site = self.root / "site"
        (site / "journal").mkdir(parents=True)
        entry = self.root / "entry.md"
        entry.write_text("---\ndate: ../../pwn\n---\n# Safe note")
        with mock.patch.object(journal, "run_llm", return_value=("# Safe note\n", "fake")), \
                mock.patch.object(journal, "git_commit"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, journal.cmd_publish(str(entry), None, str(site)))
        self.assertFalse((self.root / "pwn-safe-note.md").exists())
        self.assertEqual([], list((site / "journal").iterdir()))

    def test_auth_forms_scrubbed_before_model_and_save(self):
        text = ("# Safe choice\nAuthorization: Basic ZmFrZV91c2VyOmZha2VfcGFzcw==\n"
                "postgresql://fake_user:fake_pass@localhost:5432/demo\nKeep choice.")
        with mock.patch.object(journal.shutil, "which", return_value="claude"), \
                mock.patch.object(journal, "run_claude", return_value=text) as provider:
            body, _ = journal.run_llm(text)
        for clean in (provider.call_args.args[0], body):
            self.assertNotIn("ZmFrZV91c2VyOmZha2VfcGFzcw==", clean)
            self.assertNotIn("fake_pass", clean)
            self.assertIn("Keep choice.", clean)

    def test_replace_refs_cannot_hide_outgoing_secret(self):
        root = self.repo()
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")
        baseline = self.git(remote, "rev-parse", "main")
        clean = self.git(root, "rev-parse", "HEAD:base.md")
        (root / "entry.md").write_text("password=fake_replace_42")
        self.git(root, "add", "entry.md")
        self.git(root, "commit", "-m", "safe message")
        self.git(root, "-c", "user.email=recorder@localhost", "commit", "--amend", "--reset-author", "--no-edit")
        unsafe = self.git(root, "rev-parse", "HEAD:entry.md")
        self.git(root, "replace", unsafe, clean)
        def run(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        self.assertFalse(journal.git_push(str(root), run))
        self.assertEqual(baseline, self.git(remote, "rev-parse", "main"))


if __name__ == "__main__":
    unittest.main()
