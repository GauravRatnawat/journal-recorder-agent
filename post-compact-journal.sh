#!/usr/bin/env bash
# PostCompact hook — all logic lives in journal.py (same directory).
exec python3 "$(cd "$(dirname "$0")" && pwd)/journal.py" hook compact
