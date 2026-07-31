# journal-recorder — auto-journal for Claude Code & Codex

Automatically records your [Claude Code](https://claude.ai/code) and [Codex CLI](https://github.com/openai/codex) sessions as rich, shareable markdown journal entries. Triggers at conversation end, on every `/compact`, and after every Codex turn.

Each entry includes: what was worked on, commands run, files touched, decisions made, problems solved, and action items — written so anyone with zero prior context can understand it.

**Built for the human, not the agent.** AI sessions vanish the moment they end — a week later you can't remember which flag fixed the build or why you chose that architecture. This journal is *your* memory: remember what you did, find that command from three projects ago, hand a teammate the full story. It is **not** agent memory — Claude and Codex have their own memory systems for carrying context between sessions; this exists so *you* can remember and find things.

Entries are organized **per project**, indexed, git-tracked, **auto-pushed to GitHub**, and generated in the **background on Haiku** so your session never waits.

```
~/claude-journal/                         ← git repo, auto-pushed if remote set
├── my-repo/
│   ├── INDEX.md                          ← auto-maintained index
│   ├── 2026-07-17_14-30_auth-refactor.md ← session journals
│   ├── commits/                          ← per-commit journals (optional git hook)
│   └── .last-written                     ← per-project dedup marker
├── other-project/
├── digests/2026-W29.md                   ← weekly digests
└── .journal.log                          ← every run logged here
```

---

## Install

**Requirements:** [Claude Code](https://claude.ai/code) or [Codex CLI](https://github.com/openai/codex) (either works — generation prefers `claude -p`, falls back to `codex exec`), Python 3 (preinstalled on macOS)

**One command:**

```bash
curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/install.sh | bash
```

Installs the engine, both hooks, the agent, and merges the hook config into `~/.claude/settings.json` (existing hooks preserved). If Codex CLI is installed (`~/.codex` exists), it also wires the [Codex notify adapter](#codex-support) and skill. Idempotent — safe to re-run, also works from a local clone (`bash install.sh`).

<details>
<summary><strong>Manual install</strong> (what the script does, step by step)</summary>

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

</details>

### Add the mandate to CLAUDE.md (optional)

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
- **Git-tracked + auto-pushed** — the journal root is auto-initialized as a git repo; every entry is committed, and if a remote is configured it is pushed automatically. See [Sync to GitHub](#sync-to-github).
- **Never silent** — every run (written, skipped, failed) appends a line to `<journal-root>/.journal.log`. If `claude -p` fails, a fallback entry with the raw session digest is written instead of losing the session.

---

## Usage

**Automatic** — the hooks fire on their own:
- When Claude's turn ends after a substantive session (Stop hook)
- On every `/compact` or auto-compaction (PostCompact hook)
- After every Codex turn (notify hook — see [Codex support](#codex-support))

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

**Publish an entry to your website (one command):**
```bash
# one-time: point at your site repo (needs a journal/ folder with index.js)
echo "~/Dev/my-site" > ~/.claude/.journal-site

python3 ~/.claude/hooks/journal.py publish                    # latest entry, any project
python3 ~/.claude/hooks/journal.py publish --project my-repo  # latest entry of one project
python3 ~/.claude/hooks/journal.py publish path/to/entry.md   # specific entry
```
Converts the entry to your site's post format (frontmatter: title, date, tags, excerpt from the one-liner), drops internal tags and the Obsidian footer, regenerates the site's `journal/index.js`, commits, and pushes. Nothing publishes automatically — you pick what goes public.

### Redaction on publish

Journal entries keep real names — the journal is a private git repo, and specificity is what makes a reread useful. `publish` is where that gets scrubbed, in two layers:

1. **Genericize pass** (LLM) — rewrites prose that a pattern list cannot see: an employer's product name in a sentence becomes "the wrapper service". Best-effort.
2. **Rule pass** (deterministic) — runs *last*, so the LLM cannot reintroduce a banned term. This is the actual guarantee.

Rules live in `~/.claude/.journal-redact`, one per line. Literal matches are case-insensitive; a `re:` prefix makes the pattern a regex; without `=>` the match becomes `<redacted>`:

```
# ~/.claude/.journal-redact
acme-nemo-wrapper => the wrapper service
acme-mcp-proxy    => an internal proxy
AcmeCorp
re:JIRA-\d+       => <ticket>
re:\w+\.internal\.acme\.com => <internal-host>
```

Credential shapes and email addresses are stripped whether or not you have a rules file — private keys, `ghp_*`, `sk-*`, `AKIA*`, Slack `xox*` tokens. Title, tags and excerpt are all derived *after* redaction, so a name in the stored title cannot leak through frontmatter. Each run prints what it replaced:

```
redacted 3x  acme\-nemo\-wrapper -> the wrapper service
redacted 1x  JIRA-\d+ -> <ticket>
```

With no rules file, publish warns and applies only the built-in credential patterns. A malformed regex is skipped and logged to `.journal.log` rather than aborting the publish.

**Other commands:**
```bash
python3 ~/.claude/hooks/journal.py resolve-dir   # print journal root
python3 ~/.claude/hooks/journal.py check         # SKIP/PROCEED dedup verdict for cwd project
```

---

## Codex support

The same engine journals [Codex CLI](https://github.com/openai/codex) sessions. Codex has no Stop hook — instead its `notify` setting runs a program after every turn; the adapter locates the newest main-thread rollout in `~/.codex/sessions/`, extracts messages + tool calls (shell commands, function calls), and feeds the same pipeline. Entries get `source: codex`.

```bash
curl -o ~/.claude/hooks/codex-notify.sh \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/codex-notify.sh
chmod +x ~/.claude/hooks/codex-notify.sh
```

Add to `~/.codex/config.toml`:

```toml
notify = ["/Users/<you>/.claude/hooks/codex-notify.sh"]
```

Codex supports only **one** notify command — if you already have one, edit `codex-notify.sh` to call both (it's a two-line chain script).

Same dedup applies: Claude Code and Codex sessions in the same project share the per-project 30-minute marker, so you get one entry, not two.

**Optional — on-demand skill for Codex** (ask Codex "journal this session" anytime):

```bash
mkdir -p ~/.agents/skills/journal-recorder
curl -o ~/.agents/skills/journal-recorder/SKILL.md \
  https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/codex-skill/SKILL.md
```

---

## Obsidian integration

The **journal root itself is the vault** — open it directly:

```bash
open "obsidian://open?path=$(python3 ~/.claude/hooks/journal.py resolve-dir)"
```

Or manually in Obsidian: **Open folder as vault** → pick your journal root (default `~/claude-journal` — not a project subfolder, the root). `HOME.md` is the dashboard; each project is a folder inside the vault.

What you get out of the box:

- **Nested tags** — every entry is tagged `project/<repo>` and `source/<stop|codex|compact|agent>` plus content tags, so the tag pane becomes a filterable tree.
- **Wikilinks + graph** — each entry links `[[<project>/INDEX|<project>]]`; in graph view projects appear as hubs with sessions around them.
- **`HOME.md` dashboard** — auto-created once, never overwritten. Live tables of recent entries, open action items across all projects, and entries per project. Requires the community **Dataview** plugin (Settings → Community plugins → Dataview); without it the rest still works.
- **Frontmatter properties** — `title`, `project`, `date`, `source`, `tags` all show in Obsidian's properties panel and are queryable.

On mobile: install Obsidian + the **Obsidian Git** community plugin and clone your private journal repo — every entry pushed from your machine appears on your phone.

---

## Configure your journal folder

```bash
echo "~/Documents/my-journal" > ~/.claude/.journal-folder
```

All paths (hooks, agent, digest) read from this file. Default if unset: `~/claude-journal/`.

---

## Sync to GitHub

One-time setup — create a private repo and point the journal root at it:

```bash
cd "$(python3 ~/.claude/hooks/journal.py resolve-dir)"
gh repo create claude-journal --private --source . --push
```

(Or manually: create a private repo on GitHub, then `git remote add origin git@github.com:<you>/claude-journal.git && git push -u origin HEAD`.)

That's it. After every journal entry (hook, agent, or digest), `journal.py` commits and pushes to the first configured remote in the background. Push failures (offline, auth) are logged to `.journal.log` and never block the entry — the next successful push carries everything.

---

## How deduplication works

Each project folder has its own marker file `<journal-root>/<project>/.last-written`. Whichever trigger path fires first (Stop hook, PostCompact hook, Codex notify, or agent/skill) writes the journal and stamps the marker; the others see it is fresher than 30 minutes and skip. Sessions in *different* projects never block each other. Claude Code and Codex working on the same project share the marker — one entry, not two.

---

## Failure behavior

Nothing fails silently, and no session content is ever lost:

| Failure | Behavior |
|---|---|
| `claude -p` fails (token limit, rate limit, API error) | Fallback entry written with the raw session digest — messages, commands, files. Error logged. |
| Generation hangs | 300s timeout → same fallback entry |
| `claude` CLI missing or fails | Falls back to `codex exec` if Codex CLI installed; entry frontmatter records `model: codex-exec` |
| Both `claude` and `codex` missing | Same fallback entry |
| Terminal closed right after turn end | Writer is detached — it finishes, commits, and pushes anyway |
| Machine shutdown before writer finishes | No entry; log shows `spawned writer` without a matching `ok wrote` |
| Offline when pushing | Entry committed locally, push failure logged, next successful push carries the backlog |
| Malformed hook input / missing transcript | Clean skip, logged, never breaks your session |

Every run — written, skipped, or failed — appends one line to `<journal-root>/.journal.log`.

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

# PostCompact hook fired twice per session

**In one line:** Compaction journaling wrote duplicate entries because the hook had no
dedup window — fixed with a per-project marker file.

## The story
Set up auto-journal on compaction. Long session compact twice, so two entries land
minutes apart, near-identical. No marker meant every hook fire wrote...

## Why we chose what we chose
- **Marker file over a lock** — hook must exit fast, and a stale lock would silently
  kill journaling for good.

## Gotchas for whoever comes next
- Stop and PostCompact both fire on a long session. Dedup is not optional.

## Commands worth remembering
\```bash
python3 ~/.claude/hooks/journal.py check   # SKIP/PROCEED verdict, no side effects
\```

## Left undone
- [ ] ...

## Tags
`#claude-code` `#hooks` `#automation`
```

Entries stay short on purpose — under 400 words, no file table (git already records
that, exactly), reasoning over chronology. Voice is clipped and article-light so a
reread costs seconds. Real names are kept: the journal is a private git repo, and
[publish redacts](#redaction-on-publish) before anything reaches a public site.

---

## License

MIT
