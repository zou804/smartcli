"""Persistent Agent run reports, file checkpoints, and hash-guarded undo."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from .audit import summarize_arguments
from .storage import InterProcessFileLock, StorageLockError
from .tools import ToolContext, ToolResult


class RunStorageError(RuntimeError):
    """Raised when a run report or checkpoint cannot be safely persisted."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunJournal:
    def __init__(self, store: RunStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document
        self.run_id = str(document["run_id"])

    def prepare_action(
        self, tool: str, arguments: dict[str, Any], context: ToolContext
    ) -> int | None:
        if tool not in {"write_file", "apply_patch"} or not isinstance(
            arguments.get("path"), str
        ):
            return None
        workspace = context.workspace.resolve()
        raw_path = workspace / str(arguments["path"])
        path = raw_path.resolve()
        if path != workspace and workspace not in path.parents:
            raise RunStorageError("Cannot checkpoint a path outside the run workspace")
        current = raw_path
        while current != workspace:
            if current.is_symlink():
                raise RunStorageError("Cannot checkpoint a symbolic-link path")
            if current.parent == current:
                break
            current = current.parent
        existed = path.is_file()
        try:
            before = path.read_bytes() if existed else b""
            mode = stat.S_IMODE(path.stat().st_mode) if existed else None
        except OSError as exc:
            raise RunStorageError(f"Cannot checkpoint {path}: {exc}") from exc
        if len(before) > 1_000_000:
            raise RunStorageError("Cannot checkpoint a file larger than 1,000,000 bytes")
        change = {
            "path": path.relative_to(workspace).as_posix(),
            "state": "prepared",
            "existed": existed,
            "before_sha256": hashlib.sha256(before).hexdigest() if existed else None,
            "before_content_base64": base64.b64encode(before).decode("ascii") if existed else None,
            "before_mode": mode,
            "after_sha256": None,
        }
        self.document["changes"].append(change)
        self.store._write(self.document)
        return len(self.document["changes"]) - 1

    def record_action(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: ToolResult,
        checkpoint: int | None,
    ) -> None:
        self.document["actions"].append(
            {
                "timestamp": _now(),
                "tool": tool,
                "success": result.success,
                "arguments": summarize_arguments(arguments),
                "metadata": result.metadata,
            }
        )
        if checkpoint is not None:
            change = self.document["changes"][checkpoint]
            change["state"] = "applied" if result.success else "failed"
            if result.success:
                change["after_sha256"] = result.metadata.get("sha256")
                if not isinstance(change["after_sha256"], str):
                    raise RunStorageError("Write tool did not return the resulting SHA-256")
        self.store._write(self.document)

    def complete(self, *, final: str, steps: int, plan: tuple[str, ...]) -> None:
        self.document.update(
            {
                "status": "completed",
                "completed_at": _now(),
                "result": {"final": final, "steps": steps, "plan": list(plan)},
            }
        )
        self.store._write(self.document)

    def set_telemetry(self, value: dict[str, Any]) -> None:
        self.document["telemetry"] = value
        self.store._write(self.document)

    def fail(self, error: str) -> None:
        self.document.update(
            {
                "status": "failed",
                "completed_at": _now(),
                "result": {"error": error},
            }
        )
        self.store._write(self.document)


class RunStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else user_data_path("smartcli") / "runs"

    def start(self, workspace: Path, task: str) -> RunJournal:
        run_id = f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        document: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "running",
            "started_at": _now(),
            "completed_at": None,
            "workspace": str(workspace.resolve()),
            "task": {
                "chars": len(task),
                "sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                "preview": task[:500],
            },
            "actions": [],
            "changes": [],
            "telemetry": None,
            "result": None,
        }
        self._write(document)
        return RunJournal(self, document)

    def get(self, run_id: str) -> dict[str, Any]:
        if not run_id.startswith("run_") or any(char in run_id for char in "/\\"):
            raise RunStorageError("Invalid run ID")
        path = self.root / f"{run_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RunStorageError(f"Run not found: {run_id}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RunStorageError(f"Cannot read run {run_id}: {exc}") from exc
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise RunStorageError(f"Invalid run report: {run_id}")
        return value

    def list(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        reports = []
        for path in self.root.glob("run_*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and isinstance(value.get("run_id"), str):
                reports.append(
                    {
                        "run_id": value["run_id"],
                        "status": value.get("status"),
                        "started_at": value.get("started_at"),
                        "workspace": value.get("workspace"),
                        "task_preview": value.get("task", {}).get("preview", ""),
                        "actions": len(value.get("actions", [])),
                        "changes": sum(
                            item.get("state") == "applied" for item in value.get("changes", [])
                        ),
                    }
                )
        return sorted(reports, key=lambda item: str(item["started_at"]), reverse=True)

    def public_report(self, run_id: str) -> dict[str, Any]:
        document = self.get(run_id)
        public = {**document}
        public["changes"] = [
            {
                key: value
                for key, value in change.items()
                if key not in {"before_content_base64", "before_mode"}
            }
            for change in document.get("changes", [])
        ]
        return public

    def undo(self, run_id: str) -> dict[str, Any]:
        document = self.get(run_id)
        if document.get("status") == "undone":
            raise RunStorageError(f"Run is already undone: {run_id}")
        workspace = Path(str(document.get("workspace", ""))).resolve()
        if not workspace.is_dir():
            raise RunStorageError(f"Run workspace is unavailable: {workspace}")
        applied = [item for item in document.get("changes", []) if item.get("state") == "applied"]
        if not applied:
            raise RunStorageError(f"Run has no applied file changes: {run_id}")

        latest_by_path: dict[str, dict[str, Any]] = {}
        for change in applied:
            latest_by_path[str(change["path"])] = change
        for relative, change in latest_by_path.items():
            path = self._undo_path(workspace, relative)
            if not path.is_file():
                raise RunStorageError(
                    f"Cannot undo because the current file is missing: {relative}"
                )
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash != change.get("after_sha256"):
                raise RunStorageError(
                    f"Cannot undo because {relative} changed after the Agent run"
                )

        restored: list[str] = []
        removed: list[str] = []
        for change in reversed(applied):
            relative = str(change["path"])
            path = self._undo_path(workspace, relative)
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash != change.get("after_sha256"):
                raise RunStorageError(f"Cannot safely continue undo for {relative}")
            if bool(change.get("existed")):
                encoded = change.get("before_content_base64")
                if not isinstance(encoded, str):
                    raise RunStorageError(f"Run checkpoint is incomplete for {relative}")
                content = base64.b64decode(encoded, validate=True)
                self._atomic_restore(path, content, change.get("before_mode"))
                restored.append(relative)
            else:
                path.unlink()
                removed.append(relative)

        document["status"] = "undone"
        document["undone_at"] = _now()
        self._write(document)
        return {"run_id": run_id, "restored": restored, "removed": removed}

    def _write(self, document: dict[str, Any]) -> None:
        run_id = str(document["run_id"])
        path = self.root / f"{run_id}.json"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with InterProcessFileLock(path):
                fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(document, stream, ensure_ascii=False, indent=2)
                        stream.write("\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp_name, path)
                except BaseException:
                    Path(temp_name).unlink(missing_ok=True)
                    raise
        except (OSError, StorageLockError) as exc:
            raise RunStorageError(f"Cannot write run report {run_id}: {exc}") from exc

    @staticmethod
    def _undo_path(workspace: Path, relative: str) -> Path:
        raw = workspace / relative
        current = raw
        while current != workspace:
            if current.is_symlink():
                raise RunStorageError(f"Cannot undo through a symbolic link: {relative}")
            if current.parent == current:
                break
            current = current.parent
        path = raw.resolve()
        if path != workspace and workspace not in path.parents:
            raise RunStorageError(f"Undo path escapes the recorded workspace: {relative}")
        return path

    @staticmethod
    def _atomic_restore(path: Path, content: bytes, mode: Any) -> None:
        temp_name: str | None = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if isinstance(mode, int):
                os.chmod(temp_name, mode)
            os.replace(temp_name, path)
        except OSError as exc:
            raise RunStorageError(f"Cannot restore {path}: {exc}") from exc
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)
