#!/usr/bin/env python3
"""Guided setup. Plan writes first. Real hooks stay unchanged until apply."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

TOOLS = ('claude', 'codex', 'cursor', 'gemini')
SOURCE = Path(__file__).resolve().parent


def safe_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f'Symlink blocked: {part}')
    if path.exists() and not path.is_file():
        raise ValueError(f'File needed: {path}')


def read_text(path):
    safe_path(path)
    return path.read_text() if path.exists() else ''


def check_folder(root):
    if not root.is_absolute():
        raise ValueError('Use full journal path.')
    for part in (root, *root.parents):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise ValueError(f'Folder blocked: {part}')
    parent = root
    while not parent.exists():
        parent = parent.parent
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError('Journal folder not writable.')


def git_value(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            text=True, timeout=20)
    if result.returncode:
        raise ValueError('Git clone check failed. Use local mode or fix clone.')
    return result.stdout.strip()


def check_git(root):
    if Path(git_value(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('Pick Git clone root.')
    git_value(root, 'rev-parse', '--verify', 'HEAD')
    branch = git_value(root, 'symbolic-ref', '--short', 'HEAD')
    fetch = git_value(root, 'remote', 'get-url', '--all', 'origin').splitlines()
    push = git_value(root, 'remote', 'get-url', '--push', '--all', 'origin').splitlines()
    if len(fetch) != 1 or fetch != push:
        raise ValueError('Origin fetch and push URL must match once.')
    git_value(root, 'show-ref', '--verify', f'refs/remotes/origin/{branch}')


def merged_json(path, events, cursor=False):
    text = read_text(path)
    config = json.loads(text) if text else {}
    if not isinstance(config, dict) or not isinstance(config.get('hooks', {}), dict):
        raise ValueError(f'Hook config invalid: {path}')
    hooks = dict(config.get('hooks', {}))
    for event, command in events.items():
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f'Hook list invalid: {path}')
        marker = command.split()[-1]
        if any(('journal.py' in json.dumps(item) and marker in json.dumps(item))
               or (event in ('Stop', 'PostCompact') and 'post-' in json.dumps(item)
                   and 'journal.sh' in json.dumps(item)) for item in entries):
            continue
        handler = {'type': 'command', 'command': command}
        hooks[event] = [*entries, handler if cursor else {'hooks': [handler]}]
    result = {**config, 'hooks': hooks}
    if cursor:
        result['version'] = 1
    return json.dumps(result, indent=2) + '\n'


def codex_config(home):
    path = home / '.codex/config.toml'
    text = read_text(path)
    # Keep existing notify. Parse full TOML when stdlib parser available.
    try:
        import tomllib
    except ImportError:
        if text:
            raise ValueError('Existing Codex config needs Python 3.11+ for safe check.')
    else:
        config = tomllib.loads(text)
        if 'notify' in config:
            return text, 'Codex notify kept. Recorder route may need manual chain.'
    line = 'notify = ' + json.dumps([str(home / '.claude/hooks/codex-notify.sh')])
    return line + '\n' + text, ''


def install_plan(home, agents):
    home = home.resolve()
    if not agents or not set(agents) <= {*TOOLS, 'manual'}:
        raise ValueError('Pick claude,codex,cursor,gemini or manual.')
    hooks = home / '.claude/hooks'
    files = {hooks / name: ((SOURCE / name).read_bytes(), 0o700) for name in
             ('journal.py', 'post-stop-journal.sh', 'post-compact-journal.sh', 'codex-notify.sh')}
    files[home / '.agents/skills/journal-recorder/SKILL.md'] = (
        (SOURCE / 'codex-skill/SKILL.md').read_bytes(), 0o600)
    engine = shlex.quote(str(hooks / 'journal.py'))
    routes = {
        'claude': ('.claude/settings.json', {'Stop': 'stop', 'PostCompact': 'compact'}),
        'cursor': ('.cursor/hooks.json', {'afterAgentResponse': 'cursor'}),
        'gemini': ('.gemini/settings.json', {'AfterAgent': 'gemini'}),
    }
    warnings = []
    for tool in agents:
        if tool in routes:
            name, events = routes[tool]
            path = home / name
            commands = {event: f'python3 {engine} hook {source}' for event, source in events.items()}
            files[path] = (merged_json(path, commands, tool == 'cursor').encode(), 0o600)
        if tool == 'claude':
            files[home / '.claude/agents/journal-recorder.md'] = (
                (SOURCE / 'journal-recorder.md').read_bytes(), 0o600)
        if tool == 'codex':
            text, warning = codex_config(home)
            files[home / '.codex/config.toml'] = (text.encode(), 0o600)
            if warning:
                warnings.append(warning)
    for path in files:
        safe_path(path)
    return files, warnings


def apply_plan(files, verify=None):
    changed = {path: value for path, value in files.items()
               if not path.exists() or path.read_bytes() != value[0]
               or stat.S_IMODE(path.stat().st_mode) != value[1]}
    for path in changed:
        safe_path(path)
    backups = {}
    old_modes = {}
    staged = {}
    try:
        for path, (data, mode) in changed.items():
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists():
                old_modes[path] = stat.S_IMODE(path.stat().st_mode)
                fd, name = tempfile.mkstemp(prefix=path.name + '.backup-', dir=path.parent)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(path.read_bytes())
                backups[path] = Path(name)
            fd, name = tempfile.mkstemp(prefix='.journal-setup-', dir=path.parent)
            staged[path] = Path(name)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.chmod(name, mode)
        applied = []
        try:
            for path, temp in staged.items():
                os.replace(temp, path)
                applied.append(path)
            if verify:
                verify()
        except BaseException:
            for path in reversed(applied):
                if path in backups:
                    os.chmod(backups[path], old_modes[path])
                    os.replace(backups[path], path)
                else:
                    path.unlink()
            raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    for path, backup in backups.items():
        print(f'Backup: {path} -> {backup}')
    return len(changed)


def detected_agents(home):
    return [tool for tool in TOOLS if (home / f'.{tool}').is_dir() or shutil.which(tool)]


def ask(prompt, default):
    answer = input(f'{prompt} [{default}] ').strip()
    return answer or default


def preview(files, home, root, mode, agents):
    print(f'\nTools: {",".join(agents)}\nNotes: {root}\nSync: {mode}')
    for path, (data, _) in files.items():
        old = path.read_bytes() if path.exists() else b''
        if old == data:
            continue
        print(f'Change: {path}')
        if path.name in ('settings.json', 'hooks.json'):
            config = json.loads(data)
            for event, entries in config.get('hooks', {}).items():
                if 'journal.py' in json.dumps(entries):
                    print(f'  Recorder hook: {event}')
        elif path.name == 'config.toml':
            print('  Add recorder notify only when root notify absent.')
    print('Existing changed files get private backup. No model call or Git upload during setup.')


def doctor(home, root, mode, agents):
    check_folder(root)
    if mode == 'git':
        check_git(root)
    probe = subprocess.run([sys.executable, '-I', str(home / '.claude/hooks/journal.py'), 'doctor'],
                           env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True, timeout=20)
    if probe.returncode:
        raise ValueError('Installed core check failed. Run journal.py doctor.')
    with tempfile.TemporaryFile(dir=root):
        pass
    print('Check passed: core runs, notes folder writable.')
    if not shutil.which('claude'):
        print('Manual notes ready. Auto summaries need Claude CLI installed and signed in.')
    else:
        print('Claude CLI found. No live model call made. Check sign-in before auto capture.')
    print('Restart chosen agents. Local mode skips Git, but auto summaries still use model service.')


def guided(home):
    home = home.resolve()
    defaults = ','.join(detected_agents(home)) or 'manual'
    print('Journal Recorder setup\nPress Enter for defaults. Ctrl-C cancels.')
    agents = ask('Agents, comma separated', defaults).split(',')
    agents = list(dict.fromkeys(agent.strip() for agent in agents))
    legacy = (home / '.claude/hooks/journal.py').exists() or (home / '.claude/.journal-folder').exists()
    fallback = home / ('claude-journal' if legacy else 'journal')
    folder = read_text(home / '.claude/.journal-folder').strip() or str(fallback)
    root = Path(os.path.expanduser(ask('Save notes here?', folder))).absolute()
    check_folder(root)
    mode = read_text(home / '.claude/.journal-sync').strip()
    if not mode:
        mode = 'git' if legacy else 'local'
    if mode not in ('local', 'git'):
        raise ValueError('Sync mode invalid. Fix .journal-sync before setup.')
    choice = ask('Sync to existing private Git clone? y/n', 'y' if mode == 'git' else 'n').lower()
    if choice not in ('y', 'yes', 'n', 'no'):
        raise ValueError('Use y or n.')
    mode = 'git' if choice in ('y', 'yes') else 'local'
    if mode == 'git':
        check_git(root)
        if ask('Confirm origin repo private? y/n', 'n').lower() not in ('y', 'yes'):
            print('Cancelled. No changes.')
            return 0
    files, warnings = install_plan(home, agents)
    files = {**files, home / '.claude/.journal-folder': (f'{root}\n'.encode(), 0o600),
             home / '.claude/.journal-sync': (f'{mode}\n'.encode(), 0o600)}
    for path in files:
        safe_path(path)
    preview(files, home, root, mode, agents)
    for warning in warnings:
        print(warning)
    if ask('Apply setup? y/n', 'y').lower() not in ('y', 'yes'):
        print('Cancelled. No changes.')
        return 0
    def verify():
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        doctor(home, root, mode, agents)
    apply_plan(files, verify=verify)
    return 0


def main():
    if sys.version_info < (3, 10) or sys.platform not in ('darwin', 'linux'):
        print('Need macOS or Linux with Python 3.10+.')
        return 1
    parser = argparse.ArgumentParser(description='Set up private work notes.')
    parser.add_argument('--agents', help='Explicit hook install, keep current journal config.')
    args = parser.parse_args()
    try:
        if args.agents:
            files, warnings = install_plan(Path.home(), args.agents.split(','))
            apply_plan(files)
            for warning in warnings:
                print(warning)
            print('Installed chosen hooks. Restart agent. Shared manual skill ready.')
            return 0
        return guided(Path.home())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Setup blocked: {error}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled. No setup consent.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
