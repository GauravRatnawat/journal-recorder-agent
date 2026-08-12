---
name: journal-recorder
description: Record a journal entry summarizing the current session. Use when the user asks to journal, save, or log the session, or at a natural stopping point after significant work.
---

# Journal Recorder

Write a structured markdown journal entry for this session. Works from any coding agent — the engine is called by absolute path and needs nothing agent-specific.

**Claude Code and Codex journal automatically** via Stop/compact hooks. There, use this skill only when the user explicitly asks for an entry, or wants one now instead of waiting for the hook.

**Every other agent** (Cursor, OpenCode, Gemini CLI, Copilot, …) has no hook wired — this skill is the only way an entry gets written. Offer one at a natural stopping point after significant work.

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
agent: [which agent you are: claude-code, codex, cursor, opencode, gemini-cli, copilot]
tags: [tag1, tag2, tag3]
---

# [Specific title naming what actually happened]

**In one line:** [one sentence a reader could repeat to someone else]

## The story
[1-3 paragraphs: what prompted this, what turned out to be true, where it landed. Lead with whatever was surprising.]

## Why we chose what we chose
- [Decision] — [the reasoning or trade-off]

## Gotchas for whoever comes next
- [Traps, surprises, things that cost time]

## Commands worth remembering
[Fenced block. Only commands worth running again — repro, verification, one-liners that were hard to get right.]

## Left undone
- [ ] [Open threads with enough context to pick up cold]

## Tags
`#tag1` `#tag2` `#tag3`
```

Write for a developer who wasn't there and has never seen this project. They should finish it understanding what changed and why, not holding an inventory of what moved.

**Voice — caveman.** Short words, broken grammar, no fluff. Drop articles (a/an/the) where it still reads, drop filler (just, really, basically, simply) and hedging. Fragments fine. "Rename surface two stale-state bug" not "The rename surfaced two stale-state bugs". Technical terms stay exact — names, flags, error strings, numbers are never reworded. Code blocks verbatim. Terse, not vague: every fact survives, only the grammar goes.

- Prose, not bullet soup. The story section is paragraphs.
- No table of files created/modified. Git records that exactly and forever; a hand-copied table only drifts. Name a file when the reader needs it to follow the point.
- Skip any section with nothing real to say. A missing section beats a padded one.
- Under 400 words before the tag line.
- Explain the reasoning, not the transcript. "We chose X because Y proved wrong" earns its place; "then I ran the tests" does not.
- Keep real names, paths, and error messages — this journal is private. `journal.py publish` redacts before anything reaches a public site.

## Step 3 — Finalize

```bash
python3 "$HOME/.claude/hooks/journal.py" finalize
```

This stamps the dedup marker, rebuilds the project's `INDEX.md`, and commits + pushes the journal repo. Then report the saved file path and a 1-2 sentence summary.
