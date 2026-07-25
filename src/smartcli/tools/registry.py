"""Tool discovery and registration."""

from __future__ import annotations

from collections.abc import Iterable

from .base import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"Tool already registered or has an invalid name: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc

    def specs(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "risk_level": tool.risk_level.value,
                "capability": tool.capability,
                "has_side_effects": tool.has_side_effects,
            }
            for tool in self._tools.values()
        ]

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)
