#!/usr/bin/env bash
# Stop hook: writes a journal entry when Claude finishes a turn,
# guarded by a 30-minute recency check so it only fires meaningfully.
set -euo pipefail

input=$(cat)

# --- Recency guard (30 min) ---
marker="$HOME/.claude/.journal-last-written"
if [ -f "$marker" ]; then
  last_ts=$(cat "$marker" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - last_ts ))
  if [ "$age" -lt 1800 ]; then
    exit 0
  fi
fi

transcript_path=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)

if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ]; then
  exit 0
fi

# --- Minimum-substance check: skip trivial sessions ---
msg_count=$(python3 - "$transcript_path" <<'PYEOF'
import sys, json
count = 0
try:
    with open(sys.argv[1]) as f:
        for line in f:
            try:
                obj = json.loads(line)
                role = obj.get("message", {}).get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = obj.get("message", {}).get("content", "")
                text = " ".join(c.get("text","") for c in content if isinstance(content,list) and c.get("type")=="text") if isinstance(content,list) else str(content)
                if len(text.strip()) > 50:
                    count += 1
            except Exception:
                pass
except Exception:
    pass
print(count)
PYEOF
)

if [ "${msg_count:-0}" -lt 4 ]; then
  exit 0
fi

# --- Extract conversation ---
conversation=$(python3 - "$transcript_path" <<'PYEOF'
import sys, json
messages = []
try:
    with open(sys.argv[1]) as f:
        for line in f:
            try:
                obj = json.loads(line)
                role = obj.get("message", {}).get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, list):
                    text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
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
print("\n\n".join(messages[-30:])[:8000])
PYEOF
)

if [ -z "$conversation" ]; then
  exit 0
fi

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

SYSTEM="You are a journal writer. Your only job is to produce clean markdown journal entries. Never use tools, never ask questions, never ask for permissions. Just output the markdown text."

PROMPT="Analyze this conversation log and write a structured markdown journal entry. Output ONLY the markdown, starting directly with the # title.

Required sections: TL;DR, What Was Accomplished, Key Decisions, Problems Encountered, Action Items, Tags.

Date: $date_human

CONVERSATION:
$conversation"

journal=$(claude -p \
  --system-prompt "$SYSTEM" \
  --output-format text \
  "$PROMPT" 2>/dev/null || true)

if [ -z "$journal" ]; then
  exit 0
fi

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
echo "$(date +%s)" > "$marker"
echo "[post-stop-journal] saved: $dir/$filename" >&2
