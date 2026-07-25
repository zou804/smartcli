"""Structured, read-only Git operations that never invoke a command shell."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .base import Tool, ToolContext, ToolResult


class GitTool(Tool):
    name = "git"
    description = (
        "Run one structured read-only Git operation: status, diff, log, show, or ls_files. "
        "No arbitrary command, shell syntax, hooks, network operation, or mutation is supported."
    )
    capability = "git"
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "One of: status, diff, log, show, ls_files",
            },
            "path": {"type": "string"},
            "revision": {"type": "string"},
            "staged": {"type": "boolean"},
            "max_count": {"type": "integer"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["operation"],
        "additionalProperties": False,
    }
    _revision = re.compile(r"[A-Za-z0-9_./~^{}:+]+")

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        operation = str(arguments["operation"])
        try:
            command = self._command(operation, arguments, context.workspace)
            command[0] = self._git_executable(context.workspace)
        except ValueError as exc:
            return ToolResult(False, str(exc))
        timeout = max(1, min(int(arguments.get("timeout_seconds", 30)), 120))
        try:
            completed = subprocess.run(
                command,
                cwd=context.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"Git operation failed to start: {exc}")
        output = "\n".join(
            part for part in (completed.stdout.rstrip(), completed.stderr.rstrip()) if part
        )
        return ToolResult(
            completed.returncode == 0,
            output or f"Git exited with code {completed.returncode} and produced no output",
            {"operation": operation, "exit_code": completed.returncode},
        )

    def _command(
        self, operation: str, arguments: dict[str, object], workspace: Path
    ) -> list[str]:
        prefix = [
            "git",
            "-c",
            f"safe.directory={workspace.resolve()}",
            "-c",
            "core.fsmonitor=false",
            "--no-pager",
        ]
        path_args = self._path_arguments(arguments.get("path"), workspace)
        if operation == "status":
            return [*prefix, "status", "--short", "--branch"]
        if operation == "diff":
            staged = ["--cached"] if bool(arguments.get("staged", False)) else []
            return [*prefix, "diff", "--no-ext-diff", "--no-textconv", *staged, *path_args]
        if operation == "log":
            count = max(1, min(int(arguments.get("max_count", 20)), 100))
            return [*prefix, "log", f"--max-count={count}", "--format=%h %ad %s", "--date=short"]
        if operation == "show":
            revision = str(arguments.get("revision", "HEAD"))
            if not self._revision.fullmatch(revision) or revision.startswith("-"):
                raise ValueError("Invalid Git revision")
            return [
                *prefix,
                "show",
                "--no-ext-diff",
                "--no-textconv",
                "--format=fuller",
                revision,
                *path_args,
            ]
        if operation == "ls_files":
            return [*prefix, "ls-files", *path_args]
        raise ValueError(f"Unsupported Git operation: {operation}")

    @staticmethod
    def _path_arguments(value: object, workspace: Path) -> list[str]:
        if value is None:
            return []
        raw = workspace / str(value)
        resolved = raw.resolve()
        workspace = workspace.resolve()
        if resolved != workspace and workspace not in resolved.parents:
            raise ValueError("Git path escapes the configured workspace")
        return ["--", resolved.relative_to(workspace).as_posix()]

    @staticmethod
    def _environment() -> dict[str, str]:
        allowed = {"COMSPEC", "HOME", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
        environment = {
            name: value for name, value in os.environ.items() if name.upper() in allowed
        }
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_PAGER": "cat",
                "PAGER": "cat",
            }
        )
        return environment

    @staticmethod
    def _git_executable(workspace: Path) -> str:
        executable = shutil.which("git")
        if executable is None:
            raise ValueError("Git executable was not found on PATH")
        resolved = Path(executable).resolve()
        workspace = workspace.resolve()
        if resolved == workspace or workspace in resolved.parents:
            raise ValueError("Refusing to execute Git from inside the workspace")
        return str(resolved)
