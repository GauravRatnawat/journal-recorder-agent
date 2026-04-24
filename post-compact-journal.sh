#!/usr/bin/env bash
# PostCompact hook — generates a rich, shareable journal entry via claude -p
# Output: ~/claude-journal/YYYY-MM-DD_HH-MM_<title-slug>.md

set -euo pipefail

input=$(cat)
echo "$input" > /tmp/postcompact_last_input.json  # debug reference

transcript_path=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)
trigger=$(echo "$input" | jq -r '.trigger // "auto"' 2>/dev/null || echo "auto")

ts=$(date '+%Y-%m-%d_%H-%M')
date_human=$(date '+%Y-%m-%d %H:%M')
config="$HOME/.claude/.journal-folder"
if [ -f "$config" ]; then
  dir=$(cat "$config" | tr -d '[:space:]')
  dir="${dir/#\~/$HOME}"
else
  dir="$HOME/claude-journal"
fi
mkdir -p "$dir"

# ── Extract readable conversation from transcript ─────────────────────────────
conversation=""
if [ -n "$transcript_path" ] && [ -n "${transcript_path%%null}" ] && [ -f "$transcript_path" ]; then
  conversation=$(python3 - "$transcript_path" <<'PYEOF'
import sys, json

path = sys.argv[1]
messages = []
try:
    with open(path) as f:
        for line in f:
            try:
                obj = json.loads(line)
                role = obj.get("message", {}).get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content if c.get("type") == "text"
                    )
                else:
                    text = str(content)
                text = text.strip()
                if len(text) < 10:
                    continue
                if "<local-command" in text or "<system-reminder" in text:
                    continue
                messages.append(f"{role.upper()}: {text[:800]}")
            except Exception:
                pass
except Exception:
    pass

tail = messages[-30:]
out = "\n\n".join(tail)
print(out[:8000])
PYEOF
)
fi

# ── Fallback to compaction summary if transcript unavailable ──────────────────
if [ -z "$conversation" ]; then
  conversation=$(echo "$input" | jq -r '.summary // empty' 2>/dev/null || true)
fi

if [ -z "$conversation" ] || [ "$conversation" = "null" ]; then
  echo "[post-compact-journal] no content — skipping" >&2
  exit 0
fi

# ── Generate journal via claude -p ────────────────────────────────────────────
SYSTEM="You are a journal writer. Your only job is to produce clean markdown journal entries. Never use tools, never ask questions, never ask for permissions. Just output the markdown text."

PROMPT="Analyze this historical conversation log and write a structured markdown journal entry. Output ONLY the markdown, starting directly with the # title.

Required sections:
# <descriptive title>
**Date:** $date_human
## TL;DR
## What Was Worked On
## What Was Accomplished
## Key Decisions
## Problems & Solutions
## Action Items
## Tags

HISTORICAL LOG:
$conversation"

journal=$(claude -p \
  --system-prompt "$SYSTEM" \
  --output-format text \
  "$PROMPT" 2>/dev/null || true)

if [ -z "$journal" ]; then
  printf '# Journal Entry — %s\n\n**Trigger:** %s\n\n## Conversation Excerpt\n\n%s\n' \
    "$date_human" "$trigger" "$conversation" > "$dir/${ts}_session.md"
  echo "[post-compact-journal] claude -p failed, wrote fallback: $dir/${ts}_session.md" >&2
  exit 0
fi

# ── Slug from generated H1 title ──────────────────────────────────────────────
title_line=$(echo "$journal" | grep -m1 '^# ' | sed 's/^# //' || true)
[ -z "$title_line" ] && title_line=$(echo "$journal" | head -1 | sed 's/^#* *//')

slug=$(echo "$title_line" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/[^a-z0-9 ]/ /g' \
  | tr -s ' ' '-' \
  | sed 's/^-//; s/-$//' \
  | cut -c1-60 \
  | sed 's/-$//')
[ -z "$slug" ] && slug="session"

filename="${ts}_${slug}.md"
echo "$journal" > "$dir/$filename"
echo "$(date +%s)" > "$HOME/.claude/.journal-last-written"
echo "[post-compact-journal] saved: $dir/$filename" >&2
