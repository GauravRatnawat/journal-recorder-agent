---
name: journal-recorder
description: Use when user asks to save session journal. Send safe summary through shared recorder core.
---

# Journal Recorder

Run from project being recorded:

```sh
python3 "$HOME/.claude/hooks/journal.py" check
```

SKIP means recent entry exists. Stop unless user asks new entry now.

Write brief Markdown summary. Keep choice, reason, result, gotcha and next step. Under 400 words. Short prose, caveman voice. End with `## Tags` and 3 to 6 tags. Omit empty parts. No raw transcript, keys, passwords, emails, private org names or tool output dumps. Private Git still sends data off machine.

Send JSON on stdin. Core owns paths, frontmatter, index, filter and Git gate. Never write entry straight to repo. Never call old finalize.

```sh
python3 "$HOME/.claude/hooks/journal.py" record <<'JSON'
{"agent":"codex","cwd":"/path/to/project","session_id":"session-id","summary":"# Safe choice\n\n**In one line:** Keep safe summary.\n\n## Tags\n#journal #privacy #automation"}
JSON
```

Set actual cwd and running agent. Keep JSON escaped. Use quoted heredoc. `agent: [which agent you are: claude-code, codex, cursor, opencode, gemini-cli, copilot]`.

Report core result. Local save does not prove push. No direct Git fallback if gate blocks. Pattern scan cannot prove all prose safe.
