"""Cross-process coordination primitives for local JSON storage."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import TracebackType


class StorageLockError(RuntimeError):
    """Raised when a local storage lock cannot be acquired or released."""


class InterProcessFileLock:
    """Small stdlib-only exclusive lock backed by a sibling lock file."""

    def __init__(self, target: str | Path, *, timeout_seconds: float = 5.0) -> None:
        self.target = Path(target)
        self.lock_path = self.target.with_name(f".{self.target.name}.lock")
        self.timeout_seconds = timeout_seconds
        self._stream = None

    def __enter__(self) -> InterProcessFileLock:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = self.lock_path.open("a+b")
            if os.name == "nt" and self.lock_path.stat().st_size == 0:
                self._stream.write(b"\0")
                self._stream.flush()
        except OSError as exc:
            self._close()
            raise StorageLockError(f"Cannot open storage lock {self.lock_path}: {exc}") from exc

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._acquire_once()
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    self._close()
                    raise StorageLockError(
                        f"Timed out waiting for storage lock {self.lock_path}"
                    ) from exc
                time.sleep(0.05)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        try:
            self._release()
        except OSError as lock_exc:
            raise StorageLockError(
                f"Cannot release storage lock {self.lock_path}: {lock_exc}"
            ) from lock_exc
        finally:
            self._close()

    def _acquire_once(self) -> None:
        assert self._stream is not None
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(self) -> None:
        if self._stream is None:
            return
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)

    def _close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
