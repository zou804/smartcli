"""Short-term context windows and long-term memory extension points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MemoryEvent:
    kind: str
    content: str


class ShortTermMemory:
    """A character-bounded sliding window of recent ReAct events."""

    def __init__(self, *, max_events: int = 24, max_chars: int = 24_000) -> None:
        if max_events < 1 or max_chars < 1:
            raise ValueError("Memory limits must be positive")
        self.max_events = max_events
        self.max_chars = max_chars
        self._events: list[MemoryEvent] = []

    def add(self, kind: str, content: str) -> None:
        self._events.append(MemoryEvent(kind, content))
        while len(self._events) > self.max_events:
            self._events.pop(0)
        while len(self._events) > 1 and self._size() > self.max_chars:
            self._events.pop(0)
        if self._events and self._size() > self.max_chars:
            latest = self._events[-1]
            available = max(0, self.max_chars - len(latest.kind) - 4)
            content = latest.content[-available:] if available else ""
            self._events[-1] = MemoryEvent(latest.kind, content)

    def events(self) -> tuple[MemoryEvent, ...]:
        return tuple(self._events)

    def render(self) -> str:
        return "\n\n".join(f"[{event.kind}]\n{event.content}" for event in self._events)

    def _size(self) -> int:
        return sum(len(event.kind) + len(event.content) + 4 for event in self._events)


class LongTermMemory(Protocol):
    """Interface reserved for a vector store or other persistent memory."""

    def search(self, query: str, *, limit: int = 5) -> list[str]: ...

    def store(self, content: str, *, metadata: dict[str, str] | None = None) -> None: ...


class NullLongTermMemory:
    def search(self, query: str, *, limit: int = 5) -> list[str]:
        del query, limit
        return []

    def store(self, content: str, *, metadata: dict[str, str] | None = None) -> None:
        del content, metadata
