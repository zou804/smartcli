"""Docker CLI execution with explicit isolation and resource constraints."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from .base import ExecutionRequest, ExecutionResult
from .local import _elapsed_ms, _text


class DockerExecutionBackend:
    name = "docker"

    def __init__(
        self,
        *,
        docker_executable: str | None = None,
        runner: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.docker_executable = docker_executable
        self.runner = runner
        self.which = which
        self.clock = clock

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        started = self.clock()
        docker = self.docker_executable or self.which("docker")
        if docker is None:
            return ExecutionResult(
                None, "", "Docker executable was not found", 0, False, self.name, "docker_missing"
            )
        if not request.image:
            return ExecutionResult(
                None, "", "Docker image is required", 0, False, self.name, "image_missing"
            )
        workspace = request.workspace.resolve()
        mount = f"type=bind,source={workspace},target=/workspace"
        command = [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--memory",
            f"{request.memory_mb}m",
            "--cpus",
            str(request.cpus),
            "--pids-limit",
            str(request.pids_limit),
            "--user",
            "65532:65532",
            "--mount",
            mount,
            "-w",
            "/workspace",
            request.image,
            *request.command,
        ]
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
                env={},
            )
            error_type = None if completed.returncode == 0 else "nonzero_exit"
            stderr = completed.stderr or ""
            if completed.returncode == 125 and "No such image" in stderr:
                error_type = "image_missing"
            elif completed.returncode == 125:
                error_type = "docker_unavailable"
            return ExecutionResult(
                completed.returncode,
                completed.stdout or "",
                stderr,
                _elapsed_ms(started, self.clock()),
                False,
                self.name,
                error_type,
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
                "docker_unavailable",
            )
