#!/usr/bin/env bash
# Installs the universal journal-recorder git hook globally.
# Every git commit (in any repo) will generate a journal entry in ~/claude-journal/.
#
# Usage: curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/git-hook-universal/install-git-hook.sh | bash

set -euo pipefail

HOOKS_DIR="$HOME/.git-hooks-global"
REPO_BASE="https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/git-hook-universal"

_info()  { echo "[journal-recorder] $*"; }
_warn()  { echo "[journal-recorder] WARNING: $*" >&2; }
_error() { echo "[journal-recorder] ERROR: $*" >&2; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
_check_deps() {
  local missing=()
  for cmd in bash git jq curl python3; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done
  if (( ${#missing[@]} > 0 )); then
    _error "Missing required tools: ${missing[*]}. Install them and re-run."
  fi
}

# ── Check for existing core.hooksPath ────────────────────────────────────────
_check_hooks_path() {
  local existing
  existing="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  if [[ -z "$existing" ]]; then
    return 0  # unset — safe to proceed
  fi
  # Normalize ~ and $HOME
  local expanded="${existing/#\~/$HOME}"
  local our_path="${HOOKS_DIR/#\~/$HOME}"
  if [[ "$expanded" == "$our_path" ]]; then
    _info "core.hooksPath already points to $HOOKS_DIR — updating in place."
    return 0
  fi
  cat >&2 <<WARN
[journal-recorder] WARNING: git global core.hooksPath is already set:
  Current: $existing
  Wanted:  $HOOKS_DIR

To avoid clobbering your existing hooks, this installer will NOT overwrite it.

Manual merge option:
  1. Copy your existing post-commit hook (if any) to $HOOKS_DIR/post-commit.orig
  2. Run: git config --global core.hooksPath "$HOOKS_DIR"
  3. Re-run this installer.

Or set FORCE_HOOKS_PATH=1 to overwrite (existing hook will be backed up).
WARN

  if [[ "${FORCE_HOOKS_PATH:-0}" == "1" ]]; then
    if [[ -d "$existing" && -f "$existing/post-commit" ]]; then
      cp "$existing/post-commit" "$HOOKS_DIR/post-commit.orig.bak" 2>/dev/null || true
      _warn "Backed up existing post-commit to $HOOKS_DIR/post-commit.orig.bak"
    fi
    _warn "FORCE_HOOKS_PATH=1 set — overwriting core.hooksPath."
    return 0
  fi

  exit 1
}

# ── Download files ────────────────────────────────────────────────────────────
_download() {
  local src="$1" dst="$2"
  curl -fsSL "$src" -o "$dst"
}

_install_files() {
  _info "Creating $HOOKS_DIR ..."
  mkdir -p "$HOOKS_DIR/lib"

  _info "Downloading hook scripts ..."
  _download "$REPO_BASE/post-commit-journal.sh" "$HOOKS_DIR/post-commit-journal.sh"
  _download "$REPO_BASE/lib/redact.sh"          "$HOOKS_DIR/lib/redact.sh"
  _download "$REPO_BASE/lib/prompts.sh"          "$HOOKS_DIR/lib/prompts.sh"
  _download "$REPO_BASE/lib/llm-backend.sh"      "$HOOKS_DIR/lib/llm-backend.sh"

  chmod +x "$HOOKS_DIR/post-commit-journal.sh" \
            "$HOOKS_DIR/lib/redact.sh" \
            "$HOOKS_DIR/lib/prompts.sh" \
            "$HOOKS_DIR/lib/llm-backend.sh"

  # Write the post-commit wrapper
  cat > "$HOOKS_DIR/post-commit" <<'HOOK'
#!/usr/bin/env bash
exec bash "$(dirname "$0")/post-commit-journal.sh" "$@"
HOOK
  chmod +x "$HOOKS_DIR/post-commit"
}

# ── Activate global hooksPath ─────────────────────────────────────────────────
_activate() {
  git config --global core.hooksPath "$HOOKS_DIR"
  _info "Set git config --global core.hooksPath=$HOOKS_DIR"
}

# ── Backend detection summary ─────────────────────────────────────────────────
_print_backend_status() {
  echo ""
  echo "─── LLM Backend Status ──────────────────────────────────────────────"
  local found=false
  command -v claude  &>/dev/null && { echo "  ✓ claude CLI detected"; found=true; }
  command -v llm     &>/dev/null && { echo "  ✓ llm CLI detected";    found=true; }
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] && { echo "  ✓ ANTHROPIC_API_KEY set"; found=true; }
  [[ -n "${OPENAI_API_KEY:-}" ]]    && { echo "  ✓ OPENAI_API_KEY set";    found=true; }
  if [[ "$found" == false ]]; then
    echo "  ✗ No LLM backend found."
    echo "    Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or install claude / llm CLI."
    echo "    Without a backend, entries will be saved as minimal templates."
  fi
  echo "─────────────────────────────────────────────────────────────────────"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  _info "Starting installation ..."
  _check_deps
  _check_hooks_path
  _install_files
  _activate
  _print_backend_status

  local journal_dir="${JOURNAL_DIR:-$HOME/claude-journal}"
  mkdir -p "$journal_dir"

  cat <<DONE
[journal-recorder] Installation complete!

  Hook location:  $HOOKS_DIR/post-commit
  Journal output: $journal_dir/
  Log:            /tmp/journal-recorder.log

Every non-merge git commit will now generate a journal entry automatically.

  Per-repo opt-out:   git config journal.skip true
  Global ignore file: ~/.journal-recorder/ignore  (one path glob per line)
  Uninstall:          curl -fsSL $REPO_BASE/uninstall-git-hook.sh | bash

DONE
}

main
