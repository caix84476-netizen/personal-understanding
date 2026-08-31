#!/usr/bin/env python3
"""Process-safe storage primitives for shared personal-understanding data."""
from __future__ import annotations

import contextlib
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover
    msvcrt = None
    import fcntl  # type: ignore

_LOCAL = threading.local()


def _held() -> dict[str, tuple[object, int]]:
    value = getattr(_LOCAL, "locks", None)
    if value is None:
        value = {}
        _LOCAL.locks = value
    return value


@contextlib.contextmanager
def mutation_lock(root: Path, *, timeout: float = 30.0) -> Iterator[None]:
    """One re-entrant file lock for all writers sharing a skill directory."""
    root = root.resolve()
    key = str(root).casefold()
    held = _held()
    if key in held:
        handle, depth = held[key]
        held[key] = (handle, depth + 1)
        try:
            yield
        finally:
            handle, depth = held[key]
            held[key] = (handle, depth - 1)
        return
    lock_path = root / "memory" / ".personal-understanding.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"等待个人档案写锁超时：{lock_path}")
                time.sleep(0.05)
        held[key] = (handle, 1)
        yield
    finally:
        item = held.get(key)
        if item and item[0] is handle:
            del held[key]
        if acquired:
            try:
                handle.seek(0)
                if msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))
