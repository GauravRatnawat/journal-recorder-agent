# Safe Shared Recorder Plan

Goal: one safe summary path for agent hooks and manual use. APM optional install path. Real journals stay private.

## Rules

Keep Python stdlib. Keep old CLI entry points where safe. Leave live hooks and settings alone. Use fake data and temp Git repos in tests. No raw fallback. No whole repo staging. No claim that pattern scan catches all secrets.

## Tasks

1. Shared filter. Builtin secret shapes plus local denylist. Bad rules block. Scrub before temp file, model call, and saved output. Scan final text for residual matches. Tests first, one behavior per cycle.
2. Safe save. Failed model means skip entry. Metadata and paths use same filter. Manual agents submit summary to core. Old finalize blocks direct sync. Weekly digest and public publish use same filter.
3. Git gate. Exact owned files only. Reject unrelated staged changes and symlinks. Commit only safe text. Check all outgoing commits, messages, paths and changed blobs before push. No auto merge. Use explicit origin and current branch. Missing remote baseline means block existing history upload.
4. Session adapters. Bind Codex to exact thread and cwd. Keep Claude hooks. Add verified Gemini and Cursor payload support. Copilot support only where full payload contract verified. Manual stdin summary works from any agent.
5. Package. Direct local installer copies whole core. Fix root TOML notify insertion. Optional APM skill and target hook files. Avoid universal event alias claiming universal transcript schema.
6. Docs and checks. README support matrix, privacy limits, model providers, migration and APM steps. Run fake end to end checks. Fresh security and Python review before release.

## Test order

Each cycle: one failing behavior test, RED commit, minimum fix, suite pass, GREEN commit. Continue cycles without review pause under user instruction to finish without more questions. Never push raw fixtures or live data. Use generic maintainer author for public commits.

## Review focus

Replacement reintroduces secret. Invalid rules or unreadable config. Unrelated staged data and older outgoing secrets. Session from wrong cwd or thread. Hook payload lacks useful text. Installer runs twice with TOML tables. Model failure cannot write transcript.

## Progress

Baseline: 18 tests pass. Installed recorder matches repo. Privacy audit found save and push gaps, no prior leak proved. Branch: feat/safe-shared-recorder.

Shared filter, safe save, exact session adapters, reviewed local installer and portable APM manual skill complete. APM 0.30.0 local consumer passed five target install and both deployed core smoke checks. Live hooks unchanged.

Final review fixes proved RED then GREEN: Git replace bypass, Basic auth and URL login, publish date escape, symlink outputs, existing dashboard ownership, YAML quotes, scanned commit snapshot, isolated fetch baseline, failed sync status and root writer lock. Extra hook log symlink gap fixed same way.

Ruling: APM ships manual skill only. Native hooks stay in direct installer because event aliases do not define transcript schema. Cost: manual invoke for Copilot and unverified tools.

Ruling: root lock uses Unix flock. Target macOS and Linux. Cost: Windows needs future lock adapter. Busy writer exits for later retry. Failed sync keeps local entry and leaves dedup open; manual retry can create second entry.

Checks: 62 fake tests pass, 82% line coverage. Python compile, Bash syntax and diff whitespace pass. No live provider call, real transcript upload or machine config change. No prior exposure proved.

Release: feature branch pushed. Remote GitHub APM pin smoke blocked by automatic approval review before command ran. Local five target smoke passed earlier. Remote package install remains unverified. Main merge and live hook rollout not done.
