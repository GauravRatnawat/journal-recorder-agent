# Journal Recorder v2 — Design Spec

**Date:** 2026-07-17
**Status:** Approved approach A (single Python tool). Pending spec review.

## Problem

Current system = agent md + 2 bash hooks. Five defects:

1. Extraction blind to tool calls — journal template demands "Commands Run" / "Files Modified" but `claude -p` never sees tool_use/tool_result. Sections empty or hallucinated.
2. Triple duplication — folder resolution, dedup guard, slug gen, transcript extraction copy-pasted across agent md + both hooks. Already drifted (Stop hook has substance check, PostCompact none).
3. Global 30-min dedup marker — two projects same hour → second session silently skipped.
4. Stop hook blocks turn end (synchronous `claude -p`, up to ~30 s) and swallows failures via `2>/dev/null || true`.
5. Tail-only context — last 30 msgs × 800 chars, 8 k cap. Long session journals cover only the tail.

## Goals (user-selected)

- Journal quality: full-session extraction including tool calls.
- Reliability: per-project dedup, no silent failures, logging, fallback entry.
- Architecture cleanup: one source of truth, hooks thin.
- Organization: per-project subfolders.
- Cost/latency: background generation on Haiku.
- Keep both paths: hooks (auto safety net) + agent (on-demand rich entry).
- Features: per-project INDEX.md, weekly digest, git-tracked journal root, YAML frontmatter.

## Architecture

One file: `journal.py` (Python 3, stdlib only, no deps). Hooks become thin wrappers. Agent md references the same tool.

```
Stop hook ──┐
            ├─► journal.py hook {stop|compact}   (fast path, exits <1 s)
Compact ────┘         │
                      ├─ dedup check (per project+session, 30 min)
                      ├─ substance check (≥4 meaningful msgs; both hooks now)
                      ├─ extract transcript → digest (text + tool calls)
                      └─ spawn detached:  journal.py write --digest-file …
                                              │
                                              ├─ claude -p --model haiku → markdown
                                              ├─ frontmatter + entry file
                                              ├─ INDEX.md update
                                              ├─ git add+commit
                                              └─ marker update, logging
journal.py digest --days 7  (manual/cron) ─► digests/YYYY-Wnn.md
```

## Components

### 1. Config & paths

- Journal root: `~/.claude/.journal-folder` contents if present, else `~/claude-journal`. (Unchanged behavior.)
- Project slug: basename of hook input `cwd`, lowercased, non-alnum → `-`. Fallback `misc` when cwd missing.
- Entry path: `<root>/<project>/YYYY-MM-DD_HH-MM_<title-slug>.md`.
- Log file: `<root>/.journal.log` — every run appends one line (ok/skip/error + reason).

### 2. Dedup (fixes global-marker collision)

- Marker: `<root>/<project>/.last-written` containing `<unix-ts> <session-id>`.
- Skip when: same project AND age < 30 min. Different project never blocks.
- Marker written only after successful entry write.
- Agent md instructs agent to check/update the same marker via `journal.py`.

### 3. Extraction (fixes blind-to-tools + tail-only)

From transcript JSONL:

- Text messages: user/assistant, skip `<local-command…>` / `<system-reminder…>`, skip <10 chars.
- Tool calls: `tool_use` blocks →
  - `Bash`: record command + description.
  - `Edit`/`Write`/`NotebookEdit`: record file path + action.
  - Other tools: name only.
- Format: chronological digest, `USER:` / `ASSISTANT:` / `TOOL[Bash]: <cmd>` lines.
- Budget: 40 k chars. Over budget → keep head 1/3 + tail 2/3, elide middle with `[... N items elided ...]`.
- Substance check: ≥4 messages with >50 chars of text — applied to BOTH hook types now.

### 4. Generation (fixes blocking + cost)

- Fast path writes digest to temp file, spawns detached `journal.py write` (double-fork / `start_new_session=True`, stdio → log), exits. Turn ends instantly.
- Writer calls `claude -p --system-prompt … --model claude-haiku-4-5-20251001 --output-format text`.
- Prompt: required sections — TL;DR, What Was Accomplished, Commands & Scripts Run, Files Created/Modified, Key Decisions, Problems & Solutions, Action Items, Tags.
- Failure: stderr captured to log; fallback entry written containing raw digest excerpt (never silently lost).

### 5. Entry format (frontmatter)

```markdown
---
project: my-repo
date: 2026-07-17T14:30:00+02:00
session_id: abc123
source: stop        # stop | compact | agent
model: claude-haiku-4-5-20251001
tags: [python, debugging]
---

# <title from generated H1>
… generated body …
```

- Tags parsed from generated "## Tags" section into frontmatter list (best-effort; empty list ok).

### 6. INDEX.md (per project)

- `<root>/<project>/INDEX.md`, newest first:
  `- 2026-07-17 14:30 — [Title](2026-07-17_14-30_slug.md) — #tag1 #tag2`
- Regenerated from entry frontmatter on each write (idempotent, survives manual deletion of entries).

### 7. Git tracking

- On writer run: if `<root>/.git` missing → `git init` + initial commit.
- After entry + index write: `git add -A && git commit -m "journal: <project> — <title>"`.
- Git failures logged, never block entry write.

### 8. Weekly digest

- `journal.py digest [--days 7] [--project X]` — collects entries in window (frontmatter dates), one `claude -p` roll-up → `<root>/digests/YYYY-Wnn.md`, committed.
- Manual invocation; README documents optional cron/launchd line. No scheduler built.

### 9. Hooks & agent md

- `post-stop-journal.sh` → `exec python3 "$(dirname "$0")/journal.py" hook stop`.
- `post-compact-journal.sh` → `exec python3 "$(dirname "$0")/journal.py" hook compact`.
- `journal-recorder.md`: keep persona + template; storage/dedup/index sections now instruct the agent to run `journal.py` helpers (`resolve-dir`, dedup check, index update) instead of inline bash; add frontmatter requirement; agent writes with `source: agent`.

### 10. Testing

- `test_journal.py`, pytest, pure-function coverage: extraction (incl. tool_use, elision), slug, frontmatter render/parse, dedup decision, index line render/regen, digest window selection.
- Subprocess/`claude -p` boundaries mocked. TDD one-by-one per global rules.

## Error handling summary

| Failure | Behavior |
|---|---|
| transcript missing/unreadable | log skip, exit 0 |
| claude -p fails/empty | fallback raw-digest entry + log |
| git fails | log, entry still saved |
| marker/index corrupt | treat as absent, rebuild |
| hook JSON malformed | log skip, exit 0 (never break Claude session) |

## Out of scope

- No search UI, no embeddings, no sync service.
- No scheduler for digest (documented cron only).
- GitHub Pages site untouched.