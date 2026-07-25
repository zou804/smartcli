"""Shell execution tool with risk classification."""

from __future__ import annotations

import os
import subprocess

from .base import RiskLevel, Tool, ToolContext, ToolResult
from .safety import ShellSafetyPolicy


class ShellTool(Tool):
    name = "shell"
    description = (
        "Run PowerShell on Windows or /bin/sh on POSIX in the workspace; return stdout/stderr."
    )
    risk_level = RiskLevel.REVIEW
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout_seconds": {"type": "integer", "description": "Timeout from 1 to 120"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, policy: ShellSafetyPolicy | None = None) -> None:
        self.policy = policy or ShellSafetyPolicy()

    def assess_risk(self, arguments: dict[str, object]) -> tuple[RiskLevel, str]:
        return self.policy.assess(str(arguments.get("command", "")))

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        command = str(arguments["command"])
        risk, reason = self.policy.assess(command)
        if risk is RiskLevel.BLOCKED:
            return ToolResult(False, f"Action blocked by safety policy: {reason}")
        timeout = max(1, min(int(arguments.get("timeout_seconds", 30)), 120))
        shell_command = (
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
            if os.name == "nt"
            else ["/bin/sh", "-c", command]
        )
        try:
            completed = subprocess.run(
                shell_command,
                cwd=context.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"Command timed out after {timeout} seconds")
        output = "\n".join(
            part for part in (completed.stdout.rstrip(), completed.stderr.rstrip()) if part
        )
        return ToolResult(
            completed.returncode == 0,
            output or f"Command exited with code {completed.returncode} and produced no output",
            {"exit_code": completed.returncode},
        )
