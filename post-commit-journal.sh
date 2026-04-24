#!/usr/bin/env bash
# post-commit git hook — universal journal recorder
# Works with any AI coding tool (Claude Code, Cursor, Copilot, Aider, Windsurf, etc.)
# Install: see install-git-hook.sh or README.md

set -euo pipefail

JOURNAL_DIR="${JOURNAL_DIR:-$HOME/claude-journal}"
JOURNAL_MAX_DIFF_KB="${JOURNAL_MAX_DIFF_KB:-20}"
_HINT_FILE="$HOME/.journal-recorder/.hinted"
_LOG_FILE="/tmp/journal-recorder.log"
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Source lib modules ────────────────────────────────────────────────────────
# shellcheck source=lib/redact.sh
source "$_SCRIPT_DIR/lib/redact.sh"
# shellcheck source=lib/prompts.sh
source "$_SCRIPT_DIR/lib/prompts.sh"
# shellcheck source=lib/llm-backend.sh
source "$_SCRIPT_DIR/lib/llm-backend.sh"

# ── Slug helper ───────────────────────────────────────────────────────────────
_make_slug() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9 ]/ /g' \
    | tr -s ' ' '-' \
    | sed 's/^-//; s/-$//' \
    | cut -c1-60 \
    | sed 's/-$//'
}

# ── Minimal fallback entry (no LLM) ──────────────────────────────────────────
_write_fallback_entry() {
  local date_human="$1" repo="$2" branch="$3" hash="$4" commit_msg="$5" diff_stat="$6" outfile="$7"
  printf '# %s\n\n**Date:** %s\n**Repo:** %s | **Branch:** %s | **Commit:** %s\n\n## Commit Message\n\n%s\n\n## Files Changed\n\n```\n%s\n```\n' \
    "$commit_msg" "$date_human" "$repo" "$branch" "$hash" "$commit_msg" "$diff_stat" \
    > "$outfile"
}

# ── Main logic (runs in background) ──────────────────────────────────────────
_main() {
  # Skip merge commits
  if git rev-parse -q --verify HEAD^2 &>/dev/null; then
    echo "[journal-recorder] skipping merge commit" >&2
    return 0
  fi

  # Skip rebase / amend / cherry-pick
  local reflog_action="${GIT_REFLOG_ACTION:-}"
  if [[ "$reflog_action" =~ rebase|amend|cherry-pick ]]; then
    echo "[journal-recorder] skipping ($reflog_action)" >&2
    return 0
  fi

  # Per-repo opt-out
  if [[ "$(git config --local --get journal.skip 2>/dev/null || true)" == "true" ]]; then
    echo "[journal-recorder] skipping (journal.skip=true)" >&2
    return 0
  fi

  # Ignore-file opt-out
  local ignore_file="$HOME/.journal-recorder/ignore"
  local repo_path
  repo_path="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  if [[ -f "$ignore_file" ]]; then
    while IFS= read -r pattern; do
      [[ -z "$pattern" || "$pattern" == \#* ]] && continue
      # shellcheck disable=SC2254
      case "$repo_path" in $pattern)
        echo "[journal-recorder] skipping (matched ignore: $pattern)" >&2
        return 0
        ;;
      esac
    done < "$ignore_file"
  fi

  # Gather context
  local repo branch hash author commit_msg
  repo="$(basename "$repo_path")"
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
  hash="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
  author="$(git log -1 --format='%an <%ae>' 2>/dev/null || echo 'unknown')"
  commit_msg="$(git log -1 --format='%s' 2>/dev/null || echo 'unknown')"

  # Get diff (handle first commit — no HEAD~1)
  local diff_stat raw_diff
  if git rev-parse HEAD~1 &>/dev/null; then
    diff_stat="$(git diff --stat HEAD~1 HEAD 2>/dev/null || true)"
    raw_diff="$(git diff HEAD~1 HEAD 2>/dev/null || true)"
  else
    diff_stat="$(git show --stat HEAD 2>/dev/null | tail -n +2 || true)"
    raw_diff="$(git show HEAD 2>/dev/null || true)"
  fi

  # Redact secrets
  local safe_diff
  safe_diff="$(redact_diff "$raw_diff")"

  # Truncate if oversized
  local max_bytes=$(( JOURNAL_MAX_DIFF_KB * 1024 ))
  local diff_bytes=${#safe_diff}
  if (( diff_bytes > max_bytes )); then
    safe_diff="${safe_diff:0:$max_bytes}"$'\n\n[... diff truncated — '"$(( diff_bytes / 1024 ))"'KB total, showing first '"$JOURNAL_MAX_DIFF_KB"'KB ...]'
  fi

  # Prepare output path
  local date_human ts slug outfile
  date_human="$(date '+%Y-%m-%d %H:%M')"
  ts="$(date '+%Y-%m-%d_%H-%M')"
  mkdir -p "$JOURNAL_DIR"

  # No-LLM hint (once)
  local backend
  backend="$(detect_backend)"
  if [[ "$backend" == "none" && ! -f "$_HINT_FILE" ]]; then
    mkdir -p "$(dirname "$_HINT_FILE")"
    touch "$_HINT_FILE"
    cat >&2 <<'HINT'
[journal-recorder] No LLM backend found. Install one to get AI-written entries:
  - claude CLI:  https://claude.ai/code
  - llm CLI:     pip install llm
  - Anthropic:   export ANTHROPIC_API_KEY=sk-ant-...
  - OpenAI:      export OPENAI_API_KEY=sk-...
Writing minimal template entry instead.
HINT
  fi

  # Build prompt and generate
  local prompt journal
  if [[ "$backend" != "none" ]]; then
    prompt="$(build_journal_prompt "$repo" "$branch" "$hash" "$author" "$commit_msg" "$diff_stat" "$safe_diff")"
    journal="$(generate_journal "$JOURNAL_SYSTEM_PROMPT" "$prompt" 2>/dev/null || true)"
  fi

  # Determine title for slug
  local title_line
  if [[ -n "${journal:-}" ]]; then
    title_line="$(echo "$journal" | grep -m1 '^# ' | sed 's/^# //' || true)"
  fi
  [[ -z "${title_line:-}" ]] && title_line="$commit_msg"
  slug="$(_make_slug "$title_line")"
  [[ -z "$slug" ]] && slug="session"

  outfile="$JOURNAL_DIR/${ts}_${slug}.md"
  # Avoid collisions
  local counter=2
  while [[ -f "$outfile" ]]; do
    outfile="$JOURNAL_DIR/${ts}_${slug}_${counter}.md"
    (( counter++ ))
  done

  if [[ -n "${journal:-}" ]]; then
    echo "$journal" > "$outfile"
    echo "[journal-recorder] saved: $outfile" >&2
  else
    _write_fallback_entry "$date_human" "$repo" "$branch" "$hash" "$commit_msg" "$diff_stat" "$outfile"
    echo "[journal-recorder] saved fallback entry: $outfile" >&2
  fi
}

# ── Fork to background, return immediately ───────────────────────────────────
( _main ) >> "$_LOG_FILE" 2>&1 &
disown
exit 0
