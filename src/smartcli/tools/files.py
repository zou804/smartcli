"""Workspace-scoped file tools."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .base import RiskLevel, Tool, ToolContext, ToolResult

_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)
_IGNORED_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "node_modules", "venv"}
)


def _is_sensitive_path(path: Path) -> bool:
    name = path.name.casefold()
    if name in _SENSITIVE_NAMES or name.endswith((".key", ".p12", ".pfx")):
        return True
    if name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}:
        return True
    return any(part.casefold() in {".aws", ".git", ".ssh"} for part in path.parts)


def _workspace_path(workspace: Path, value: str) -> Path:
    workspace = workspace.resolve()
    candidate = (workspace / value).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("Path escapes the configured workspace")
    return candidate


class ListFilesTool(Tool):
    name = "list_files"
    description = "List files and directories inside the workspace before choosing files to read."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean"},
            "max_entries": {"type": "integer"},
        },
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        try:
            root = _workspace_path(context.workspace, str(arguments.get("path", ".")))
        except ValueError as exc:
            return ToolResult(False, str(exc))
        if not root.is_dir():
            return ToolResult(False, f"Not a directory: {root}")
        recursive = bool(arguments.get("recursive", False))
        limit = max(1, min(int(arguments.get("max_entries", 200)), 2_000))
        try:
            entries = root.rglob("*") if recursive else root.iterdir()
            visible = []
            for path in entries:
                relative_path = path.relative_to(context.workspace)
                if _is_sensitive_path(path) or any(
                    part.casefold() in _IGNORED_DIRECTORIES for part in relative_path.parts
                ):
                    continue
                relative = relative_path.as_posix()
                visible.append(f"{relative}/" if path.is_dir() else relative)
                if len(visible) >= limit:
                    break
        except OSError as exc:
            return ToolResult(False, f"Cannot list {root}: {exc}")
        return ToolResult(
            True,
            "\n".join(visible) or "Directory is empty",
            {"path": str(root), "entries": len(visible), "limit_reached": len(visible) >= limit},
        )


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
        if _is_sensitive_path(path):
            return ToolResult(False, "Access to sensitive credential files is blocked")
        limit = max(1, min(int(arguments.get("max_chars", 20_000)), 100_000))
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(False, f"Cannot read {path}: {exc}")
        truncated = len(text) > limit
        return ToolResult(
            True,
            text[:limit],
            {
                "path": str(path),
                "truncated": truncated,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or atomically replace a UTF-8 file inside the workspace. Every write requires "
        "user confirmation. Replacing a file also requires its current SHA-256 hash."
    )
    risk_level = RiskLevel.REVIEW
    capability = "write"
    has_side_effects = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean"},
            "expected_sha256": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def assess_risk(self, arguments: dict[str, object]) -> tuple[RiskLevel, str]:
        if bool(arguments.get("overwrite", False)):
            return RiskLevel.REVIEW, "atomic file replacement requires approval"
        return RiskLevel.REVIEW, "new file creation requires approval"

    def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        self.validate(arguments)
        raw_path = context.workspace.resolve() / str(arguments["path"])
        current = raw_path
        while current != context.workspace.resolve():
            if current.is_symlink():
                return ToolResult(False, "Writing through symbolic links is blocked")
            if current.parent == current:
                break
            current = current.parent
        try:
            path = _workspace_path(context.workspace, str(arguments["path"]))
        except ValueError as exc:
            return ToolResult(False, str(exc))
        if _is_sensitive_path(path):
            return ToolResult(False, "Access to sensitive credential files is blocked")
        content = str(arguments["content"])
        encoded = content.encode("utf-8")
        if len(encoded) > 1_000_000:
            return ToolResult(False, "File content exceeds the 1,000,000-byte write limit")
        overwrite = bool(arguments.get("overwrite", False))
        existed = path.exists()
        if existed and not overwrite:
            return ToolResult(False, "File already exists; set overwrite=true to replace it")
        if existed:
            expected = arguments.get("expected_sha256")
            if not isinstance(expected, str) or not expected:
                return ToolResult(False, "expected_sha256 is required when replacing a file")
            try:
                current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                return ToolResult(False, f"Cannot verify {path}: {exc}")
            if expected.casefold() != current_hash:
                return ToolResult(
                    False,
                    "File changed since it was inspected; expected_sha256 does not match",
                    {"current_sha256": current_hash},
                )
        temp_name: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if existed:
                latest_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                if latest_hash != current_hash:
                    return ToolResult(False, "File changed while preparing the atomic replacement")
                os.chmod(temp_name, path.stat().st_mode)
            elif path.exists():
                return ToolResult(False, "Target file appeared while preparing the atomic write")
            os.replace(temp_name, path)
        except OSError as exc:
            return ToolResult(False, f"Cannot write {path}: {exc}")
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)
        return ToolResult(
            True,
            f"Wrote {path}",
            {"path": str(path), "sha256": hashlib.sha256(encoded).hexdigest()},
        )
