#!/usr/bin/env bash
# Stop hook — all logic lives in journal.py (same directory).
exec python3 "$(cd "$(dirname "$0")" && pwd)/journal.py" hook stop
