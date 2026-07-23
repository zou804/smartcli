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
        return cls(
            id=str(value.get("id", "")),
            title=str(value.get("title") or content.splitlines()[0][:80] or "Untitled"),
            content=content,
            tags=[str(tag) for tag in value.get("tags", [])],
            source=str(value.get("source", "manual")),
            model=value.get("model"),
            role=value.get("role"),
            created_at=str(value.get("created_at", datetime.now(UTC).isoformat())),
        )
