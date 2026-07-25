"""Privacy-conscious JSONL audit records for agent tool actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_path


class AuditLogError(RuntimeError):
    """Raised when an audit record cannot be persisted."""


class AuditLogger:
    def __init__(self, filepath: str | Path | None = None) -> None:
        self.filepath = Path(filepath) if filepath else user_data_path("smartcli") / "audit.jsonl"

    def record(self, event: dict[str, Any]) -> None:
        value = {"timestamp": datetime.now(UTC).isoformat(), **event}
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with self.filepath.open("a", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
        except OSError as exc:
            raise AuditLogError(f"Cannot write agent audit log: {exc}") from exc


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep useful target metadata without persisting commands or file content."""
    summary: dict[str, Any] = {"keys": sorted(arguments)}
    if isinstance(arguments.get("path"), str):
        summary["path"] = arguments["path"]
    serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    summary["sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return summary
