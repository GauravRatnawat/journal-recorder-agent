---
name: journal-recorder-agent
description: Use when user asks to save session journal or record work done. Send short safe summary through recorder core.
---

# Journal Recorder

Use shared safe core. Never write journal Markdown straight to repo. Never call old finalize. Never copy raw transcript, secrets, tool output dumps or private names into summary.

Run from project being recorded. Direct install engine at `$HOME/.claude/hooks/journal.py`. APM root skill ships `journal.py` beside this file. Pick that file if direct engine absent.

Check recent entry first:

```sh
python3 "$HOME/.claude/hooks/journal.py" check
```

If SKIP, stop unless user asks new entry now. Write brief summary under 400 words. Keep choice, reason, gotcha, result and next step. Use short prose. Omit empty parts. End with `## Tags` and 3 to 6 tags. No real keys, passwords, emails, employer or client names. Private Git still sends data off machine. Pattern filter cannot catch all prose leaks.

Send JSON on stdin. Use safe shell heredoc. JSON needs `agent`, `cwd`, `session_id`, `summary`. `cwd` must be actual project path. `summary` holds Markdown string. JSON escaping must stay valid.

```sh
python3 "$HOME/.claude/hooks/journal.py" record <<'JSON'
{"agent":"copilot","cwd":"/path/to/project","session_id":"session-id","summary":"# Safe choice\n\n**In one line:** Keep one safe summary path.\n\n## Tags\n#privacy #journal #automation"}
JSON
```

For APM copy, replace engine path in commands with `journal.py` beside this SKILL.md. Do not search transcript stores. Do not install hooks without user ask. Engine owns file path, frontmatter, index and Git gate. Report core result. Exit failure means blocked; never claim push done from local save alone.

Agent identity field: `agent: [which agent you are: claude-code, codex, cursor, opencode, gemini-cli, copilot]`.
