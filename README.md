# journal-recorder

Automatically records your coding sessions as rich, shareable markdown journal entries.

Works with **any AI coding tool** — Claude Code, Cursor, GitHub Copilot, Aider, Windsurf, OpenCode, or plain `git`. Three install options:

- **[Option A](#option-a-universal-git-hook)** — Universal git hook (recommended — any tool)
- **[Option B](#option-b-claude-code-agent)** — Claude Code agent (manual trigger)
- **[Option C](#option-c-claude-code-postcompact-hook)** — Claude Code PostCompact hook (auto on `/compact`)

Entries are saved to `~/claude-journal/YYYY-MM-DD_HH-MM_<title>.md`.

---

## Option A: Universal Git Hook

Triggers on every `git commit`, in any repo, with any AI tool. Uses an LLM to write a structured journal entry from the diff and commit message.

### Prerequisites

- `bash`, `git`, `jq`, `curl`, `python3`
- At least one LLM backend (priority order):
  1. [`claude` CLI](https://claude.ai/code)
  2. [`llm` CLI](https://llm.datasette.io/) — `pip install llm`
  3. `ANTHROPIC_API_KEY` env var
  4. `OPENAI_API_KEY` env var
  - Without any backend, a minimal template entry is written instead.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/git-hook-universal/install-git-hook.sh | bash
```

This sets `git config --global core.hooksPath ~/.git-hooks-global` so the hook fires in every repo.

### What each entry looks like

```
~/claude-journal/2026-04-24_14-30_fix-null-pointer-in-auth-module.md
```

```markdown
# Fix Null Pointer in Auth Module

**Date:** 2026-04-24 14:30
**Repo:** my-app | **Branch:** main | **Commit:** abc1234

## TL;DR
Fixed a null pointer exception in the login flow when the user record is missing.

## What Was Worked On
- Authentication module — login function

## What Was Accomplished
- Added null check before `user.verify_password()`
- Added `audit_log("login", user.id)` call
- Added three new tests: success, wrong password, unknown user

## Files Changed
| File | Change |
|------|--------|
| src/auth.py | +6 / -1 |
| tests/test_auth.py | +10 / -0 |

## Key Decisions
Chose to raise ValueError (not return None) so callers can't silently ignore auth failure.

## Action Items
- [ ] Add rate limiting to login endpoint

## Tags
`auth` `null-check` `testing` `python`
```

### Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `JOURNAL_DIR` | `~/claude-journal` | Where entries are saved |
| `JOURNAL_MAX_DIFF_KB` | `20` | Max diff size before truncation |
| `JOURNAL_CLAUDE_MODEL` | `claude-sonnet-4-6` | Model for `claude` backend |
| `JOURNAL_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Model for direct Anthropic API |
| `JOURNAL_OPENAI_MODEL` | `gpt-4o-mini` | Model for OpenAI backend |
| `JOURNAL_LLM_MODEL` | _(llm default)_ | Model for `llm` CLI backend |
| `BACKEND_OVERRIDE` | — | Force a backend: `claude\|llm\|anthropic\|openai\|none` |

### Opt-out

```bash
# Skip journaling in one repo
git config journal.skip true

# Skip journaling in repos matching path globs
echo "$HOME/work/client-*" >> ~/.journal-recorder/ignore
```

### Troubleshoot

```bash
# See what the last hook run did
cat /tmp/journal-recorder.log

# Test the hook manually with no LLM
BACKEND_OVERRIDE=none bash ~/.git-hooks-global/post-commit-journal.sh
```

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/git-hook-universal/uninstall-git-hook.sh | bash
```

---

## Option B: Claude Code Agent

Manual trigger inside a Claude Code session. Say "use the journal-recorder agent" or let it fire automatically at session end / milestones.

**Requirements:** [Claude Code](https://claude.ai/code)

```bash
mkdir -p ~/.claude/agents
curl -o ~/.claude/agents/journal-recorder.md \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/journal-recorder.md
```

Claude Code picks it up automatically — no restart needed.

---

## Option C: Claude Code PostCompact Hook

Auto-journals on every `/compact` or auto-compaction. Reads the full conversation transcript and generates a richer entry than the git hook (conversation context vs. diff only).

**Requirements:** Claude Code, `jq`

```bash
mkdir -p ~/.claude/hooks
curl -o ~/.claude/hooks/post-compact-journal.sh \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/post-compact-journal.sh
chmod +x ~/.claude/hooks/post-compact-journal.sh
```

Add to `~/.claude/settings.json`:

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

---

## License

MIT
