# Easy Setup Plan

> Agent work: use executing-plans. User waived TDD after first RED commit: "no tdd continue". Checks below name shipped behavior, not claimed RED cycles.

**Goal:** One copyable command starts guided setup. New users save local notes without GitHub setup.

**Architecture:** Stdlib Python core and guided setup.py. Detect tools, ask notes folder and optional existing Git clone, preview writes, back up config and check result. Pinned bootstrap.py checks archive SHA256 before setup. Local mode skips journal Git commit and push, keeps scrub, lock and dedup. Missing mode keeps legacy Git.

**Tech Stack:** Python 3.10+, Bash, curl, stdlib tarfile/hashlib/urllib. macOS and Linux. Existing Codex TOML safe edits and full tests need Python 3.11+.

**Spec:** User approved chat flow: detect agents, Enter defaults, ~/journal, show hooks, back up config, quick check, optional private Git sync. APM stays advanced. No real hooks changed during tests.

## Global Constraints

* Real journals and history stay private. No raw fallback.
* New setup local by default. Existing root and mode kept as defaults.
* Fixed download version and checksum. No mutable main code pipe.
* Keep unrelated .serena and .idea changes out.
* Temp HOME, fake data and local Git remotes only.

## Task 1: Local note success

Files: journal.py, tests/test_setup.py.

* [x] Local record saves scrubbed note, sets marker and skips Git.
* [x] Local digest skips Git. Public publish keeps own Git gate.
* [x] Unknown mode blocks. Missing mode stays Git.

## Task 2: Guided setup

Files: setup.py, install.sh, tests/test_setup.py.

* [x] Detect tools. New defaults: ~/journal and local mode.
* [x] Keep unrelated hooks. Private backups before apply.
* [x] Preview paths and hook events without config secrets.
* [x] Cancel, bad JSON and unsafe symlinks block before apply.
* [x] Failed check, apply error or interrupt restores old file bytes and modes.
* [x] Git option checks existing clone, matching origin URLs and tracked branch. No upload.
* [x] Keep root Codex notify, including quoted key. Nested notify does not hide root route.
* [x] Keep legacy root and Git defaults on upgrade.
* [x] Doctor checks folder, mode and privacy rules without model call.

## Task 3: Checked bootstrap

Files: bootstrap.py, tests/test_setup.py.

* [x] Fixed archive pin and SHA256 before extract or run.
* [x] Reject links, traversal, extra roots and oversized archive.
* [x] Read prompts from /dev/tty when source piped through stdin.
* [x] Checked remote payload smoke in temp HOME, manual local record.
* [x] Exact documented curl pipe command passed real terminal flow in temp HOME. Local mode, no Git repo.

Setup payload: 1b64eeb4460d99b5d9d9988d9d56b080f6be4b00.
Archive SHA256: 0d602c1a82e8f64f3f3f71334f70563509f3484066446ef3243789ce139de316.
Bootstrap: 273ff5039c9106e60a59d49c20909b9502d513c9.

## Task 4: Docs and page

Files: README.md, docs/index.html, docs/llms.txt.

* [x] One pinned command first. Show short flow and local privacy limits.
* [x] Manual summaries need no model CLI. Auto summaries need signed-in Claude CLI.
* [x] Git, clone and APM details stay advanced.
* [x] State rerun adds routes. Old hooks stay active until removed from config.
* [x] 80 tests pass. Production Python line coverage 83% across core, setup and bootstrap.
* [x] Python and shell syntax checks pass. Doc shell blocks and JSON-LD parse.
* [x] Browser checked 375, 768 and 1440 widths. No page overflow or console errors. Advanced steps open. Phone and desktop screenshots viewed.
* [x] Fresh code and security review done. Concrete defects fixed and covered. Final docs review gap fixed.

## Rulings and progress

Ruling: execute inline under user request to implement. No extra plan approval pause. Existing feature branch, no worktree requested. Cost: unrelated files remain in checkout, stage exact paths only.

Ruling: Git option uses existing clone. No login, repo creation or upload inside setup. Cost: new Git repo setup stays advanced.

Ruling: user waived TDD after first RED commit. Keep checks, drop RED/GREEN pause. Cost: later tests prove behavior, not test-first order.

Ruling: bootstrap.py replaces planned bootstrap.sh. Stdlib handles hash and safe archive extraction in one file. Cost: Python must exist before download command runs.

Ruling: bootstrap pin fetches earlier tested setup payload. Cost: future release must update both pins and archive hash.

No live provider or native app capture smoke claimed. Real user hooks untouched. This change still needs merge before public page deploy.
