#!/usr/bin/env python3
"""Fetch fixed setup archive. Check bytes before extract or run."""

import hashlib
import io
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REVISION = '1b64eeb4460d99b5d9d9988d9d56b080f6be4b00'
SHA256 = '0d602c1a82e8f64f3f3f71334f70563509f3484066446ef3243789ce139de316'
MAX_ARCHIVE = 8_000_000
MAX_EXPANDED = 24_000_000


def extract_checked(data, target, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Download check failed. No setup run.')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        if not members or len(members) > 1000:
            raise ValueError('Archive size blocked.')
        roots = set()
        total = 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('Archive path blocked.')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Archive link blocked.')
            roots.add(path.parts[0])
            total += member.size
            if total > MAX_EXPANDED:
                raise ValueError('Archive size blocked.')
        if len(roots) != 1:
            raise ValueError('Archive root blocked.')
        for member in members:
            output = target.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as source, output.open('xb') as dest:
                    dest.write(source.read())
        root = target / roots.pop()
        if not (root / 'setup.py').is_file() or not (root / 'journal.py').is_file():
            raise ValueError('Setup payload missing.')
        return root


def main():
    if sys.version_info < (3, 10) or sys.platform not in ('darwin', 'linux'):
        print('Need macOS or Linux with Python 3.10+.')
        return 1
    url = f'https://codeload.github.com/GauravRatnawat/journal-recorder-agent/tar.gz/{REVISION}'
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(MAX_ARCHIVE + 1)
        if len(data) > MAX_ARCHIVE:
            raise ValueError('Download too large.')
        with tempfile.TemporaryDirectory(prefix='journal-setup-') as tmp:
            root = extract_checked(data, Path(tmp), SHA256)
            with open('/dev/tty') as terminal:
                return subprocess.run([sys.executable, '-I', str(root / 'setup.py')],
                                      stdin=terminal, cwd=tmp).returncode
    except (OSError, ValueError, tarfile.TarError) as error:
        print(f'Setup blocked: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
