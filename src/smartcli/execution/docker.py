"""Docker CLI execution with explicit isolation and resource constraints."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
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
        name_factory: Callable[[], str] | None = None,
        container_user: str | None = None,
    ) -> None:
        self.docker_executable = docker_executable
        self.runner = runner
        self.which = which
        self.clock = clock
        self.name_factory = name_factory or (
            lambda: f"smartcli-{uuid.uuid4().hex[:12]}"
        )
        self.container_user = container_user or _container_user()

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
        if self.container_user.split(":", 1)[0] == "0":
            return ExecutionResult(
                None,
                "",
                "Docker execution is refused when the host identity is root",
                0,
                False,
                self.name,
                "root_host_user",
            )
        workspace = request.workspace.resolve()
        mount = f"type=bind,source={workspace},target=/workspace"
        container_name = self.name_factory()
        command = [
            docker,
            "create",
            "--name",
            container_name,
            "--pull",
            "never",
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
            self.container_user,
            "--mount",
            mount,
            "-w",
            "/workspace",
            request.image,
            *request.command,
        ]
        try:
            created = self.runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
                env={},
            )
            if created.returncode != 0:
                stderr = created.stderr or ""
                error_type = (
                    "image_missing"
                    if "No such image" in stderr or "pull access denied" in stderr
                    else "docker_unavailable"
                )
                return ExecutionResult(
                    created.returncode,
                    created.stdout or "",
                    stderr,
                    _elapsed_ms(started, self.clock()),
                    False,
                    self.name,
                    error_type,
                )
            completed = self.runner(
                [docker, "start", "--attach", container_name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
                env={},
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
                "docker_unavailable",
            )
        finally:
            _force_remove(self.runner, docker, container_name)


def _force_remove(runner: Callable[..., Any], docker: str, container_name: str) -> None:
    try:
        runner(
            [docker, "rm", "--force", container_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env={},
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _container_user() -> str:
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if callable(getuid) and callable(getgid):
        return f"{getuid()}:{getgid()}"
    # Docker Desktop shares Windows/macOS host paths independently of Linux UID ownership.
    return "65532:65532"
