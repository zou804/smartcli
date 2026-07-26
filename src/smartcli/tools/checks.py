"""Explicit project checks executed without a command shell."""

from __future__ import annotations

import os

from ..execution import ExecutionBackend, ExecutionRequest
from ..policy import ProjectPolicy
from .base import RiskLevel, Tool, ToolContext, ToolResult


class ProjectCheckTool(Tool):
    name = "run_check"
    description = (
        "Run one approved local project check without a shell: tests, lint, or compile. "
        "Repository code may execute without an OS sandbox, so every check requires explicit "
        "confirmation. Sensitive environment variables are not inherited."
    )
    capability = "check"
    risk_level = RiskLevel.HIGH
    has_side_effects = True
    input_schema = {
        "type": "object",
        "properties": {
            "check": {
                "type": "string",
                "description": "One of: tests, lint, compile",
            },
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["check"],
        "additionalProperties": False,
    }

    def __init__(self, backend: ExecutionBackend, policy: ProjectPolicy) -> None:
        self.backend = backend
        self.policy = policy

    def assess_risk(self, arguments: dict[str, object]) -> tuple[RiskLevel, str]:
        check = str(arguments.get("check", ""))
        return RiskLevel.HIGH, f"project check {check!r} may execute repository code"

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        check = str(arguments["check"])
        commands = {
            "tests": ("python", "-m", "pytest"),
            "lint": ("python", "-m", "ruff", "check", "."),
            "compile": ("python", "-m", "compileall", "-q", "src", "tests"),
        }
        command = commands.get(check)
        if command is None:
            return ToolResult(False, f"Unsupported project check: {check}")
        if check not in self.policy.checks.allowed:
            return ToolResult(False, f"Project check {check!r} is not allowed by project policy")
        execution = self.policy.execution
        requested_timeout = max(1, min(int(arguments.get("timeout_seconds", 120)), 600))
        timeout = min(requested_timeout, execution.timeout_seconds)
        result = self.backend.run(
            ExecutionRequest(
                command=command,
                workspace=context.workspace,
                timeout_seconds=timeout,
                environment=dict(os.environ),
                network=execution.network,
                memory_mb=execution.memory_mb,
                cpus=execution.cpus,
                pids_limit=execution.pids_limit,
                image=execution.image,
            )
        )
        output = "\n".join(
            part for part in (result.stdout.rstrip(), result.stderr.rstrip()) if part
        )
        return ToolResult(
            result.success,
            output or _result_message(result, timeout),
            {
                "check": check,
                "exit_code": result.exit_code,
                "timeout_seconds": timeout,
                "backend": result.backend,
                "elapsed_ms": result.elapsed_ms,
                "timed_out": result.timed_out,
                "error_type": result.error_type,
            },
        )


def _result_message(result: object, timeout: int) -> str:
    if getattr(result, "timed_out", False):
        return f"Project check timed out after {timeout} seconds"
    error_type = getattr(result, "error_type", None)
    if error_type:
        return f"Project check failed: {error_type}"
    return f"Project check exited with code {getattr(result, 'exit_code', None)}"
