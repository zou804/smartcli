"""Common contracts shared by every agent tool."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class RiskLevel(StrEnum):
    SAFE = "safe"
    REVIEW = "review"
    HIGH = "high"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolContext:
    workspace: Path


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def observation(self, limit: int = 12_000) -> str:
        text = self.output
        if len(text) > limit:
            text = f"{text[:limit]}\n... [observation truncated]"
        status = "success" if self.success else "failure"
        metadata = (
            f"\nTool metadata: {json.dumps(self.metadata, ensure_ascii=False)}"
            if self.metadata
            else ""
        )
        return f"Tool status: {status}{metadata}\n{text}"


class Tool(ABC):
    """A discoverable, JSON-invoked capability available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = RiskLevel.SAFE

    def assess_risk(self, arguments: dict[str, Any]) -> tuple[RiskLevel, str]:
        return self.risk_level, self.risk_level.value

    def validate(self, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        required = self.input_schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"Missing required tool arguments: {', '.join(missing)}")
        properties = self.input_schema.get("properties", {})
        expected_types = {"string": str, "integer": int, "boolean": bool, "array": list}
        for name, value in arguments.items():
            if name not in properties:
                raise ValueError(f"Unknown tool argument: {name}")
            expected = expected_types.get(properties[name].get("type"))
            wrong_integer = expected is int and isinstance(value, bool)
            if expected is not None and (not isinstance(value, expected) or wrong_integer):
                raise ValueError(f"Tool argument {name!r} must be {properties[name]['type']}")

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool after validation and safety approval."""
