#!/usr/bin/env bash
# Install reviewed local checkout. Pick hooks with --agents.
set -euo pipefail
command -v python3 >/dev/null || { printf 'Python 3 needed.\n' >&2; exit 1; }
if [ -z "${BASH_SOURCE[0]:-}" ] || [ ! -f "${BASH_SOURCE[0]}" ]; then
  printf 'Clone reviewed revision, then run bash install.sh.\n' >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS="claude,codex"
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != "--agents" ]; then
    printf 'Use: bash install.sh --agents claude,codex,cursor,gemini\n' >&2
    exit 1
  fi
  AGENTS="$2"
fi
python3 - "$SCRIPT_DIR" "$AGENTS" <<'PY'
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys

source = Path(sys.argv[1])
agents = set(sys.argv[2].split(','))
if not agents <= {'claude', 'codex', 'cursor', 'gemini', 'manual'}:
    raise SystemExit('Unknown agent. Use claude,codex,cursor,gemini,manual.')
home = Path.home()
hooks = home / '.claude/hooks'
hooks.mkdir(parents=True, exist_ok=True)
for name in ('journal.py', 'post-stop-journal.sh', 'post-compact-journal.sh', 'codex-notify.sh'):
    shutil.copyfile(source / name, hooks / name)
    (hooks / name).chmod(0o700)
skill = home / '.agents/skills/journal-recorder'
skill.mkdir(parents=True, exist_ok=True)
shutil.copyfile(source / 'codex-skill/SKILL.md', skill / 'SKILL.md')


def merge(path, events, cursor=False):
    config = json.loads(path.read_text()) if path.exists() else {}
    new_hooks = dict(config.get('hooks', {}))
    for event, command in events.items():
        entries = list(new_hooks.get(event, []))
        marker = command.split()[-1]
        if any('journal.py' in json.dumps(item) and marker in json.dumps(item)
               or event in ('Stop', 'PostCompact') and 'post-' in json.dumps(item) and 'journal.sh' in json.dumps(item)
               for item in entries):
            continue
        handler = {'type': 'command', 'command': command}
        entries.append(handler if cursor else {'hooks': [handler]})
        new_hooks[event] = entries
    result = {**config, 'hooks': new_hooks}
    if cursor:
        result['version'] = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')

engine = shlex.quote(str(hooks / 'journal.py'))
if 'claude' in agents:
    merge(home / '.claude/settings.json', {
        'Stop': f'python3 {engine} hook stop',
        'PostCompact': f'python3 {engine} hook compact',
    })
    agent_dir = home / '.claude/agents'
    agent_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / 'journal-recorder.md', agent_dir / 'journal-recorder.md')
if 'cursor' in agents:
    merge(home / '.cursor/hooks.json', {
        'afterAgentResponse': f'python3 {engine} hook cursor',
    }, cursor=True)
if 'gemini' in agents:
    merge(home / '.gemini/settings.json', {
        'AfterAgent': f'python3 {engine} hook gemini',
    })
if 'codex' in agents and (home / '.codex').is_dir():
    config = home / '.codex/config.toml'
    text = config.read_text() if config.exists() else ''
    root = re.split(r'^\s*\[', text, maxsplit=1, flags=re.M)[0]
    if re.search(r'^\s*notify\s*=', root, re.M):
        print('Codex notify kept. Check existing command before manual change.')
    else:
        line = 'notify = ' + json.dumps([str(hooks / 'codex-notify.sh')])
        config.write_text(line + '\n' + text)
print('Installed chosen hooks. Restart agent. Shared manual skill ready.')
PY
