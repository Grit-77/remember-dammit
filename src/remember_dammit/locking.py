"""Participating-writer lock kept outside the portable vault.

The OS releases the advisory lock if its process dies. Arbitrary external
editors do not participate; managed writes therefore never edit their files.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading
import time

from .errors import VaultError

_thread_guard = threading.Lock()
_thread_locks = {}


@contextmanager
def writer_lock(root, *, timeout=30):
    """Serialize threads and processes operating on the same resolved root."""
    identity = os.path.normcase(str(Path(root).resolve()))
    key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    # A process-controlled TEMP/TMPDIR cannot select a second lock namespace.
    # This sibling is outside portable vault contents. Writers need access to
    # the canonical root's parent; same-host aliases resolve to the same lock.
    directory = Path(root).resolve().parent / '.remember-dammit-locks'
    junction_check = getattr(directory, 'is_junction', None)
    if directory.is_symlink() or (callable(junction_check) and junction_check()):
        raise VaultError('invalid_vault', 'The writer lock directory must not be a link.')
    directory.mkdir(parents=True, exist_ok=True)
    with _thread_guard:
        lock = _thread_locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise VaultError('lock_timeout', 'The vault writer is busy.')
    handle = None
    locked = False
    try:
        handle = open(directory / (key + '.lock'), 'a+b')
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise VaultError('lock_timeout', 'The vault writer is busy.') from None
                time.sleep(0.02)
        yield
    finally:
        if handle is not None:
            if locked:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        lock.release()
