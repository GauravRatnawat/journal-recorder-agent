# Journal Recorder

Keep short work notes in local Markdown. One command starts guided setup. GitHub sync optional. Shared core scrubs known secrets before model call, temp file and save.

## Quick start

Need macOS or Linux, Python 3.10+ and curl. Run in terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/273ff5039c9106e60a59d49c20909b9502d513c9/bootstrap.py | python3 -I -
```

Setup detects agent tools, asks notes folder and shows planned hook changes. Press Enter for defaults. New users get `~/journal` with local mode. No GitHub login or repo needed. Changed config files get private backups. Cancel before apply leaves config untouched. Failed setup check rolls file changes back.

```text
Journal Recorder setup
Agents: claude,codex
Save notes here? ~/journal
Sync to existing private Git clone? n
Apply setup? y
Check passed. Restart agents.
```

Download uses fixed commit. Bootstrap checks archive SHA256 and rejects archive links or path escapes before running setup. Command trusts pinned bootstrap from this repo. No mutable `main` installer.

Automatic summaries need Claude CLI installed and signed in. Manual skill needs no model CLI. Local mode skips Git commit and push; automatic summaries still send scrubbed text to model service. Setup makes no live model call.

Run check later:

```sh
python3 ~/.claude/hooks/journal.py doctor
```

To add tools or change folder and sync later, run same setup command again. Old tool hooks stay active, even when left out on rerun. To stop capture for old tool, remove its recorder hook from config. Existing folder and mode shown as defaults. Backup paths print after apply. Restore chosen backup to original path to undo that file. Existing Codex notify kept; setup warns if recorder needs manual chaining.

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

## Advanced: local checkout

Need macOS or Linux, Python 3.10+ and Bash. Git needed for sync. Existing Codex config safe edits need Python 3.11+. Root lock uses Unix `flock`. Python 3.11+ for full test suite. Claude CLI needed for automatic summary generation. Manual `record` needs no model CLI.

```sh
git clone https://github.com/GauravRatnawat/journal-recorder-agent.git
cd journal-recorder-agent
git checkout 1b64eeb4460d99b5d9d9988d9d56b080f6be4b00
bash install.sh
```

Default `bash install.sh` opens same guided setup. Advanced `bash install.sh --agents claude,codex,cursor,gemini` installs explicit hooks and keeps current folder and sync mode. `--agents manual` installs core and skill only. Existing configs validated before writes and changed files backed up. Explicit route does not choose local mode for you. Restart tool after install.

Core lands at `~/.claude/hooks/journal.py`. Shared skill lands at `~/.agents/skills/journal-recorder`. Existing hook entries kept. Existing root Codex notify kept; installer prints notice. Codex allows one notify command, so chain recorder yourself only after review if another notify exists.

Hook config locations: Claude `~/.claude/settings.json`, Cursor `~/.cursor/hooks.json`, Gemini `~/.gemini/settings.json`, Codex `~/.codex/config.toml`. Cursor may import Claude hooks too. Pick one route for capture. Root lock covers save, generated files, commit and push. Busy writer exits with retry notice. Project dedup applies after successful local save or Git sync.

This repo update does not change already installed hooks. Run installer when ready to roll out reviewed version.

## Private journal path and Git

Guided setup defaults new users to `~/journal`, local mode. Old installs without sync config keep legacy Git mode and `~/claude-journal` fallback. Effective mode lives in `~/.claude/.journal-sync`: `local` or `git`. Unknown mode blocks save. Run guided setup to switch safely.

For optional Git sync, choose existing private clone as notes folder, answer yes and confirm repo private. Setup checks clone root, HEAD, branch and matching origin URLs with tracked origin branch. Setup makes no Git upload and cannot prove repo visibility. Next note uses full outgoing scan.

Advanced path override:

```sh
printf '%s\n' '~/Documents/my-journal' > ~/.claude/.journal-folder
```

Use PRIVATE repo for real notes. Start from private repo clone with existing remote branch, then point config there. Recorder uses `origin` and current branch. It requires one identical fetch and push URL, fetches branch baseline, checks ancestry and scans outgoing objects, commit headers and paths. Missing branch, diverged history, unknown destination, secret match or scan error blocks push. No auto pull, merge or history rewrite.

Recorder commits current entry and generated project `INDEX.md`. `HOME.md` included only when recorder creates it. Existing dashboard edits stay local. Digest commits one digest file. Public publish commits one post plus post index. Existing staged data blocks commit. Private index holds exact scanned bytes; Git index lock plus checked branch update prevents reread race. Recorder uses generic Git identity `Journal Recorder <recorder@localhost>`.

Output writes reject symlinks. New entry uses exclusive create. Generated files use safe replace through held parent directory. Metadata strings use YAML compatible JSON quotes. Failed sync returns nonzero, keeps local Markdown and leaves dedup marker unchanged. Retry may create new entry; inspect local files and Git state before manual retry.

Old unpushed commits can block sync even when latest files look clean. Deleting secret in new commit does not erase older secret. Review history yourself. Recorder never rewrites journal history.

## Privacy filter

Pipeline:

```text
Agent text → deterministic scrub → temp/model → scrub reply and metadata
→ local Markdown
→ optional Git: exact file scan → commit → outgoing history scan → origin push
```

Builtins match private keys, common GitHub/OpenAI/AWS/Slack token shapes, emails, Bearer and Basic credentials, URL login fields and common secret assignments. Add private org names, hosts, paths and ticket patterns to local `~/.claude/.journal-redact`:

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
apm install 'GauravRatnawat/journal-recorder-agent#8665f4bbf108edda89b61f85f70a016f6485637f' --target claude,codex,copilot,cursor,gemini
```

APM skill carries `journal.py` beside `SKILL.md`; use that engine path if direct install absent. No hook auto-activation from APM package. Native hooks use reviewed direct installer. This avoids aliasing one event into incompatible tool payloads and duplicate hook routes.

Verified with APM 0.30.0: GitHub install at `8665f4bbf108edda89b61f85f70a016f6485637f` passed for `claude,codex,copilot,cursor,gemini` in temp home. Core shipped to `.agents/skills/journal-recorder-agent` and `.claude/skills/journal-recorder-agent`. Both copies passed fake `record`, secret scrub and push to local bare Git remote. Local consumer install passed too. No real user hooks or settings changed. Agent app capture still needs live smoke.

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

Release check record: 80 tests passed, 83% production Python line coverage across core, setup and bootstrap. Earlier shared core release had 62 tests, 82% line coverage, from 18 test baseline. These record past checks, no fresh run claimed.

Checked setup payload: `1b64eeb4460d99b5d9d9988d9d56b080f6be4b00`. Archive SHA256: `0d602c1a82e8f64f3f3f71334f70563509f3484066446ef3243789ce139de316`. Bootstrap: `273ff5039c9106e60a59d49c20909b9502d513c9`. Future release must update both pins and archive hash. Checked remote archive install and manual local record passed in temp HOME. Exact documented curl pipe passed real terminal flow, local mode, no Git repo. Archive checks cover hash, links, path escapes, extra roots and size limit; piped source reads prompts from `/dev/tty`.

APM 0.30.0 release pin `8665f4bbf108edda89b61f85f70a016f6485637f` passed GitHub install for `claude,codex,copilot,cursor,gemini` on 2026-11-06 in temp HOME. Local consumer passed too. Both deployed core copies passed fake record, scrub and push to local bare Git remote.

Core checks cover extraction with tool calls and elision, project slug and worktree lookup, frontmatter, dedup, generated indexes and digest windows. Privacy checks cover invalid or unreadable rules, replacement leaving secrets, model input and reply scrub, model failure with no raw fallback, metadata quotes, output and log symlinks, publish date path escape, exact scanned commit bytes, old outgoing secrets, Git replace bypass, Basic auth, URL login, isolated fetch baseline, existing dashboard ownership, failed sync status and root writer lock.

Setup checks cover local record and digest without Git, legacy and unknown modes, agent detection, hook merge, private backups, secret free preview, cancel before apply, bad JSON and symlink rejection. Failed apply, check or interrupt restores file bytes and modes. Git option checks existing clone, matching origin URLs and tracked branch with no upload. Existing root Codex notify stays, including quoted key; nested notify does not hide root route. Doctor checks folder, mode and privacy rules with no model call.

Python compile, Bash syntax, doc shell syntax, JSON-LD parse and diff whitespace passed for prior releases. Page checked at 375, 768 and 1440 widths with no overflow or console errors; advanced details opened and phone and desktop screenshots viewed. Fresh code, Python and security reviews covered prior releases; easy setup checks followed user TDD waiver, no full RED then GREEN claim.

Tests use fake credentials, temp HOME and local bare Git remotes. No real transcript upload, live model call or real user hook/config change. Claude and Codex capture checks use fake session data; Cursor and Gemini use documented field fixtures and temp install checks. Native app capture still needs live smoke. Copilot and unverified tools use manual summary. Automatic child transcript capture absent. Past privacy audit found gaps but did not prove prior exposure; checks cannot prove all prose safe.
