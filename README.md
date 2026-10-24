# Journal Recorder

Keep short work notes in private Markdown repo. One shared core scrubs known secrets before model call, temp file and save. Exact output files pass Git scan before commit. Full outgoing history checked before push.

Recorder writes notes. [decision-ledger-setup](https://github.com/GauravRatnawat/decision-ledger-setup) builds read site from those notes. Real journal repo and history stay private. This repo holds code and fake tests only.

## Agent support

| Tool | Capture path | Verified here |
| --- | --- | --- |
| Claude Code | Stop and PostCompact transcript hooks | Fake payload and core tests |
| Codex CLI | Notify, exact thread ID plus cwd match | Fake rollout test, no unrelated fallback |
| Cursor | afterAgentResponse final text | Official field fixture, temp install test |
| Gemini CLI | AfterAgent prompt plus final reply | Official field fixture, temp install test |
| Copilot CLI and editor | Shared manual skill and stdin summary | Shared core and APM install test |
| OpenCode and other agents | Shared manual skill or stdin summary | Core independent of agent |

Cursor and Gemini capture text supplied by hook. No whole transcript parser claimed. Copilot Stop exposes transcript path, but record schema not verified here. Use manual skill there. No live end to end smoke run claimed for agent apps. Child agents use manual summary with own identity; automatic child transcript capture absent.

## Install reviewed code

Need Python 3.10+, Git, Bash. Python 3.11+ for full test suite. Claude CLI needed for automatic summary generation. Manual `record` needs no model CLI.

```sh
git clone https://github.com/GauravRatnawat/journal-recorder-agent.git
cd journal-recorder-agent
git checkout FULL_REVIEWED_COMMIT_SHA
python3 -m unittest discover -s tests
bash install.sh --agents claude,codex,cursor,gemini
```

Pick only tools wanted. Default `bash install.sh` picks Claude and Codex. `--agents manual` installs shared core and skill with no hook config changes. Restart tool after install. Installer runs from local checkout only; old pipe from mutable `main` rejected. Review checkout before install.

Core lands at `~/.claude/hooks/journal.py`. Shared skill lands at `~/.agents/skills/journal-recorder`. Existing hook entries kept. Existing root Codex notify kept; installer prints notice. Codex allows one notify command, so chain recorder yourself only after review if another notify exists.

Hook config locations: Claude `~/.claude/settings.json`, Cursor `~/.cursor/hooks.json`, Gemini `~/.gemini/settings.json`, Codex `~/.codex/config.toml`. Cursor may import Claude hooks too. Pick one route for capture; project dedup reduces repeat entries but does not lock concurrent writers.

This repo update does not change already installed hooks. Run installer when ready to roll out reviewed version.

## Private journal path and Git

Default root: `~/claude-journal`. To change:

```sh
printf '%s\n' '~/Documents/my-journal' > ~/.claude/.journal-folder
```

Use PRIVATE repo for real notes. Start from private repo clone with existing remote branch, then point config there. Recorder uses `origin` and current branch. It requires one identical fetch and push URL, fetches branch baseline, checks ancestry and scans outgoing objects, commit headers and paths. Missing branch, diverged history, unknown destination, secret match or scan error blocks push. No auto pull, merge or history rewrite.

Recorder stages only current entry, project `INDEX.md` and `HOME.md`. Digest stages one digest file. Public publish stages one post plus post index. Existing staged data blocks commit. Other working files stay local. Recorder uses generic Git identity `Journal Recorder <recorder@localhost>`.

Old unpushed commits can block sync even when latest files look clean. Deleting secret in new commit does not erase older secret. Review history yourself. Recorder never rewrites journal history.

## Privacy filter

Pipeline:

```text
Agent text → deterministic scrub → temp/model → scrub reply and metadata
→ Markdown → exact file scan → commit → outgoing history scan → origin push
```

Builtins match private keys, common GitHub/OpenAI/AWS/Slack token shapes, emails, Bearer credentials and common secret assignments. Add private org names, hosts, paths and ticket patterns to local `~/.claude/.journal-redact`:

```text
AcmeCorp => internal-org
registry.acme.internal => internal-registry
re:PROJ-\d+ => <ticket>
```

Keep real rules file out of Git. Example file here uses fake names. Literal match ignores case. `re:` means Python regex. Rule order matters. Replacement cannot leave any rule match behind. Bad regex, unreadable policy or residual match blocks flow. Missing policy deliberately uses builtins only. Public publish requires rules file too.

Pattern scan does not prove text private. It cannot infer all client names, business facts, arbitrary secret prose or encoded secrets. Review what agents summarize. Private Git and model calls both send data off machine. Cloudflare Access protects website reads, not model or Git traffic.

Model failure skips entry. No raw transcript fallback. Provider stderr not logged. Existing old entries untouched. Digest and publish scrub old input before model call. Direct `finalize` blocked; manual agents must use `record`.

## Model provider

Default generation: Claude CLI, tools disabled, MCP empty, hooks disabled, no session persistence, fresh temp cwd. Uses configured `MODEL` in `journal.py`. Prompt goes over stdin. No live provider call made by tests.

Codex generation fallback needs explicit `JOURNAL_ALLOW_CODEX=1`. It uses read-only sandbox. Codex CLI has no blanket tool-disable config, so this mode has weaker isolation and can read files allowed by its sandbox. Leave off for strict text-only generation. Codex session capture works with Claude as summary writer; capture agent and writer model separate fields.

## Manual summary from any agent

Run from project being recorded. Use `check` first if avoiding duplicate entry:

```sh
python3 ~/.claude/hooks/journal.py check
python3 ~/.claude/hooks/journal.py record <<'JSON'
{"agent":"copilot","cwd":"/path/to/project","session_id":"session-id","summary":"# Safe choice\n\n**In one line:** Keep shared safe save path.\n\n## Tags\n#journal #privacy #automation"}
JSON
```

Core owns metadata and saved path. Do not write raw entry then call old finalize. Prefer short choice, reason, result and next step. Leave secrets out before submission.

```sh
python3 ~/.claude/hooks/journal.py resolve-dir
python3 ~/.claude/hooks/journal.py digest --days 7
```

Markdown remains source of truth. Open journal folder as Obsidian vault if wanted. `HOME.md` has optional Dataview queries. Website renderer lives in separate setup repo.

## Optional Microsoft APM

[Microsoft APM](https://github.com/microsoft/apm) installs shared skill across agent tools. It does not normalize transcript payloads or make hooks universal. Root `SKILL.md`, `journal.py` and `apm.yml` form portable manual package.

From project where skill should land:

```sh
apm install 'GauravRatnawat/journal-recorder-agent#FULL_REVIEWED_COMMIT_SHA' --target claude,codex,copilot,cursor,gemini
```

APM skill carries `journal.py` beside `SKILL.md`; use that engine path if direct install absent. No hook auto-activation from APM package. Native hooks use reviewed direct installer. This avoids aliasing one event into incompatible tool payloads and duplicate hook routes.

Verified with APM 0.30.0: isolated local consumer install for five targets, core shipped to `.agents/skills/journal-recorder-agent` and `.claude/skills/journal-recorder-agent`, fake `record` smoke passed in both. GitHub pin install needs published commit. No user-scope APM config changed during checks.

## Legacy public publish

Separate old static post format, not private decision ledger deploy. Set site path in `~/.claude/.journal-site`; target needs `journal/` folder. Review denylist before use:

```sh
python3 ~/.claude/hooks/journal.py publish /path/to/entry.md --site /path/to/public-site
```

Needs local rules file and successful generic rewrite. Scrub runs before model and after reply. Shared Git gate still applies. Do not treat model rewrite as approval that prose safe.

## Checks

```sh
python3 -m py_compile journal.py
bash -n install.sh
python3 -W error::ResourceWarning -m unittest discover -s tests
```

Tests use fake credentials, temp HOME and local bare Git remotes. No real transcript upload, live model call or live hook install. See [plan](docs/superpowers/plans/2026-10-24-safe-shared-recorder.md) for change scope.
