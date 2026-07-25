"""Workspace-scoped file tools."""

from __future__ import annotations

from pathlib import Path

from .base import RiskLevel, Tool, ToolContext, ToolResult


def _workspace_path(workspace: Path, value: str) -> Path:
    workspace = workspace.resolve()
    candidate = (workspace / value).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("Path escapes the configured workspace")
    return candidate


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_chars": {"type": "integer"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        try:
            path = _workspace_path(context.workspace, str(arguments["path"]))
        except ValueError as exc:
            return ToolResult(False, str(exc))
        limit = max(1, min(int(arguments.get("max_chars", 20_000)), 100_000))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(False, f"Cannot read {path}: {exc}")
        truncated = len(text) > limit
        return ToolResult(True, text[:limit], {"path": str(path), "truncated": truncated})


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write UTF-8 text to a file inside the workspace."
    risk_level = RiskLevel.REVIEW
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def assess_risk(self, arguments: dict[str, object]) -> tuple[RiskLevel, str]:
        if bool(arguments.get("overwrite", False)):
            return RiskLevel.REVIEW, "file overwrite requested"
        return RiskLevel.SAFE, "new file write"

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        try:
            path = _workspace_path(context.workspace, str(arguments["path"]))
        except ValueError as exc:
            return ToolResult(False, str(exc))
        overwrite = bool(arguments.get("overwrite", False))
        if path.exists() and not overwrite:
            return ToolResult(False, "File already exists; set overwrite=true to replace it")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(arguments["content"]), encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"Cannot write {path}: {exc}")
        return ToolResult(True, f"Wrote {path}", {"path": str(path)})
