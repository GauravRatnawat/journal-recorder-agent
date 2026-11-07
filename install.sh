#!/usr/bin/env bash
# Guided setup from local checkout. Explicit --agents keeps old config mode.
set -euo pipefail
command -v python3 >/dev/null || { printf 'Python 3.10+ needed.\n' >&2; exit 1; }
if [ -z "${BASH_SOURCE[0]:-}" ] || [ ! -f "${BASH_SOURCE[0]}" ]; then
  printf 'Use checked bootstrap or run local install.sh.\n' >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" = '--setup' ]; then shift; fi
exec python3 -I "$SCRIPT_DIR/setup.py" "$@"
