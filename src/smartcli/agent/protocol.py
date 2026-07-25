"""Strict JSON wire protocol between the model and the agent runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    """Raised when the model does not follow the agent JSON protocol."""


@dataclass(frozen=True)
class AgentAction:
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentDecision:
    thought: str
    plan: tuple[str, ...] = ()
    action: AgentAction | None = None
    final: str | None = None


def parse_decision(text: str) -> AgentDecision:
    """Parse exactly one action or one final response."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1])
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:].lstrip("\r\n")
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Model output is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Model output must be a JSON object")
    thought = value.get("thought", "")
    if not isinstance(thought, str):
        raise ProtocolError("thought must be a string")
    raw_plan = value.get("plan", [])
    if not isinstance(raw_plan, list) or not all(isinstance(item, str) for item in raw_plan):
        raise ProtocolError("plan must be an array of strings")
    raw_action = value.get("action")
    final = value.get("final")
    if (raw_action is None) == (final is None):
        raise ProtocolError("Provide exactly one of action or final")
    if final is not None:
        if not isinstance(final, str) or not final.strip():
            raise ProtocolError("final must be a non-empty string")
        return AgentDecision(thought, tuple(raw_plan), final=final)
    if not isinstance(raw_action, dict):
        raise ProtocolError("action must be an object")
    tool = raw_action.get("tool")
    arguments = raw_action.get("arguments")
    if not isinstance(tool, str) or not tool:
        raise ProtocolError("action.tool must be a non-empty string")
    if not isinstance(arguments, dict):
        raise ProtocolError("action.arguments must be an object")
    return AgentDecision(thought, tuple(raw_plan), action=AgentAction(tool, arguments))
