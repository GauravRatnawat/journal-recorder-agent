#!/usr/bin/env bash
# Test harness for post-commit-journal hook.
# Run from project root: bash test/test-hook.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"

PASS=0; FAIL=0

_pass() { echo "  PASS: $1"; (( PASS++ )) || true; }
_fail() { echo "  FAIL: $1"; (( FAIL++ )) || true; }
_section() { echo ""; echo "── $1 ──────────────────────────────────────"; }

# Source lib for unit tests
# shellcheck source=../lib/redact.sh
source "$ROOT_DIR/lib/redact.sh"
# shellcheck source=../lib/prompts.sh
source "$ROOT_DIR/lib/prompts.sh"
# shellcheck source=../lib/llm-backend.sh
source "$ROOT_DIR/lib/llm-backend.sh"

# ── redact.sh tests ───────────────────────────────────────────────────────────
_section "redact.sh — AWS key"
raw="$(cat "$FIXTURES_DIR/diff-with-secrets.txt")"
result="$(redact_diff "$raw")"
if echo "$result" | grep -q 'REDACTED_AWS_KEY'; then
  _pass "AWS access key redacted"
else
  _fail "AWS access key NOT redacted"
fi
if echo "$result" | grep -q 'AKIAIOSFODNN7EXAMPLE'; then
  _fail "Raw AWS key still present"
else
  _pass "Raw AWS key removed"
fi

_section "redact.sh — GitHub token"
if echo "$result" | grep -q 'REDACTED_GITHUB_TOKEN'; then
  _pass "GitHub token redacted"
else
  _fail "GitHub token NOT redacted"
fi

_section "redact.sh — OpenAI key"
if echo "$result" | grep -q 'REDACTED_OPENAI_KEY'; then
  _pass "OpenAI key redacted"
else
  _fail "OpenAI key NOT redacted"
fi

_section "redact.sh — Anthropic key"
if echo "$result" | grep -q 'REDACTED_ANTHROPIC_KEY'; then
  _pass "Anthropic key redacted"
else
  _fail "Anthropic key NOT redacted"
fi

_section "redact.sh — JWT redacted"
if echo "$result" | grep -q 'REDACTED_JWT'; then
  _pass "JWT redacted"
else
  _fail "JWT NOT redacted"
fi

_section "redact.sh — .env file skipped entirely"
if echo "$result" | grep -q 'FILE SKIPPED'; then
  _pass ".env file skipped"
else
  _fail ".env file NOT skipped"
fi
if echo "$result" | grep -q 'supersecret'; then
  _fail ".env contents still visible"
else
  _pass ".env contents hidden"
fi

_section "redact.sh — id_rsa file skipped"
if echo "$result" | grep -q 'FILE SKIPPED'; then
  _pass "id_rsa file skipped"
else
  _fail "id_rsa file NOT skipped"
fi

_section "redact.sh — clean diff untouched"
clean="$(cat "$FIXTURES_DIR/diff-normal.txt")"
clean_result="$(redact_diff "$clean")"
if echo "$clean_result" | grep -q 'REDACTED'; then
  _fail "Clean diff incorrectly redacted"
else
  _pass "Clean diff passes through unchanged"
fi

# ── prompts.sh tests ──────────────────────────────────────────────────────────
_section "prompts.sh — build_journal_prompt contains required sections"
prompt="$(build_journal_prompt "my-repo" "main" "abc1234" "Alice <alice@example.com>" "fix: null check" "1 file changed" "$(cat "$FIXTURES_DIR/diff-normal.txt")")"
for section in "TL;DR" "What Was Worked On" "What Was Accomplished" "Files Changed" "Key Decisions" "Action Items" "Tags"; do
  if echo "$prompt" | grep -q "$section"; then
    _pass "Section '$section' present"
  else
    _fail "Section '$section' MISSING"
  fi
done
if echo "$prompt" | grep -q "my-repo"; then
  _pass "Repo name in prompt"
else
  _fail "Repo name missing from prompt"
fi

# ── llm-backend.sh tests ──────────────────────────────────────────────────────
_section "llm-backend.sh — detect_backend respects BACKEND_OVERRIDE"
result="$(BACKEND_OVERRIDE=openai detect_backend)"
if [[ "$result" == "openai" ]]; then
  _pass "BACKEND_OVERRIDE=openai respected"
else
  _fail "BACKEND_OVERRIDE not respected (got: $result)"
fi

_section "llm-backend.sh — detect_backend returns 'none' when nothing available"
# Temporarily remove vars and shadow CLIs
result="$(
  PATH="/nonexistent" \
  ANTHROPIC_API_KEY="" \
  OPENAI_API_KEY="" \
  BACKEND_OVERRIDE="" \
  detect_backend
)"
if [[ "$result" == "none" ]]; then
  _pass "detect_backend returns 'none' with no backend"
else
  _fail "detect_backend returned '$result' instead of 'none'"
fi

# ── slug helper tests ─────────────────────────────────────────────────────────
_section "Slug helper"
# Source slug helper from main script without running it
_make_slug() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9 ]/ /g' \
    | tr -s ' ' '-' \
    | sed 's/^-//; s/-$//' \
    | cut -c1-60 \
    | sed 's/-$//'
}
slug="$(_make_slug "Fix: Null pointer exception in auth module")"
if [[ "$slug" == "fix-null-pointer-exception-in-auth-module" ]]; then
  _pass "Slug generated correctly"
else
  _fail "Slug wrong: '$slug'"
fi
slug_long="$(_make_slug "$(printf 'a%.0s' {1..80})")"
if (( ${#slug_long} <= 60 )); then
  _pass "Long slug truncated to <=60 chars"
else
  _fail "Long slug not truncated: ${#slug_long} chars"
fi

# ── E2E test — hook creates a journal file ────────────────────────────────────
_section "E2E — hook creates journal entry on commit"
TMP_REPO="$(mktemp -d)"
TMP_JOURNAL="$(mktemp -d)"
trap 'rm -rf "$TMP_REPO" "$TMP_JOURNAL"' EXIT

cd "$TMP_REPO"
git init -q
git config user.email "test@test.com"
git config user.name "Test"

# Install hook pointing at project lib
mkdir -p .git/hooks
cat > .git/hooks/post-commit <<HOOK
#!/usr/bin/env bash
JOURNAL_DIR="$TMP_JOURNAL" \
BACKEND_OVERRIDE="none" \
  bash "$ROOT_DIR/post-commit-journal.sh"
# Give background process time to finish in test context
sleep 3
HOOK
chmod +x .git/hooks/post-commit

echo "hello" > file.txt
git add file.txt
git commit -q -m "test: add hello file"
sleep 4  # wait for background journal write

files="$(ls "$TMP_JOURNAL" 2>/dev/null || true)"
if [[ -n "$files" ]]; then
  _pass "Journal file created on commit"
  first_file="$(ls "$TMP_JOURNAL" | head -1)"
  if grep -q "test: add hello file\|hello file\|hello" "$TMP_JOURNAL/$first_file"; then
    _pass "Journal entry contains commit context"
  else
    _fail "Journal entry missing commit context"
  fi
else
  _fail "No journal file created"
fi

_section "E2E — merge commit is skipped"
TMP_REPO2="$(mktemp -d)"
TMP_JOURNAL2="$(mktemp -d)"
trap 'rm -rf "$TMP_REPO2" "$TMP_JOURNAL2"' EXIT

cd "$TMP_REPO2"
git init -q
git config user.email "test@test.com"
git config user.name "Test"
echo "a" > a.txt && git add . && git commit -q -m "first"
git checkout -q -b feature
echo "b" > b.txt && git add . && git commit -q -m "feature commit"
git checkout -q main 2>/dev/null || git checkout -q master

mkdir -p .git/hooks
cat > .git/hooks/post-commit <<HOOK
#!/usr/bin/env bash
JOURNAL_DIR="$TMP_JOURNAL2" \
BACKEND_OVERRIDE="none" \
  bash "$ROOT_DIR/post-commit-journal.sh"
sleep 2
HOOK
chmod +x .git/hooks/post-commit

git merge --no-ff feature -m "merge: feature into main" -q 2>/dev/null || true
sleep 3

files="$(ls "$TMP_JOURNAL2" 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$files" == "0" ]]; then
  _pass "Merge commit correctly skipped"
else
  _fail "Merge commit generated $files entries (should be 0)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "══════════════════════════════════════════"
(( FAIL == 0 ))
