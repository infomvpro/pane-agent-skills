#!/usr/bin/env python3
"""Durable file-inbox example, NOT an LLM runner. Configure via a private wrapper.

One atomic JSON file per event; a real agent consumer must track completion and
publication idempotency durably. Never delete jobs just to indicate success.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from pane_common import SafeError, decode_json
from webhook_receiver import ID, MAX_BODY, VALIDATOR


def store(raw: bytes, directory: Path) -> None:
    data = decode_json(raw)
    if len(raw) > MAX_BODY or not VALIDATOR.is_valid(data) or not ID.fullmatch(data['audio_event_id']):
        raise SafeError('invalid_event')
    if not directory.is_absolute() or directory.is_symlink():
        raise SafeError('absolute_private_inbox_required')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise SafeError('private_inbox_required')
    target = directory / (data['audio_event_id'] + '.json')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.incoming-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)  # Atomic, no overwrite after an ambiguous handoff.
        except FileExistsError:
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as existing:
                if hashlib.sha256(existing.read(MAX_BODY + 1)).digest() != hashlib.sha256(raw).digest():
                    raise SafeError('conflicting_event')
        temporary.unlink()
        temporary = None
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    try:
        location = os.environ.get('PANE_AGENT_INBOX', '')
        if not location:
            raise SafeError('private_wrapper_must_set_PANE_AGENT_INBOX')
        store(sys.stdin.buffer.read(MAX_BODY + 1), Path(location))
        return 0
    except (SafeError, OSError, RecursionError):
        # Worker deliberately suppresses output; retain only a nonzero result.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
