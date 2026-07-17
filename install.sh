#!/usr/bin/env bash
# journal-recorder one-command installer.
#   curl -fsSL https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main/install.sh | bash
# Idempotent: safe to re-run. Run from a local checkout to install local copies instead of downloading.
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/GauravRatnawat/journal-recorder-agent/main"
HOOKS_DIR="$HOME/.claude/hooks"
AGENTS_DIR="$HOME/.claude/agents"
SETTINGS="$HOME/.claude/settings.json"

command -v python3 >/dev/null || { echo "error: python3 required" >&2; exit 1; }

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

fetch() { # fetch <repo-path> <dest>
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/$1" ]; then
    cp "$SCRIPT_DIR/$1" "$2"
  else
    curl -fsSL "$REPO_RAW/$1" -o "$2"
  fi
  echo "  installed $2"
}

echo "journal-recorder install"

# 1. Engine + hook scripts
mkdir -p "$HOOKS_DIR"
fetch journal.py "$HOOKS_DIR/journal.py"
fetch post-compact-journal.sh "$HOOKS_DIR/post-compact-journal.sh"
fetch post-stop-journal.sh "$HOOKS_DIR/post-stop-journal.sh"
chmod +x "$HOOKS_DIR/post-compact-journal.sh" "$HOOKS_DIR/post-stop-journal.sh"

# 2. Agent (on-demand rich entries)
mkdir -p "$AGENTS_DIR"
fetch journal-recorder.md "$AGENTS_DIR/journal-recorder.md"

# 3. Merge Stop + PostCompact hooks into settings.json (idempotent)
python3 - "$SETTINGS" <<'PY'
import json, os, sys

path = sys.argv[1]
settings = {}
if os.path.exists(path):
    with open(path) as f:
        settings = json.load(f)

hooks = settings.setdefault("hooks", {})

def ensure(event, script):
    entries = hooks.setdefault(event, [])
    for entry in entries:
        for h in entry.get("hooks", []):
            if script in h.get("command", ""):
                return False
    entries.append({"hooks": [{
        "type": "command",
        "command": f"bash ~/.claude/hooks/{script}",
        "statusMessage": "Saving journal entry...",
        "timeout": 30,
    }]})
    return True

changed = ensure("Stop", "post-stop-journal.sh")
changed |= ensure("PostCompact", "post-compact-journal.sh")

if changed:
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("  hooks merged into " + path)
else:
    print("  hooks already present in " + path)
PY

# 4. Codex (only if Codex CLI is set up)
CODEX_CONFIG="$HOME/.codex/config.toml"
if [ -d "$HOME/.codex" ]; then
  fetch codex-notify.sh "$HOOKS_DIR/codex-notify.sh"
  chmod +x "$HOOKS_DIR/codex-notify.sh"
  mkdir -p "$HOME/.agents/skills/journal-recorder"
  fetch codex-skill/SKILL.md "$HOME/.agents/skills/journal-recorder/SKILL.md"

  NOTIFY_LINE="notify = [\"$HOOKS_DIR/codex-notify.sh\"]"
  touch "$CODEX_CONFIG"
  if grep -q "codex-notify.sh" "$CODEX_CONFIG"; then
    echo "  codex notify already configured"
  elif grep -q "^notify" "$CODEX_CONFIG"; then
    echo "  WARNING: $CODEX_CONFIG already has a notify command."
    echo "  Codex supports only one — edit ~/.claude/hooks/codex-notify.sh to chain both, then set:"
    echo "    $NOTIFY_LINE"
  else
    printf '\n%s\n' "$NOTIFY_LINE" >> "$CODEX_CONFIG"
    echo "  codex notify added to $CODEX_CONFIG"
  fi
else
  echo "  codex not found, skipping (re-run installer after installing Codex CLI)"
fi

echo
echo "Done. Journals will be written to $(python3 "$HOOKS_DIR/journal.py" resolve-dir)."
echo
echo "Optional next steps:"
echo "  - Custom journal folder:  echo \"~/Documents/my-journal\" > ~/.claude/.journal-folder"
echo "  - GitHub sync:            cd \"\$(python3 ~/.claude/hooks/journal.py resolve-dir)\" && gh repo create claude-journal --private --source . --push"
echo "  - CLAUDE.md mandate:      see README 'Add the mandate to CLAUDE.md'"