"""Host-process execution with a reduced environment and no command shell."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from .base import ExecutionRequest, ExecutionResult

_ALLOWED_ENVIRONMENT = frozenset(
    {"COMSPEC", "HOME", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR"}
)


class LocalExecutionBackend:
    name = "local"

    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.runner = runner
        self.clock = clock

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        command = list(request.command)
        if command and command[0] == "python":
            command[0] = sys.executable
        environment = {
            name: value
            for name, value in request.environment.items()
            if name.upper() in _ALLOWED_ENVIRONMENT
        }
        environment.update({"PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        started = self.clock()
        try:
            completed = self.runner(
                command,
                cwd=request.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
                env=environment,
            )
            return ExecutionResult(
                completed.returncode,
                completed.stdout or "",
                completed.stderr or "",
                _elapsed_ms(started, self.clock()),
                False,
                self.name,
                None if completed.returncode == 0 else "nonzero_exit",
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                None,
                _text(exc.output),
                _text(exc.stderr),
                _elapsed_ms(started, self.clock()),
                True,
                self.name,
                "timeout",
            )
        except OSError as exc:
            return ExecutionResult(
                None,
                "",
                str(exc),
                _elapsed_ms(started, self.clock()),
                False,
                self.name,
                "start_error",
            )


def _elapsed_ms(started: float, ended: float) -> int:
    return max(0, round((ended - started) * 1000))


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""
