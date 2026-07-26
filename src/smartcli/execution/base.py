"""Contracts shared by local and isolated execution backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExecutionRequest:
    command: tuple[str, ...]
    workspace: Path
    timeout_seconds: int
    environment: dict[str, str] = field(default_factory=dict)
    network: str = "none"
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 128
    image: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_ms: int
    timed_out: bool
    backend: str
    error_type: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error_type is None


class ExecutionBackend(Protocol):
    name: str

    def run(self, request: ExecutionRequest) -> ExecutionResult: ...
