from __future__ import annotations

import fcntl
from pathlib import Path
from types import TracebackType
from typing import TextIO


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle: TextIO | None = None
        self.acquired = False

    def __enter__(self) -> ProcessLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("w")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            self.acquired = False
            return self
        handle.write(str(__import__("os").getpid()))
        handle.flush()
        self._handle = handle
        self.acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is not None:
            handle = self._handle
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            self.path.unlink(missing_ok=True)
