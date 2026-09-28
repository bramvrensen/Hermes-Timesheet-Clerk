"""Process and thread locking for local persistent state (Linux/macOS)."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import threading
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()
_local = threading.local()


@contextmanager
def state_lock(root: Path):
    path = str((Path(root) / ".state.lock").resolve())
    with _guard:
        lock = _locks.setdefault(path, threading.RLock())
    with lock:
        held = getattr(_local, "held", {})
        if path in held:
            yield
            return
        Path(root).mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held[path] = handle
            _local.held = held
            try:
                yield
            finally:
                held.pop(path)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked_repository(method):
    from functools import wraps
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with state_lock(self.root):
            return method(self, *args, **kwargs)
    return wrapped
