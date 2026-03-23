# journal-recorder — Claude Code Agent

A Claude Code subagent that automatically records your coding sessions as rich, searchable journal entries. Triggered proactively at the end of conversations or after significant milestones.

## What it does

After each session, the agent writes a structured markdown entry to `~/claude-journal/` capturing:

- Session summary and background context
- What was accomplished (with file names)
- Step-by-step flow (reproducible recipe)
- Every command and script run
- Key decisions and reasoning
- Problems encountered and solutions
- Action items and next steps
- Searchable tags

Entries are written for a "new engineer with zero prior context" — detailed enough to pick up exactly where you left off.

## Install

Copy the agent file to your Claude Code agents directory:

```bash
curl -o ~/.claude/agents/journal-recorder.md \
  https://raw.githubusercontent.com/<your-username>/journal-recorder-agent/main/journal-recorder.md
```

Or manually download `journal-recorder.md` and place it at:

```
~/.claude/agents/journal-recorder.md
```

That's it. Claude Code picks up agents automatically — no restart needed.

## Usage

The agent triggers automatically. Claude will invoke it:

- When you say things like "we're done", "thanks, looks good", or "let me go implement this"
- After a major milestone ("the authentication module is working now")
- Periodically during long sessions

You can also invoke it explicitly:

```
Use the journal-recorder agent to log this session.
```

## Journal storage

Entries are saved to `~/claude-journal/` with the naming format:

```
YYYY-MM-DD_HH-MM_<short-topic-slug>.md
```

Examples:
```
~/claude-journal/2024-01-15_15-45_react-hooks-debugging.md
~/claude-journal/2024-01-15_10-00_api-architecture-planning.md
```

## Customization

To change the journal storage location, edit the `## Storage Location` section in `journal-recorder.md` and update the path.

## Requirements

- [Claude Code](https://claude.ai/code) CLI

## License

MIT
