---
name: journal-recorder
description: Record a journal entry summarizing the current session. Use when the user asks to journal, save, or log the session, or at a natural stopping point after significant work.
---

# Journal Recorder (Codex)

Write a structured markdown journal entry for this session. Automatic journaling already happens via the Codex notify hook — use this skill only when the user explicitly asks for a journal entry, or when they want one now instead of waiting for the hook.

## Step 1 — Idempotency check

```bash
python3 "$HOME/.claude/hooks/journal.py" check
```

- Output `SKIP: ...` → stop. Report: "Journal already written recently for this project — skipping duplicate."
- Output `PROCEED: <path>` → that path is the project's journal directory. Create it if missing and continue.

## Step 2 — Write the entry

File name: `<path>/YYYY-MM-DD_HH-MM_<short-topic-slug>.md`

Template:

```markdown
---
title: [Short descriptive title]
project: [project folder name]
date: [ISO timestamp]
source: agent
agent: codex
tags: [tag1, tag2, tag3]
---

# [Title]

## TL;DR
[2-4 sentences: what the session was about, what changed.]

## What Was Accomplished
- [Concrete bullets — file names, decisions, fixes]

## Commands & Scripts Run
[Significant commands verbatim in fenced code blocks.]

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|

## Key Decisions
- **Decision**: [what] — **Why**: [reasoning]

## Problems & Solutions
- **Problem**: [x] — **Solution**: [y]

## Action Items
- [ ] [Next steps with enough context to pick up cold]

## Tags
`#tag1` `#tag2` `#tag3`
```

Write for a reader with zero prior context. Preserve exact file paths, commands, and error messages. Synthesize — do not transcribe.

## Step 3 — Finalize

```bash
python3 "$HOME/.claude/hooks/journal.py" finalize
```

This stamps the dedup marker, rebuilds the project's `INDEX.md`, and commits + pushes the journal repo. Then report the saved file path and a 1-2 sentence summary.
