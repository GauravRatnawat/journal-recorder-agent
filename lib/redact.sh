#!/usr/bin/env bash
# Redacts secrets from git diffs before any LLM call.

# Files to skip entirely (by path pattern)
_SKIP_PATTERNS=(
  '.env' '.env.*' '*.env'
  '*.pem' '*.key' '*.p12' '*.pfx'
  'id_rsa' 'id_rsa.*' 'id_ed25519' 'id_ed25519.*' 'id_ecdsa' 'id_ecdsa.*'
  '*secret*' '*credential*' '*credentials*'
  '*.jks' '*.keystore'
)

_file_should_skip() {
  local path="$1"
  local pat
  for pat in "${_SKIP_PATTERNS[@]}"; do
    # shellcheck disable=SC2254
    case "$path" in $pat) return 0 ;; esac
  done
  return 1
}

# Redacts a raw unified diff, printing safe version to stdout.
# Usage: redact_diff <raw_diff_string>
redact_diff() {
  local raw="$1"
  local output=""
  local current_file=""
  local skip_file=false
  local line

  while IFS= read -r line; do
    # Detect file header (diff --git a/foo b/foo  or  +++ b/foo)
    if [[ "$line" =~ ^diff\ --git\ a/(.+)\ b/(.+)$ ]]; then
      current_file="${BASH_REMATCH[2]}"
      if _file_should_skip "$(basename "$current_file")"; then
        skip_file=true
        output+="diff --git a/${current_file} b/${current_file}"$'\n'
        output+="[FILE SKIPPED — matches secret file pattern]"$'\n'
        continue
      else
        skip_file=false
      fi
    fi

    [[ "$skip_file" == true ]] && continue

    # Redact known secret patterns inline
    line="${line//$'\r'/}"  # strip CR

    # AWS access key: AKIA[0-9A-Z]{16}
    line="$(echo "$line" | sed -E 's/AKIA[0-9A-Z]{16}/[REDACTED_AWS_KEY]/g')"
    # AWS secret: 40-char base64-ish after common var names
    line="$(echo "$line" | sed -E 's/(aws_secret_access_key|AWS_SECRET)[^=]*=\s*[A-Za-z0-9/+=]{40}/\1=[REDACTED_AWS_SECRET]/gi')"
    # GitHub tokens
    line="$(echo "$line" | sed -E 's/gh[pos]_[A-Za-z0-9_]{36,}/[REDACTED_GITHUB_TOKEN]/g')"
    # OpenAI keys
    line="$(echo "$line" | sed -E 's/sk-[A-Za-z0-9]{32,}/[REDACTED_OPENAI_KEY]/g')"
    # Anthropic keys
    line="$(echo "$line" | sed -E 's/sk-ant-[A-Za-z0-9_-]{32,}/[REDACTED_ANTHROPIC_KEY]/g')"
    # Generic Bearer tokens (long base64)
    line="$(echo "$line" | sed -E 's/(Bearer\s+)[A-Za-z0-9_\-\.]{40,}/\1[REDACTED_TOKEN]/g')"
    # Private key blocks
    line="$(echo "$line" | sed -E 's/-----BEGIN [A-Z ]+ KEY-----/[REDACTED_PRIVATE_KEY_BLOCK]/g')"
    # JWTs: three base64url segments separated by dots
    line="$(echo "$line" | sed -E 's/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/[REDACTED_JWT]/g')"

    output+="$line"$'\n'
  done <<< "$raw"

  echo "$output"
}
