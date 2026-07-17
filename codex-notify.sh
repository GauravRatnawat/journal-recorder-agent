#!/usr/bin/env bash
# Codex notify hook — Codex appends the notification JSON as the last argument.
# If you already have a notify program configured, call it here too (chained),
# since Codex supports only one notify command.
python3 "$HOME/.claude/hooks/journal.py" hook codex "${@: -1}"
