"""Explicit project checks executed without a command shell."""

from __future__ import annotations

import os
import subprocess
import sys

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

    def assess_risk(self, arguments: dict[str, object]) -> tuple[RiskLevel, str]:
        check = str(arguments.get("check", ""))
        return RiskLevel.HIGH, f"project check {check!r} may execute repository code"

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        check = str(arguments["check"])
        commands = {
            "tests": [sys.executable, "-m", "pytest"],
            "lint": [sys.executable, "-m", "ruff", "check", "."],
            "compile": [sys.executable, "-m", "compileall", "-q", "src", "tests"],
        }
        command = commands.get(check)
        if command is None:
            return ToolResult(False, f"Unsupported project check: {check}")
        timeout = max(1, min(int(arguments.get("timeout_seconds", 120)), 600))
        allowed_environment = {
            "COMSPEC",
            "HOME",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        }
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper() in allowed_environment
        }
        environment.update({"PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        try:
            completed = subprocess.run(
                command,
                cwd=context.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"Project check timed out after {timeout} seconds")
        except OSError as exc:
            return ToolResult(False, f"Project check failed to start: {exc}")
        output = "\n".join(
            part for part in (completed.stdout.rstrip(), completed.stderr.rstrip()) if part
        )
        return ToolResult(
            completed.returncode == 0,
            output or f"Project check exited with code {completed.returncode}",
            {"check": check, "exit_code": completed.returncode, "timeout_seconds": timeout},
        )
