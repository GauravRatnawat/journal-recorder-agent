# journal-recorder — Claude Code Agent

Automatically records your Claude Code sessions as rich, shareable markdown journal entries. Triggers at conversation end, milestones, and on every `/compact`.

Each entry includes: what was worked on, decisions made, commands run, problems solved, and action items — written so anyone with zero prior context can understand it.

Entries are saved to a folder of your choice (you're asked once on first use, default: `~/claude-journal/`).

---

## Install

**Requirements:** [Claude Code](https://claude.ai/code), `jq` (`brew install jq`)

### 1. Install the agent

```bash
mkdir -p ~/.claude/agents
curl -o ~/.claude/agents/journal-recorder.md \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/journal-recorder.md
```

Claude Code picks it up automatically — no restart needed.

### 2. Install both hooks

Both hooks fire automatically. PostCompact captures every `/compact`. Stop hook captures session end with a 30-minute deduplication guard so you never get duplicate entries.

```bash
mkdir -p ~/.claude/hooks

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
            "timeout": 90
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
            "timeout": 90
          }
        ]
      }
    ]
  }
}
```

### 3. Add the mandate to CLAUDE.md (optional but recommended)

This makes the main Claude agent proactively invoke journal-recorder at session end — a second layer on top of the Stop hook.

Add to `~/.claude/CLAUDE.md`:

```markdown
## Session Journaling — MANDATORY

Always invoke the `journal-recorder` agent before ending ANY session that involved
tool use, code changes, decisions, or meaningful work. Do not skip it, do not wait
to be asked.

Trigger signals: "thanks", "done", "bye", "looks good", "ship it", "we're done"
```

---

## Usage

**Automatic** — the agent fires on its own when:
- You signal the session is ending ("we're done", "looks good", "let me go implement this")
- A major milestone is reached
- Every `/compact` or auto-compaction (PostCompact hook)
- When Claude's turn ends after a substantive session (Stop hook, 30-min guard)

**Manual:**
```
Use the journal-recorder agent to log this session.
```

---

## Configure your journal folder

On first use, Claude asks where to save entries. To set or change it at any time:

```bash
echo "~/Documents/my-journal" > ~/.claude/.journal-folder
```

All three paths (agent, PostCompact hook, Stop hook) read from this file. Default if unset: `~/claude-journal/`.

---

## How deduplication works

All three trigger paths share a marker file `~/.claude/.journal-last-written`. Whichever fires first writes the journal and stamps the marker. The others see the marker is fresh and skip. This means you get exactly one entry per session regardless of which path triggered it.

---

## What the entries look like

```
~/claude-journal/2026-04-23_01-00_postcompact-hook-setup-and-fix.md
```

```markdown
# PostCompact Hook Setup and Fix

**Date:** 2026-04-23 01:00

## TL;DR
Configured Claude Code to auto-journal on compaction. Initial PreCompact + agent
hook failed (unsupported outside REPL). Switched to PostCompact + command hook
that reads the conversation transcript and generates a full entry via claude -p.

## What Was Worked On
...
## What Was Accomplished
- bullet list with file names
## Key Decisions
...
## Problems & Solutions
...
## Action Items
- [ ] ...
## Tags
`#claude-code` `#hooks` `#automation`
```

---

## License

MIT
