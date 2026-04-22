# journal-recorder — Claude Code Agent

Automatically records your coding sessions as rich, shareable markdown journal entries. Triggers at conversation end, milestones, and on every `/compact`.

Each entry includes: what was worked on, decisions made, commands run, problems solved, and action items — written so anyone with zero prior context can understand it.

Entries are saved to `~/claude-journal/YYYY-MM-DD_HH-MM_<title>.md`.

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

### 2. Enable auto-journaling on compaction

```bash
mkdir -p ~/.claude/hooks
curl -o ~/.claude/hooks/post-compact-journal.sh \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/post-compact-journal.sh
chmod +x ~/.claude/hooks/post-compact-journal.sh
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
    ]
  }
}
```

The hook reads the full conversation transcript and uses `claude -p` to generate a proper journal entry after each compaction (both `/compact` and auto-compact).

---

## Usage

**Automatic** — the agent fires on its own when:
- You signal the session is ending ("we're done", "looks good", "let me go implement this")
- A major milestone is reached
- Every `/compact` or auto-compaction (with the hook above)

**Manual:**
```
Use the journal-recorder agent to log this session.
```

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
