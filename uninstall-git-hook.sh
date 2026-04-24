#!/usr/bin/env bash
# Uninstalls the universal journal-recorder git hook.
#
# Usage: curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/git-hook-universal/uninstall-git-hook.sh | bash

set -euo pipefail

HOOKS_DIR="$HOME/.git-hooks-global"

_info()  { echo "[journal-recorder] $*"; }
_warn()  { echo "[journal-recorder] WARNING: $*" >&2; }

main() {
  # Unset core.hooksPath only if it points at our directory
  local current
  current="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  local expanded="${current/#\~/$HOME}"
  local our_path="${HOOKS_DIR/#\~/$HOME}"

  if [[ "$expanded" == "$our_path" ]]; then
    git config --global --unset core.hooksPath
    _info "Removed core.hooksPath from global git config."
  elif [[ -n "$current" ]]; then
    _warn "core.hooksPath is '$current', not '$HOOKS_DIR' — leaving git config untouched."
  fi

  # Remove hook files
  if [[ -d "$HOOKS_DIR" ]]; then
    # Check for extra files we didn't install
    local extra
    extra="$(find "$HOOKS_DIR" -type f \
      ! -name 'post-commit' \
      ! -name 'post-commit-journal.sh' \
      ! -name 'post-commit.orig.bak' \
      ! -path '*/lib/redact.sh' \
      ! -path '*/lib/prompts.sh' \
      ! -path '*/lib/llm-backend.sh' \
      2>/dev/null || true)"

    if [[ -n "$extra" ]]; then
      _warn "Found extra files in $HOOKS_DIR not installed by journal-recorder:"
      echo "$extra" | sed 's/^/    /'
      read -r -p "[journal-recorder] Remove entire directory anyway? [y/N] " confirm
      if [[ "${confirm,,}" != "y" ]]; then
        _info "Skipping directory removal. Removed git config only."
        exit 0
      fi
    fi

    rm -rf "$HOOKS_DIR"
    _info "Removed $HOOKS_DIR"
  else
    _info "$HOOKS_DIR not found — nothing to remove."
  fi

  _info "Uninstall complete. Journal entries in ~/claude-journal/ are untouched."
}

main
