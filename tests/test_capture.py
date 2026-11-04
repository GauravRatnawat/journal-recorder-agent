"""Fake agent logs check capture boundaries. No real session reads."""

import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for patch in (
            mock.patch.object(journal, "journal_root", return_value=str(self.root / "notes")),
            mock.patch.object(journal, "REDACT_CONFIG", str(self.root / "missing")),
            mock.patch.object(journal, "log_line"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_claude_log_keeps_work_and_skips_injected_context(self):
        path = self.root / "claude.jsonl"
        items = [
            {"message": {"role": "system", "content": "skip system"}},
            {"message": {"role": "user", "content": "user work " * 10}},
            {"message": {"role": "assistant", "content": [
                {"type": "text", "text": "assistant work " * 10}, None,
                {"type": "tool_use", "name": "Bash", "input": {"command": "git status", "description": "check state"}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "demo.py"}},
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
            {"message": {"role": "user", "content": "<system-reminder>skip injected context"}},
        ]
        path.write_text("bad json\n" + "\n".join(map(json.dumps, items)))
        body, count = journal.extract_digest(str(path))
        self.assertEqual(2, count)
        for text in ("USER: user work", "ASSISTANT: assistant work", "TOOL[Bash]: git status", "TOOL[Edit]: demo.py", "TOOL[Read]"):
            self.assertIn(text, body)
        self.assertNotIn("skip", body)
        self.assertEqual(("", 0), journal.extract_digest(str(self.root / "absent")))

    def test_codex_log_keeps_work_and_tool_calls(self):
        path = self.root / "codex.jsonl"
        items = [{"type": "session_meta", "payload": {"id": "thread"}}]
        for role in ("user", "assistant", "system"):
            items.append({"type": "response_item", "payload": {"type": "message", "role": role,
                         "content": [{"type": "input_text", "text": role + " work " * 15}]}})
        items.extend([
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<user_instructions>skip this"}]}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "demo.py"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "git status"}},
        ])
        path.write_text("bad json\n" + "\n".join(map(json.dumps, items)))
        body, count = journal.extract_codex_digest(str(path))
        self.assertEqual(2, count)
        self.assertIn("TOOL[apply_patch]: demo.py", body)
        self.assertIn("TOOL[shell]: git status", body)
        self.assertNotIn("system work", body)
        self.assertNotIn("skip this", body)
        self.assertEqual(("", 0), journal.extract_codex_digest(str(self.root / "absent")))
        self.assertEqual({"id": "thread"}, journal.codex_session_meta(str(path)))
        self.assertEqual({}, journal.codex_session_meta(str(self.root / "absent")))

    def test_budget_keeps_head_and_tail(self):
        with mock.patch.object(journal, "DIGEST_BUDGET_CHARS", 90):
            body = journal.elide([str(n) * 10 for n in range(20)])
        self.assertTrue(body.startswith("0000000000"))
        self.assertTrue(body.endswith("19191919191919191919"))
        self.assertIn("items elided", body)
        self.assertEqual("one\n\ntwo", journal.elide(["one", "two"]))

    def test_claude_hooks_gate_trivial_missing_and_duplicate_sessions(self):
        transcript = self.root / "session.jsonl"
        transcript.write_text("\n".join(json.dumps({"message": {"role": "user", "content": "safe work " * 15}}) for _ in range(4)))
        payload = {"cwd": str(self.root), "session_id": "thread", "transcript_path": str(transcript)}
        with mock.patch.object(journal, "spawn_writer") as spawn:
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                self.assertEqual(0, journal.cmd_hook("stop"))
            self.assertEqual(1, spawn.call_count)
            self.assertIn("safe work", spawn.call_args.args[4])
            spawn.reset_mock()
            with mock.patch.object(journal, "is_duplicate", return_value=True), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                journal.cmd_hook("stop")
            for data in ("bad json", "[]", "{}", json.dumps({**payload, "transcript_path": "absent"})):
                with mock.patch.object(sys, "stdin", io.StringIO(data)):
                    journal.cmd_hook("stop")
            with mock.patch.object(journal, "extract_digest", return_value=("short", 1)), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                journal.cmd_hook("stop")
            spawn.assert_not_called()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": str(self.root), "summary": "safe compact summary"}))):
                journal.cmd_hook("compact")
            self.assertEqual("safe compact summary", spawn.call_args.args[4])

    def test_codex_hook_needs_exact_session_and_enough_work(self):
        payload = json.dumps({"cwd": str(self.root), "thread-id": "thread", "type": "agent-turn-complete"})
        meta = {"id": "thread", "cwd": str(self.root)}
        with mock.patch.object(journal, "spawn_writer") as spawn, mock.patch.object(journal, "find_codex_rollout", return_value=("rollout", meta)), mock.patch.object(journal, "extract_codex_digest", return_value=("safe work", 4)):
            self.assertEqual(0, journal.cmd_hook_codex(payload))
            self.assertEqual("thread", spawn.call_args.args[2])
            spawn.reset_mock()
            with mock.patch.object(journal, "is_duplicate", return_value=True):
                journal.cmd_hook_codex(payload)
            with mock.patch.object(journal, "extract_codex_digest", return_value=("short", 1)):
                journal.cmd_hook_codex(payload)
            with mock.patch.object(journal, "extract_codex_digest", return_value=("", 0)):
                journal.cmd_hook_codex(payload)
            with mock.patch.object(journal, "find_codex_rollout", return_value=(None, {})):
                for data in (payload, "bad json", "[]"):
                    journal.cmd_hook_codex(data)
            journal.cmd_hook_codex('{"type":"other"}')
            spawn.assert_not_called()

    def test_opted_in_codex_provider_uses_result_file_and_cleans_temp(self):
        paths = []
        def run(argv, **kwargs):
            path = Path(argv[argv.index("--output-last-message") + 1])
            paths.append(path)
            path.write_text("# Safe result")
            return subprocess.CompletedProcess(argv, 0, "events", "")
        with mock.patch.object(journal.subprocess, "run", side_effect=run):
            self.assertEqual("# Safe result", journal.run_codex("safe prompt"))
        self.assertFalse(paths[0].exists())
        for response in (subprocess.CompletedProcess([], 1, "", "private error"), OSError("private error"), subprocess.TimeoutExpired("codex", 1)):
            with mock.patch.object(journal.subprocess, "run", **({"side_effect": response} if isinstance(response, Exception) else {"return_value": response})):
                self.assertEqual("", journal.run_codex("safe prompt"))


if __name__ == "__main__":
    unittest.main()
