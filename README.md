# journal-recorder — Claude Code Agent

Automatically records your Claude Code sessions as rich, shareable markdown journal entries. Triggers at conversation end, milestones, and on every `/compact`.

Each entry includes: what was worked on, commands run, files touched, decisions made, problems solved, and action items — written so anyone with zero prior context can understand it.

Entries are organized **per project**, indexed, git-tracked, and generated in the **background on Haiku** so your session never waits.

```
~/claude-journal/
├── my-repo/
│   ├── INDEX.md                          ← auto-maintained index
│   ├── 2026-07-17_14-30_auth-refactor.md
│   └── .last-written                     ← per-project dedup marker
├── other-project/
├── digests/2026-W29.md                   ← weekly digests
└── .journal.log                          ← every run logged here
```

---

## Install

**Requirements:** [Claude Code](https://claude.ai/code), Python 3 (preinstalled on macOS)

### 1. Install the engine + hooks

```bash
mkdir -p ~/.claude/hooks

curl -o ~/.claude/hooks/journal.py \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/journal.py

curl -o ~/.claude/hooks/post-compact-journal.sh \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/post-compact-journal.sh
chmod +x ~/.claude/hooks/post-compact-journal.sh

curl -o ~/.claude/hooks/post-stop-journal.sh \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/post-stop-journal.sh
chmod +x ~/.claude/hooks/post-stop-journal.sh
```

Add to `~/.claude/settings.json` (merge into existing `"hooks"` if present):

```json
{
  "hooks": {
    "PostCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/post-compact-journal.sh",
            "statusMessage": "Saving journal entry...",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/post-stop-journal.sh",
            "statusMessage": "Saving journal entry...",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

The hook itself finishes in under a second — it extracts the transcript and spawns a detached background writer. Journal generation (via `claude -p` on Haiku) never blocks your session.

### 2. Install the agent (optional, for on-demand rich entries)

```bash
mkdir -p ~/.claude/agents
curl -o ~/.claude/agents/journal-recorder.md \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/journal-recorder.md
```

### 3. Add the mandate to CLAUDE.md (optional)

Makes the main Claude agent proactively invoke journal-recorder at session end — a second layer on top of the Stop hook. Add to `~/.claude/CLAUDE.md`:

```markdown
## Session Journaling — MANDATORY

Always invoke the `journal-recorder` agent before ending ANY session that involved
tool use, code changes, decisions, or meaningful work. Do not skip it, do not wait
to be asked.

Trigger signals: "thanks", "done", "bye", "looks good", "ship it", "we're done"
```

---

## What you get

- **Full-session extraction** — user/assistant messages **plus tool calls**: every Bash command and every file edited appear in the log fed to the journal writer, so "Commands Run" and "Files Modified" sections are real, not hallucinated. Long sessions keep head + tail with the middle elided at a 40k-char budget.
- **Per-project folders** — each repo gets its own subfolder and its own 30-minute dedup marker, so parallel work on two projects journals both.
- **YAML frontmatter** — `title`, `project`, `date`, `session_id`, `source`, `model`, `tags` on every entry. Obsidian-friendly, machine-readable.
- **INDEX.md per project** — regenerated on every write from entry frontmatter.
- **Git-tracked** — the journal root is auto-initialized as a git repo; every entry is committed. Push it wherever you like.
- **Never silent** — every run (written, skipped, failed) appends a line to `<journal-root>/.journal.log`. If `claude -p` fails, a fallback entry with the raw session digest is written instead of losing the session.

---

## Usage

**Automatic** — the hooks fire on their own:
- When Claude's turn ends after a substantive session (Stop hook)
- On every `/compact` or auto-compaction (PostCompact hook)

**Manual (rich agent entry):**
```
Use the journal-recorder agent to log this session.
```

**Weekly digest:**
```bash
python3 ~/.claude/hooks/journal.py digest --days 7            # all projects
python3 ~/.claude/hooks/journal.py digest --days 7 --project my-repo
```
Writes `<journal-root>/digests/YYYY-Wnn.md`. To automate, add a cron line:
```
0 18 * * FRI python3 $HOME/.claude/hooks/journal.py digest --days 7
```

**Other commands:**
```bash
python3 ~/.claude/hooks/journal.py resolve-dir   # print journal root
python3 ~/.claude/hooks/journal.py check         # SKIP/PROCEED dedup verdict for cwd project
```

---

## Configure your journal folder

```bash
echo "~/Documents/my-journal" > ~/.claude/.journal-folder
```

All paths (hooks, agent, digest) read from this file. Default if unset: `~/claude-journal/`.

---

## How deduplication works

Each project folder has its own marker file `<journal-root>/<project>/.last-written`. Whichever trigger path fires first (Stop hook, PostCompact hook, or agent) writes the journal and stamps the marker; the others see it is fresher than 30 minutes and skip. Sessions in *different* projects never block each other.

---

## What the entries look like

```
~/claude-journal/my-repo/2026-07-17_14-30_postcompact-hook-setup.md
```

```markdown
---
title: PostCompact Hook Setup and Fix
project: my-repo
date: 2026-07-17T14:30:00+02:00
session_id: abc123
source: stop
model: claude-haiku-4-5-20251001
tags: [claude-code, hooks, automation]
---

# PostCompact Hook Setup and Fix

## TL;DR
Configured Claude Code to auto-journal on compaction...

## What Was Accomplished
- bullet list with file names
## Commands & Scripts Run
## Files Created / Modified
## Key Decisions
## Problems & Solutions
## Action Items
- [ ] ...
## Tags
`#claude-code` `#hooks` `#automation`
```

---

## License

MIT
