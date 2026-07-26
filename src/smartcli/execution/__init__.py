"""Execution backends for approved project checks."""

from ..policy import ProjectPolicy
from .base import ExecutionBackend, ExecutionRequest, ExecutionResult
from .docker import DockerExecutionBackend
from .local import LocalExecutionBackend


def backend_from_policy(policy: ProjectPolicy) -> ExecutionBackend:
    """Create the configured backend without silently weakening isolation."""
    execution = policy.execution
    if execution.backend == "docker":
        return DockerExecutionBackend()
    return LocalExecutionBackend()

__all__ = [
    "DockerExecutionBackend",
    "ExecutionBackend",
    "ExecutionRequest",
    "ExecutionResult",
    "LocalExecutionBackend",
    "backend_from_policy",
]
