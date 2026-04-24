#!/usr/bin/env bash
# LLM backend detection and dispatch.
# Source this file, then call: generate_journal "$system" "$prompt"

# Model overrides via env
JOURNAL_CLAUDE_MODEL="${JOURNAL_CLAUDE_MODEL:-claude-sonnet-4-6}"
JOURNAL_LLM_MODEL="${JOURNAL_LLM_MODEL:-}"  # passed to `llm` CLI; empty = llm's default
JOURNAL_ANTHROPIC_MODEL="${JOURNAL_ANTHROPIC_MODEL:-claude-sonnet-4-6}"
JOURNAL_OPENAI_MODEL="${JOURNAL_OPENAI_MODEL:-gpt-4o-mini}"

# detect_backend: echoes one of: claude | llm | anthropic | openai | none
detect_backend() {
  # Allow override for testing
  [[ -n "${BACKEND_OVERRIDE:-}" ]] && echo "$BACKEND_OVERRIDE" && return

  if command -v claude &>/dev/null; then
    echo "claude"; return
  fi
  if command -v llm &>/dev/null; then
    echo "llm"; return
  fi
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "anthropic"; return
  fi
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    echo "openai"; return
  fi
  echo "none"
}

_backend_claude() {
  local system="$1" prompt="$2"
  claude -p \
    --system-prompt "$system" \
    --output-format text \
    --model "$JOURNAL_CLAUDE_MODEL" \
    "$prompt" 2>/dev/null
}

_backend_llm() {
  local system="$1" prompt="$2"
  local model_flag=""
  [[ -n "$JOURNAL_LLM_MODEL" ]] && model_flag="-m $JOURNAL_LLM_MODEL"
  # llm reads system via --system
  # shellcheck disable=SC2086
  echo "$prompt" | llm $model_flag --system "$system" 2>/dev/null
}

_backend_anthropic() {
  local system="$1" prompt="$2"
  local escaped_system escaped_prompt payload response

  escaped_system="$(echo "$system" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
  escaped_prompt="$(echo "$prompt" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

  payload="{\"model\":\"${JOURNAL_ANTHROPIC_MODEL}\",\"max_tokens\":2048,\"system\":${escaped_system},\"messages\":[{\"role\":\"user\",\"content\":${escaped_prompt}}]}"

  response="$(curl -s --max-time 120 \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d "$payload" \
    "https://api.anthropic.com/v1/messages" 2>/dev/null)"

  echo "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["content"][0]["text"])' 2>/dev/null
}

_backend_openai() {
  local system="$1" prompt="$2"
  local escaped_system escaped_prompt payload response

  escaped_system="$(echo "$system" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
  escaped_prompt="$(echo "$prompt" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

  payload="{\"model\":\"${JOURNAL_OPENAI_MODEL}\",\"messages\":[{\"role\":\"system\",\"content\":${escaped_system}},{\"role\":\"user\",\"content\":${escaped_prompt}}]}"

  response="$(curl -s --max-time 120 \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "https://api.openai.com/v1/chat/completions" 2>/dev/null)"

  echo "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"])' 2>/dev/null
}

# generate_journal <system_prompt> <user_prompt>
# Echoes markdown on stdout, empty string on failure.
generate_journal() {
  local system="$1" prompt="$2"
  local backend
  backend="$(detect_backend)"

  case "$backend" in
    claude)    _backend_claude    "$system" "$prompt" ;;
    llm)       _backend_llm       "$system" "$prompt" ;;
    anthropic) _backend_anthropic "$system" "$prompt" ;;
    openai)    _backend_openai    "$system" "$prompt" ;;
    none)      echo "" ;;
  esac
}
