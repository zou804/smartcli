from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Note:
    id: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = "manual"
    model: str | None = None
    role: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Note:
        """Load current or legacy note data."""
        content = str(value.get("content", ""))
        lines = content.splitlines()
        raw_tags = value.get("tags", [])
        if raw_tags is None:
            raw_tags = []
        if not isinstance(raw_tags, list):
            raise ValueError("Note tags must be a JSON array")
        return cls(
            id=str(value.get("id", "")),
            title=str(value.get("title") or (lines[0][:80] if lines else "Untitled")),
            content=content,
            tags=[str(tag) for tag in raw_tags],
            source=str(value.get("source", "manual")),
            model=value.get("model"),
            role=value.get("role"),
            created_at=str(value.get("created_at", datetime.now(UTC).isoformat())),
        )
