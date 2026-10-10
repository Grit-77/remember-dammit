"""Participating-writer lock kept outside the portable vault.

The OS releases the advisory lock if its process dies. Arbitrary external
editors do not participate; managed writes therefore never edit their files.
"""
from contextlib import contextmanager
import os
import threading
import time

from .errors import VaultError
from .local_state import _is_link, local_state_directory

_thread_guard = threading.Lock()
_thread_locks = {}
_thread_owned = threading.local()


@contextmanager
def writer_lock(root, *, timeout=30):
    """Serialize threads and processes operating on the same resolved root."""
    directory = local_state_directory(root, 'locks')
    key = str(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _thread_guard:
        lock = _thread_locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise VaultError('lock_timeout', 'The vault writer is busy.')
    owned = getattr(_thread_owned, 'keys', None)
    if owned is None:
        owned = _thread_owned.keys = set()
    owner_key = (os.getpid(), key)
    if owner_key in owned:
        try:
            yield
        finally:
            lock.release()
        return
    handle = None
    locked = False
    try:
        lock_path = directory / 'writer.lock'
        if _is_link(lock_path):
            raise VaultError('invalid_local_state', 'The writer lock must not be a link.')
        handle = open(lock_path, 'a+b')
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
        owned.add(owner_key)
        yield
    finally:
        owned.discard(owner_key)
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
