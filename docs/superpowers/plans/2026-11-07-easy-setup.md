# Easy Setup Plan

> Agent work: use executing-plans. One failing behavior per RED commit, smallest GREEN change, full suite after each cycle.

**Goal:** One copyable command starts guided setup. New users save local notes without GitHub setup.

**Architecture:** Keep stdlib Python core and existing hook installer. New setup.py asks tools, journal folder and optional existing Git clone sync, previews writes, backs up changed config and checks result. Pinned bootstrap.sh fetches exact archive and checks fixed SHA256 before running setup. Local mode skips journal Git commit and push, keeps scrub, lock and dedup. Legacy config without mode stays Git.

**Tech Stack:** Python 3.10+, Bash, curl, stdlib tarfile/hashlib/urllib. macOS and Linux.

**Spec:** User approved chat flow: detect agents, Enter defaults, ~/journal, show hooks, backup config, quick check, optional private Git sync. APM stays advanced. No real hooks changed during tests.

## Global Constraints

* Real journals and history stay private. No raw fallback.
* New setup local by default. Existing configured root and mode kept by default.
* Fixed download version and checksum. No mutable main code pipe.
* Keep unrelated .serena and .idea changes out.
* Temp HOME, fake data and local Git remotes only.

## Review Focus

* Existing config and root must survive rerun or cancelled setup.
* Existing Codex notify must stay; warn route not active.
* Invalid JSON, symlinks or bad folder must block before hook mutation.
* Git choice must validate existing origin branch and matching URLs without creating or uploading repo.
* Bad download hash or archive path must block execution.

## Task 1: Local note success

Files: journal.py, tests/test_setup.py.
Produces: journal_sync_mode() reads ~/.claude/.journal-sync, defaults git; sync_journal(root, message, paths) skips Git in local mode.

* [ ] RED test local record saves scrubbed note, sets marker, returns zero and makes no Git commit.
* [ ] GREEN minimum local mode plus write/digest routing. Keep publish Git gate unchanged.
* [ ] RED test invalid mode blocks and absent config stays git.
* [ ] GREEN reject unknown mode, keep legacy behavior. Full suite.

## Task 2: Guided setup

Files: setup.py, install.sh, tests/test_setup.py.
Consumes: .journal-folder and .journal-sync config from Task 1.
Produces: bash install.sh --setup. Existing --agents route stays supported.

* [ ] RED temp HOME flow accepts defaults, detects installed tool dirs, writes ~/journal and local mode, preserves unrelated hooks with backup.
* [ ] GREEN wizard prompts, preview/apply, config backups and quick checks. Full suite.
* [ ] RED cancellation leaves files untouched.
* [ ] GREEN stage validation before writes. Full suite.
* [ ] RED bad JSON, unsafe symlink or invalid folder blocks before writes.
* [ ] GREEN preflight all outputs and config. Full suite.
* [ ] RED optional Git requires existing clone, origin and remote branch; keeps existing mode on rerun.
* [ ] GREEN validate Git choice, warn existing Codex notify. Full suite.

## Task 3: Checked bootstrap

Files: bootstrap.sh, tests/test_setup.py.
Consumes: tested setup commit archive with fixed SHA256.
Produces: pinned bootstrap file for one copyable install command. Read prompts from /dev/tty when piped.

* [ ] RED corrupted archive cannot run installer.
* [ ] GREEN download to private temp dir, check hash and safe archive paths before extract/run. Full suite.
* [ ] RED archive links and traversal rejected.
* [ ] GREEN restrict archive regular files and directories under single root. Full suite.

## Task 4: Docs and page

Files: README.md, docs/index.html, docs/llms.txt.

* [ ] Put one pinned install command first. Show short setup flow and local privacy model.
* [ ] Explain manual summaries need no model; auto summaries need Claude CLI.
* [ ] Move clone, tests, APM and sync detail to advanced steps. Keep limits accurate.
* [ ] Run suite, syntax, coverage, browse phone/desktop, and fresh code/security review.
* [ ] Commit scoped files and push feature branch. Live merge/deploy needs explicit user request for this change.

## Rulings and progress

Ruling: execute inline under user request to implement. No extra plan approval pause. Use existing branch, no worktree requested. Cost: unrelated files remain in checkout, stage exact paths only.

Ruling: Git option uses existing clone. No GitHub login, repo creation or upload inside setup. Cost: new Git repo setup stays advanced.
